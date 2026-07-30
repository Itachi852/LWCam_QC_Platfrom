from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import logging
import os
import shutil
from pathlib import Path

from fastapi import APIRouter, File, Form, Query, UploadFile
from fastapi.responses import FileResponse
from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import object_session

from app.core.errors import ApiCodes, BusinessError
from app.core.paths import to_db, to_local
from app.core.responses import ApiResponse, PageResult, ok
from app.dependencies import DbSession, QcUser
from app.models.capture import CaptureBox, CaptureFolder, CaptureImage
from app.models.project import Project, UserProject
from app.models.qc_session import ReworkLog
from app.models.user import User
from app.schemas.qc import (
    BatchLuminanceRequest,
    BatchRotateRequest,
    FolderMetadataVO,
    CropImageRequest,
    DeskewImageRequest,
    LuminanceRequest,
    MetadataTemplateFieldVO,
    MetadataTemplateVO,
    MetadataUpdateRequest,
    MetadataQcImageVO,
    MetadataQcTaskVO,
    RejectRequest,
    ReorderImagesRequest,
    ReviewRequest,
    RotateImageRequest,
    SeparationMarkersRequest,
)
from app.services.luminance import apply_luminance
from app.services.previews import PREVIEW_MIME_TYPE, generate_preview_image, generate_thumbnail_file
from app.services.qc_audit import write_qc_audit
from app.services.qc_separation import SeparationFileError, SeparationFileTransaction
from app.services.qc_drafts import (
    create_inserted_image,
    delete_image as draft_delete_image,
    dirty_image_ids_from_manifest,
    discard_draft,
    draft_dir,
    draft_image_item,
    draft_image_path,
    draft_summary,
    draft_version,
    ensure_work_copy,
    mark_dirty,
    mark_dirty_no_history,
    metadata_dirty_from_manifest,
    metadata_values_from_manifest,
    read_manifest,
    redo_manifest,
    replace_image as draft_replace_image,
    restore_original as draft_restore_original,
    save_metadata_draft,
    set_order,
    set_separation_markers,
    undo_manifest,
    visible_order,
)

router = APIRouter(prefix="/qc/metadata-tasks", tags=["metadata-qc"])
logger = logging.getLogger(__name__)
DB_TO_API_STATUS = {"pending": "pending", "pass": "passed", "rework": "rework"}

# Accepted for Replace / Insert-before. Capture output is .jpg today and only
# becomes .tif at export (capture_folders.is_tif_converted), so restricting
# these actions to .tif made them unusable on pre-export folders. Matches the
# set the bundled Luminance Correction tool already accepts.
UPLOAD_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}
TITLE_RECORD_TYPE_MAP = {
    "WWI South African Mounted Rifles Military Personnel Cards": "Military Service Records",
    "WWI South African Mounted Rifles Military Indexes": "Military Service Record Indexes",
    "WWI Medical Files": "Military Medical Records",
    "WWII Medical Files": "Military Medical Records",
}
DEFAULT_METADATA_TEMPLATE = {
    "fields": [
        {
            "key": "coverTag",
            "label": "Cover Tag",
            "input": "select",
            "mandatory": True,
            "exported": False,
            "options": [
                "Cover Will Be Captured",
                "Cover Will not Be Captured",
                "Cover Unavailable or Missing",
            ],
        },
        {
            "key": "imageTags",
            "label": "Image Tags",
            "input": "select",
            "mandatory": False,
            "exported": False,
            "options": [
                "Faded or Damaged Documents",
                "Reflective Surface",
                "Document Glued Together",
            ],
        },
        {
            "key": "title",
            "label": "Title",
            "input": "select",
            "mandatory": True,
            "exported": True,
            "options": list(TITLE_RECORD_TYPE_MAP.keys()),
        },
        {"key": "volume", "label": "Volume", "input": "text", "mandatory": True, "exported": True},
        {
            "key": "startDate",
            "label": "Start Date",
            "input": "select",
            "mandatory": True,
            "exported": True,
            "options": ["1914", "1939"],
        },
        {
            "key": "endDate",
            "label": "End Date",
            "input": "select",
            "mandatory": True,
            "exported": True,
            "options": ["1918", "1945"],
        },
        {
            "key": "archivalRefNo",
            "label": "Archival Reference Number",
            "input": "text",
            "mandatory": False,
            "exported": True,
        },
        {"key": "place", "label": "Place", "input": "fixed", "value": "South Africa"},
        {"key": "language", "label": "Language", "input": "fixed", "value": "English"},
        {
            "key": "recordCustodian",
            "label": "Record Custodian",
            "input": "fixed",
            "value": "South Africa Department of Defense",
        },
        {"key": "digitizingEntity", "label": "Digitizing Entity", "input": "fixed", "value": "Lifewood"},
        {"key": "captureOperatorId", "label": "Capture Operator ID", "input": "fixed", "value": "cis.user.MM38-RXW3"},
        {"key": "captureOperatorName", "label": "Capture Operator Name", "input": "fixed", "value": "lifewoodza01"},
    ],
    "titleRecordTypeMap": TITLE_RECORD_TYPE_MAP,
}
METADATA_FIELD_MAP = {
    "coverTag": "cover_tag",
    "imageTags": "image_tags",
    "title": "title",
    "volume": "volume",
    "startDate": "start_date",
    "endDate": "end_date",
    "archivalRefNo": "archival_ref_no",
    "recordType": "record_type",
    "place": "place",
    "language": "language",
    "recordCustodian": "record_custodian",
    "captureOperatorId": "capture_operator_id",
    "captureOperatorName": "capture_operator_name",
    "digitizingEntity": "digitizing_entity",
}


def now() -> datetime:
    """返回当前 UTC 时间。"""
    return datetime.now(timezone.utc)


def folder_options():
    """返回查询 Folder 时预加载图片、Box、项目和设备的选项。"""
    from sqlalchemy.orm import selectinload
    return (
        selectinload(CaptureFolder.images),
        selectinload(CaptureFolder.box).selectinload(CaptureBox.project),
        selectinload(CaptureFolder.device),
    )


def project_ids_for_user(db, user_id: int) -> list[int]:
    """查询 QC 用户已被授权访问的项目 ID。"""
    return list(db.scalars(select(UserProject.project_id).where(UserProject.user_id == user_id)).all())


def visible_folder_conditions(project_ids: list[int]):
    """构造 QC 可见任务的通用过滤条件。

    folder_path is written by LWCAM only after LWIP finishes deskew/crop/thumbnail
    processing, while qc_status defaults to 'PENDING' the moment the row syncs.
    Without the NULL check a folder becomes claimable before its images exist on
    disk, and every image request then 404s — so treat "has an image directory"
    as part of being a QC task at all.
    """
    return (
        CaptureFolder.is_deleted.is_not(True),
        CaptureFolder.folder_path.is_not(None),
        CaptureFolder.box.has(CaptureBox.is_deleted.is_not(True)),
        CaptureFolder.box.has(CaptureBox.project_id.in_(project_ids)),
        CaptureFolder.box.has(CaptureBox.project.has(Project.is_deleted.is_not(True))),
        CaptureFolder.images.any(),
    )


def safe_filename(value: str) -> str:
    """校验图片名为纯文件名，阻止路径穿越访问。"""
    filename = value.strip()
    if not filename or filename in {".", ".."} or "/" in filename or "\\" in filename:
        raise BusinessError(ApiCodes.BAD_REQUEST, "图片文件名无效")
    return filename


def safe_backup_part(value: str) -> str:
    return "".join(char if char.isalnum() or char in {"-", "_", "."} else "_" for char in value)


def thumbnail_target_path(folder: CaptureFolder, image: CaptureImage) -> Path | None:
    if not folder.thumbnail_path:
        return None
    directory = to_local(folder.thumbnail_path).resolve()
    filename = safe_filename(image.image_name)
    path = (directory / filename).resolve()
    try:
        path.relative_to(directory)
    except ValueError as error:
        raise BusinessError(ApiCodes.FORBIDDEN, "缩略图路径越界", 403) from error
    return path


def resolve_image_file(folder: CaptureFolder, image: CaptureImage, thumbnail: bool = False) -> Path:
    """解析并校验图片或缩略图的实际文件路径。"""
    directory_value = folder.thumbnail_path if thumbnail else folder.folder_path
    if not directory_value:
        raise BusinessError(ApiCodes.NOT_FOUND, "图片目录未配置", 404)
    directory = to_local(directory_value).resolve()
    filename = safe_filename(image.image_name)
    path = (directory / filename).resolve()
    try:
        path.relative_to(directory)
    except ValueError as error:
        raise BusinessError(ApiCodes.FORBIDDEN, "图片路径越界", 403) from error
    if not path.is_file():
        raise BusinessError(ApiCodes.NOT_FOUND, f"图片文件不存在: {filename}", 404)
    return path


def image_available(folder: CaptureFolder, image: CaptureImage) -> bool:
    try:
        resolve_image_file(folder, image)
        return True
    except BusinessError:
        return False


def metadata_snapshot(folder: CaptureFolder) -> dict:
    box = folder.box
    project = box.project
    return {
        "folderId": folder.id,
        "boxId": box.box_id,
        "boxName": box.box_name,
        "projectId": project.id if project else None,
        "projectName": project.project_name if project else None,
        "folderName": folder.folder_name,
        "folderSeq": folder.folder_seq,
        "deviceId": folder.device.device_id,
        "coverTag": folder.cover_tag,
        "imageTags": folder.image_tags,
        "title": folder.title,
        "volume": folder.volume,
        "startDate": folder.start_date.isoformat() if folder.start_date else None,
        "endDate": folder.end_date.isoformat() if folder.end_date else None,
        "archivalRefNo": folder.archival_ref_no,
        "recordType": folder.record_type,
        "place": folder.place,
        "language": folder.language,
        "recordCustodian": folder.record_custodian,
        "captureOperatorId": folder.capture_operator_id,
        "captureOperatorName": folder.capture_operator_name,
        "digitizingEntity": folder.digitizing_entity,
        "sourceCreatedAt": folder.source_created_at.isoformat() if folder.source_created_at else None,
        "sourceUpdatedAt": folder.source_updated_at.isoformat() if folder.source_updated_at else None,
    }


def metadata_template(folder: CaptureFolder) -> MetadataTemplateVO:
    project_template = (folder.box.project.template if folder.box and folder.box.project else None) or {}
    raw_fields = project_template.get("fields") if isinstance(project_template, dict) else None
    raw_mapping = project_template.get("titleRecordTypeMap") if isinstance(project_template, dict) else None
    fields_source = raw_fields if isinstance(raw_fields, list) and raw_fields else DEFAULT_METADATA_TEMPLATE["fields"]
    mapping_source = raw_mapping if isinstance(raw_mapping, dict) and raw_mapping else TITLE_RECORD_TYPE_MAP
    fields = []
    for item in fields_source:
        if not isinstance(item, dict) or not item.get("key"):
            continue
        default_item = next(
            (field for field in DEFAULT_METADATA_TEMPLATE["fields"] if field["key"] == item["key"]),
            {},
        )
        merged = {**default_item, **item}
        options = merged.get("options") or []
        fields.append(MetadataTemplateFieldVO(
            key=str(merged["key"]),
            label=str(merged.get("label") or merged["key"]),
            input=str(merged.get("input") or "text"),
            mandatory=bool(merged.get("mandatory")),
            exported=bool(merged.get("exported")),
            options=[str(option) for option in options],
            value=merged.get("value"),
        ))
    return MetadataTemplateVO(
        fields=fields,
        titleRecordTypeMap={str(key): str(value) for key, value in mapping_source.items()},
    )


def derive_record_type(title: str | None, template: MetadataTemplateVO) -> str | None:
    if not title:
        return None
    return template.titleRecordTypeMap.get(title) or TITLE_RECORD_TYPE_MAP.get(title)


def normalize_metadata_values(values: dict, template: MetadataTemplateVO) -> dict:
    result = dict(values)
    for field in template.fields:
        if field.input == "fixed":
            result[field.key] = field.value
    result["recordType"] = derive_record_type(result.get("title"), template)
    for key, value in list(result.items()):
        if isinstance(value, str):
            result[key] = value.strip() or None
    return result


def metadata_date(value):
    if isinstance(value, datetime) or value is None:
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if len(text) == 4 and text.isdigit():
            return datetime(int(text), 1, 1, tzinfo=timezone.utc)
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            return value
    return value


def validate_date_order(values: dict) -> None:
    start_date = metadata_date(values.get("startDate"))
    end_date = metadata_date(values.get("endDate"))
    if isinstance(start_date, datetime) and isinstance(end_date, datetime) and start_date > end_date:
        raise BusinessError(ApiCodes.BAD_REQUEST, "开始日期不能晚于结束日期", 400)


def effective_metadata_snapshot(folder: CaptureFolder, manifest: dict | None, template: MetadataTemplateVO) -> dict:
    snapshot = normalize_metadata_values(metadata_snapshot(folder), template)
    draft_values = metadata_values_from_manifest(manifest)
    if draft_values:
        snapshot.update(normalize_metadata_values(draft_values, template))
    return snapshot


def editable_metadata_to_dict(values) -> dict:
    return {
        "coverTag": values.coverTag,
        "imageTags": values.imageTags,
        "title": values.title,
        "volume": values.volume,
        "startDate": values.startDate,
        "endDate": values.endDate,
        "archivalRefNo": values.archivalRefNo,
        "recordType": values.recordType,
        "place": values.place,
        "language": values.language,
        "recordCustodian": values.recordCustodian,
        "captureOperatorId": values.captureOperatorId,
        "captureOperatorName": values.captureOperatorName,
        "digitizingEntity": values.digitizingEntity,
    }


def apply_metadata_to_folder(folder: CaptureFolder, values: dict, template: MetadataTemplateVO) -> None:
    normalized = normalize_metadata_values(values, template)
    normalized["startDate"] = metadata_date(normalized.get("startDate"))
    normalized["endDate"] = metadata_date(normalized.get("endDate"))
    for api_key, model_key in METADATA_FIELD_MAP.items():
        if api_key in normalized:
            setattr(folder, model_key, normalized[api_key])


def validate_metadata_for_approval(values: dict, template: MetadataTemplateVO) -> None:
    normalized = normalize_metadata_values(values, template)
    missing = [
        field.label
        for field in template.fields
        if field.mandatory and not normalized.get(field.key)
    ]
    if missing:
        raise BusinessError(ApiCodes.BAD_REQUEST, f"必填元数据未填写: {', '.join(missing)}", 400)
    validate_date_order(normalized)


def image_snapshot(folder: CaptureFolder) -> list[dict]:
    return [
        {
            "id": image.id,
            "name": image.image_name,
            "format": image.file_format,
            "createdAt": image.image_created_at.isoformat() if image.image_created_at else None,
            "updatedAt": image.image_updated_at.isoformat() if image.image_updated_at else None,
        }
        for image in sorted(folder.images, key=lambda item: (item.image_created_at or datetime.min.replace(tzinfo=timezone.utc), item.id))
    ]


def source_hash(folder: CaptureFolder) -> str:
    """对当前元数据和图片快照计算稳定的 SHA-256 版本指纹。"""
    payload = {"metadata": metadata_snapshot(folder), "images": image_snapshot(folder)}
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(raw.encode("utf-8")).hexdigest()


def folder_or_404(db, folder_id: int, user_id: int, lock: bool = False) -> CaptureFolder:
    """按 QC 项目权限获取 Folder；可选地为后续写操作加行锁。"""
    project_ids = project_ids_for_user(db, user_id)
    if not project_ids:
        raise BusinessError(ApiCodes.FORBIDDEN, "当前QC未分配项目", 403)
    from sqlalchemy.orm import selectinload
    statement = select(CaptureFolder).options(*folder_options()).where(
        CaptureFolder.id == folder_id, *visible_folder_conditions(project_ids)
    )
    if lock:
        statement = statement.with_for_update()
    folder = db.scalar(statement)
    if folder is None:
        raise BusinessError(ApiCodes.NOT_FOUND, "QC任务不存在或无权访问", 404)
    return folder


def assert_lock_owner(folder: CaptureFolder, user_id: str) -> None:
    """校验当前用户持有该 Folder 的审核锁，否则抛出冲突错误。"""
    if folder.qc_locked_by != user_id:
        raise BusinessError(ApiCodes.CONFLICT, "任务已不属于当前审核员", 409)


def to_task_vo(db, folder: CaptureFolder, viewer_user_id: str) -> MetadataQcTaskVO:
    """将 Folder 和图片组装成 QC 页面使用的任务视图模型。"""
    locked_by_viewer = folder.qc_locked_by == viewer_user_id
    if locked_by_viewer:
        status = "reviewing"
    else:
        status = DB_TO_API_STATUS.get(folder.qc_status.lower(), folder.qc_status.lower())

    assigned_user_id: int | None = None
    if folder.qc_locked_by:
        assigned_user_id = db.scalar(
            select(User.id).where(User.user_id == folder.qc_locked_by)
        )

    template = metadata_template(folder)
    manifest = read_manifest(folder.id, viewer_user_id) if locked_by_viewer else None
    dirty_image_ids = dirty_image_ids_from_manifest(manifest)
    metadata_dirty = metadata_dirty_from_manifest(manifest)
    current_draft_version = draft_version(folder.id, viewer_user_id) if dirty_image_ids or manifest else None
    official_images = sorted(
        folder.images,
        key=lambda item: (item.image_created_at or datetime.min.replace(tzinfo=timezone.utc), item.id),
    )
    official_by_id = {item.id: item for item in official_images}
    image_ids = visible_order(manifest, [item.id for item in official_images]) if locked_by_viewer else [item.id for item in official_images]
    marker_ids = set((manifest or {}).get("separation_markers", []))

    images = []
    for image_id in image_ids:
        draft_item = draft_image_item(manifest, image_id)
        if image_id < 0 and draft_item:
            version = current_draft_version or int(now().timestamp() * 1000)
            work_path = Path(draft_item.get("work_path", ""))
            images.append(MetadataQcImageVO(
                id=image_id,
                filename=draft_item.get("image_name") or work_path.name,
                available=work_path.is_file(),
                previewUrl=f"/api/qc/metadata-tasks/{folder.id}/images/{image_id}/preview?v={version}",
                draftState=draft_item.get("status"),
                separationStart=image_id in marker_ids,
            ))
            continue
        image = official_by_id.get(image_id)
        if image is None:
            continue
        if draft_item and current_draft_version is not None:
            version = current_draft_version
        else:
            version = int(((image.image_updated_at or image.image_created_at) or now()).timestamp() * 1000)
        images.append(MetadataQcImageVO(
            id=image.id,
            filename=image.image_name,
            available=image_available(folder, image),
            previewUrl=f"/api/qc/metadata-tasks/{folder.id}/images/{image.id}/preview?v={version}",
            draftState=(draft_item or {}).get("status"),
            separationStart=image.id in marker_ids,
        ))

    return MetadataQcTaskVO(
        id=folder.id,
        status=status,
        sourceHash=source_hash(folder),
        hasDraft=bool(dirty_image_ids or metadata_dirty or (manifest or {}).get("order") or (manifest or {}).get("separation_markers")),
        draftImageIds=dirty_image_ids,
        draftMetadataDirty=metadata_dirty,
        assignedTo=assigned_user_id,
        claimedAt=folder.qc_locked_at,
        submittedAt=folder.source_created_at or folder.updated_at,
        metadata=FolderMetadataVO(**effective_metadata_snapshot(folder, manifest, template)),
        metadataTemplate=template,
        imageCount=len(images),
        imageAvailable=bool(images) and all(item.available for item in images),
        images=images,
    )


def verify_reviewable_folder(folder: CaptureFolder, source_hash_value: str) -> None:
    current_hash = source_hash(folder)
    if source_hash_value != current_hash:
        raise BusinessError(ApiCodes.CONFLICT, "Folder宸叉洿鏂帮紝璇峰埛鏂板悗閲嶆柊瀹℃牳", 409)
    if folder.qc_status.lower() != "pending":
        raise BusinessError(ApiCodes.CONFLICT, "浠诲姟鐘舵€佸凡鍙樺寲", 409)


def ordered_official_images(folder: CaptureFolder) -> list[CaptureImage]:
    return sorted(folder.images, key=lambda item: (item.image_created_at or datetime.min.replace(tzinfo=timezone.utc), item.id))


def official_image_ids(folder: CaptureFolder) -> list[int]:
    return [image.id for image in ordered_official_images(folder)]


def draft_or_official_path(folder: CaptureFolder, user_id: str, image_id: int) -> Path:
    source_path = draft_image_path(folder.id, user_id, image_id)
    if source_path is not None:
        return source_path
    image = next((item for item in folder.images if item.id == image_id), None)
    if image is None:
        raise BusinessError(ApiCodes.NOT_FOUND, "图片不属于当前Folder", 404)
    return resolve_image_file(folder, image)


def ensure_editable_work_path(folder: CaptureFolder, user_id: str, image_id: int) -> tuple[Path, str]:
    manifest = read_manifest(folder.id, user_id)
    draft_item = draft_image_item(manifest, image_id)
    if image_id < 0:
        if not draft_item:
            raise BusinessError(ApiCodes.NOT_FOUND, "Draft图片不存在", 404)
        path = draft_image_path(folder.id, user_id, image_id)
        if path is None:
            raise BusinessError(ApiCodes.NOT_FOUND, "Draft图片文件不存在", 404)
        return path, draft_item.get("image_name") or path.name
    image = next((item for item in folder.images if item.id == image_id), None)
    if image is None:
        raise BusinessError(ApiCodes.NOT_FOUND, "图片不属于当前Folder", 404)
    source_path = resolve_image_file(folder, image)
    return ensure_work_copy(
        folder.id,
        user_id,
        image.id,
        image.image_name,
        source_path,
        official_ids=official_image_ids(folder),
    ), image.image_name


def validate_upload_filename(filename: str | None) -> str:
    """Extension gate for Replace/Insert. Content is checked separately."""
    name = safe_filename(filename or "")
    if Path(name).suffix.lower() not in UPLOAD_IMAGE_EXTENSIONS:
        allowed = "/".join(sorted(UPLOAD_IMAGE_EXTENSIONS))
        raise BusinessError(
            ApiCodes.BAD_REQUEST, f"Replace/Insert 只支持 {allowed} 文件", 400
        )
    return name


def replacement_image_name(existing_name: str, upload_name: str) -> str:
    """The name a replaced official image keeps.

    Page identity is the filename (see MODULE_1_QC_REWORK_DESIGN: "image_name =
    identity", and a recapture keeps the same one), so the stem is preserved and
    ordering with it. The extension follows the uploaded file, because keeping
    `.tif` on PNG bytes would leave a file whose name contradicts its content.
    """
    existing_suffix = Path(existing_name).suffix.lower()
    upload_suffix = Path(upload_name).suffix.lower()
    if existing_suffix == upload_suffix:
        return existing_name
    return f"{Path(existing_name).stem}{upload_suffix}"


def save_upload_to_temp(folder_id: int, user_id: str, file: UploadFile, filename: str) -> Path:
    upload_dir = draft_dir(folder_id, user_id) / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    target = (upload_dir / f"{int(now().timestamp() * 1000000)}_{safe_filename(filename)}").resolve()
    target.relative_to(draft_dir(folder_id, user_id).resolve())
    with target.open("wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    # The extension is caller-supplied, so it proves nothing about the bytes.
    # Every later step (rotate, crop, thumbnail, commit) assumes a real image,
    # so reject anything Pillow can't parse here rather than letting a corrupt
    # file reach the official folder.
    try:
        with Image.open(target) as probe:
            probe.verify()
    except Exception as error:
        target.unlink(missing_ok=True)
        raise BusinessError(ApiCodes.BAD_REQUEST, "上传的文件不是有效图片", 400) from error
    return target


def apply_rotate(path: Path, degrees: int) -> None:
    try:
        with Image.open(path) as src:
            frame = ImageOps.exif_transpose(src)
            original_format = src.format or path.suffix.lstrip(".").upper()
            save_format = "JPEG" if original_format == "JPG" else original_format
            rotated = frame.rotate(-degrees, expand=True)
            temp_path = path.with_name(f".{path.stem}.rotate_tmp{path.suffix}")
            save_kwargs: dict = {"format": save_format}
            if save_format == "JPEG":
                if rotated.mode not in {"RGB", "L"}:
                    rotated = rotated.convert("RGB")
                save_kwargs["quality"] = 95
            rotated.save(temp_path, **save_kwargs)
        os.replace(temp_path, path)
    except UnidentifiedImageError as error:
        raise BusinessError(ApiCodes.BAD_REQUEST, "不支持的图片格式", 400) from error


def deleted_root(folder_id: int, user_id: str) -> Path:
    path = draft_dir(folder_id, user_id).parent.parent / "qc_deleted" / str(folder_id) / str(int(now().timestamp() * 1000))
    path.mkdir(parents=True, exist_ok=True)
    return path


def child_group_id(parent_group_id: str | None, index: int) -> str | None:
    """The `group_id` for child folder [index] of a Separation split (1-based).

    `capture_folders.group_id` carries a UNIQUE constraint, so children cannot
    inherit the parent's value verbatim: the second child would collide, and the
    parent is only soft-deleted so its row still holds the original. Splitting it
    with the same `_001`/`_002` suffix `folder_name` already uses keeps the two
    columns in step.

    A parent with no group_id yields None for every child — PostgreSQL treats
    NULLs as distinct under a plain UNIQUE, so those never collide.
    """
    if parent_group_id is None or not parent_group_id.strip():
        return None
    return f"{parent_group_id}_{index:03d}"


def unique_official_name(folder: CaptureFolder, preferred_name: str, existing_names: set[str]) -> str:
    preferred = safe_filename(preferred_name)
    stem = Path(preferred).stem
    suffix = Path(preferred).suffix or ".tif"
    candidate = preferred
    index = 1
    official_dir = to_local(folder.folder_path or "").resolve()
    while candidate in existing_names or (official_dir / candidate).exists():
        candidate = f"{stem}_{index}{suffix}"
        index += 1
    existing_names.add(candidate)
    return candidate


def apply_separation_commit(
    db,
    folder: CaptureFolder,
    marker_ids: list[int],
    ordered_ids: list[int],
    commit_time: datetime,
) -> SeparationFileTransaction:
    marker_set = set(marker_ids)
    if len(marker_set) < 2:
        raise ValueError("Separation 至少需要两个起始页")
    if ordered_ids and ordered_ids[0] not in marker_set:
        raise ValueError("Separation 第一张图片必须标记为起始页")

    groups: list[list[int]] = []
    current_group: list[int] = []
    for image_id in ordered_ids:
        if image_id in marker_set and current_group:
            groups.append(current_group)
            current_group = []
        current_group.append(image_id)
    if current_group:
        groups.append(current_group)
    if len(groups) < 2:
        raise ValueError("Separation 至少需要两个子Folder")

    max_seq = db.scalar(select(func.max(CaptureFolder.folder_seq)).where(CaptureFolder.box_id == folder.box_id)) or 0
    image_lookup = {
        image.id: image
        for image in db.scalars(
            select(CaptureImage).where(
                CaptureImage.id.in_(ordered_ids),
                CaptureImage.folder_id == folder.id,
            )
        ).all()
    }
    if set(image_lookup) != set(ordered_ids):
        raise ValueError("Separation包含不属于当前Folder的图片")
    if not folder.folder_path:
        raise ValueError("Folder原图目录未配置")

    grouped_names = [
        [safe_filename(image_lookup[image_id].image_name) for image_id in group]
        for group in groups
    ]
    file_transaction = SeparationFileTransaction(
        to_local(folder.folder_path),
        to_local(folder.thumbnail_path) if folder.thumbnail_path else None,
        grouped_names,
    )
    file_transaction.apply()

    try:
        for index, group in enumerate(groups, start=1):
            file_group = file_transaction.groups[index - 1]
            child = CaptureFolder(
                group_id=child_group_id(folder.group_id, index),
                folder_name=f"{folder.folder_name}_{index:03d}",
                box_id=folder.box_id,
                device_id=folder.device_id,
                folder_seq=max_seq + index,
                cover_tag=folder.cover_tag,
                image_tags=folder.image_tags,
                title=folder.title,
                volume=folder.volume,
                start_date=folder.start_date,
                end_date=folder.end_date,
                archival_ref_no=folder.archival_ref_no,
                record_type=folder.record_type,
                place=folder.place,
                language=folder.language,
                record_custodian=folder.record_custodian,
                capture_operator_id=folder.capture_operator_id,
                capture_operator_name=folder.capture_operator_name,
                digitizing_entity=folder.digitizing_entity,
                source_created_at=commit_time,
                source_updated_at=commit_time,
                updated_at=commit_time,
                is_deleted=False,
                client_qc_status=folder.client_qc_status,
                client_rework=False,
                is_deskewed=folder.is_deskewed,
                is_cropped=folder.is_cropped,
                is_created_thumbnail=folder.is_created_thumbnail,
                # Written back in LWCAM's own path form — LWCAM and LWIP read these.
                folder_path=to_db(file_group.final_image_dir),
                thumbnail_path=(
                    to_db(file_group.final_thumbnail_dir)
                    if file_group.final_thumbnail_dir
                    else None
                ),
                qc_status="PENDING",
                is_tif_converted=folder.is_tif_converted,
            )
            db.add(child)
            db.flush()
            for image_id in group:
                image_lookup[image_id].folder_id = child.id

        folder.qc_status = "PASS"
        folder.qc_locked_by = None
        folder.qc_locked_at = None
        folder.is_deleted = True
        folder.deleted_at = commit_time
        folder.folder_path = None
        folder.thumbnail_path = None
        db.flush()
    except Exception:
        try:
            file_transaction.rollback()
        except SeparationFileError as rollback_error:
            raise SeparationFileError(
                f"数据库分离失败，且物理文件回滚失败: {rollback_error}"
            ) from rollback_error
        raise
    return file_transaction


def commit_current_draft(
    folder: CaptureFolder,
    user_id: str,
) -> SeparationFileTransaction | None:
    commit_time = now()
    db = object_session(folder)
    if db is None:
        raise ValueError("Folder is not attached to a database session")
    manifest = read_manifest(folder.id, user_id)
    if not manifest:
        return None
    images_by_id = {image.id: image for image in folder.images}
    template = metadata_template(folder)
    has_metadata_changes = metadata_dirty_from_manifest(manifest)
    committed: list[CaptureImage] = []
    id_map: dict[int, int] = {}
    folder_path = to_local(folder.folder_path or "").resolve()
    if not folder_path.is_dir():
        raise ValueError("Folder official image directory is missing")
    existing_names = {image.image_name for image in folder.images}
    thumbnail_dir = to_local(folder.thumbnail_path).resolve() if folder.thumbnail_path else None
    if thumbnail_dir:
        thumbnail_dir.mkdir(parents=True, exist_ok=True)

    for raw_id, item in list((manifest.get("images") or {}).items()):
        image_id = int(raw_id)
        status = item.get("status")
        if status == "deleted" and image_id > 0:
            image = images_by_id.get(image_id)
            if image is None:
                continue
            target_dir = deleted_root(folder.id, user_id)
            official_path = resolve_image_file(folder, image)
            shutil.move(str(official_path), str(target_dir / official_path.name))
            thumb = thumbnail_target_path(folder, image)
            if thumb and thumb.is_file():
                shutil.move(str(thumb), str(target_dir / thumb.name))
            db.delete(image)
            committed.append(image)
            continue
        if status == "inserted" and image_id < 0:
            work_path = Path(item["work_path"]).resolve()
            if not work_path.is_file():
                raise FileNotFoundError(f"Draft image missing: {work_path}")
            image_name = unique_official_name(folder, item.get("image_name") or work_path.name, existing_names)
            official_path = (folder_path / image_name).resolve()
            shutil.copy2(work_path, official_path)
            new_image = CaptureImage(
                image_name=image_name,
                device_id=folder.device_id,
                folder_id=folder.id,
                file_format=official_path.suffix.lstrip(".").lower() or "tif",
                image_created_at=commit_time,
                image_updated_at=commit_time,
            )
            db.add(new_image)
            db.flush()
            id_map[image_id] = new_image.id
            images_by_id[new_image.id] = new_image
            if thumbnail_dir:
                generate_thumbnail_file(official_path, thumbnail_dir / image_name)
            committed.append(new_image)
            continue
        if image_id > 0 and (item.get("dirty") or status == "replaced"):
            image = images_by_id.get(image_id)
            if image is None:
                raise ValueError(f"Draft image no longer belongs to folder: {image_id}")
            work_path = Path(item["work_path"]).resolve()
            official_path = resolve_image_file(folder, image)
            if not work_path.is_file():
                raise FileNotFoundError(f"Draft image missing: {work_path}")
            temp_path = official_path.with_name(f".{official_path.name}.draft_commit_tmp")
            shutil.copy2(work_path, temp_path)
            os.replace(temp_path, official_path)
            target_thumbnail = thumbnail_target_path(folder, image)
            if target_thumbnail is not None:
                temp_thumbnail = target_thumbnail.with_name(f".{target_thumbnail.name}.draft_commit_tmp")
                if generate_thumbnail_file(official_path, temp_thumbnail) is None:
                    temp_thumbnail.unlink(missing_ok=True)
                    raise ValueError(f"Thumbnail generation failed: {target_thumbnail}")
                os.replace(temp_thumbnail, target_thumbnail)
            image.image_updated_at = commit_time
            committed.append(image)

    if has_metadata_changes:
        apply_metadata_to_folder(folder, metadata_values_from_manifest(manifest), template)

    ordered_ids = [id_map.get(int(item), int(item)) for item in visible_order(manifest, official_image_ids(folder))]
    db.flush()
    latest_images = {image.id: image for image in images_by_id.values() if image.id in ordered_ids}
    for index, image_id in enumerate(ordered_ids):
        image = latest_images.get(image_id)
        if image:
            image.image_created_at = commit_time + timedelta(seconds=index)

    markers = [id_map.get(int(item), int(item)) for item in manifest.get("separation_markers", [])]
    separation_transaction = None
    if markers:
        if folder.qc_locked_by != user_id:
            raise ValueError("任务已不属于当前审核员")
        separation_transaction = apply_separation_commit(
            db,
            folder,
            markers,
            ordered_ids,
            commit_time,
        )

    if committed or has_metadata_changes or manifest.get("order") or markers:
        folder.is_created_thumbnail = True
        folder.source_updated_at = commit_time
        folder.updated_at = commit_time
    return separation_transaction


@router.get("", response_model=ApiResponse[PageResult[MetadataQcTaskVO]])
def list_tasks(
    current_user: QcUser,
    db: DbSession,
    scope: str = Query("pending", pattern="^(pending|mine|completed)$"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
) -> ApiResponse[PageResult[MetadataQcTaskVO]]:
    """按待领取、我的任务或已完成范围分页列出 QC 可见 Folder。"""
    project_ids = project_ids_for_user(db, current_user.id)
    if not project_ids:
        return ok(PageResult(records=[], total=0, page=page, size=size))

    statement = select(CaptureFolder).options(*folder_options()).where(*visible_folder_conditions(project_ids))

    if scope == "pending":
        statement = statement.where(
            func.lower(CaptureFolder.qc_status) == "pending",
            CaptureFolder.qc_locked_by.is_(None),
        )
        statement = statement.order_by(CaptureFolder.source_created_at.asc().nullslast(), CaptureFolder.id.asc())
    elif scope == "mine":
        statement = statement.where(
            func.lower(CaptureFolder.qc_status) == "pending",
            CaptureFolder.qc_locked_by == current_user.user_id,
        )
        statement = statement.order_by(CaptureFolder.qc_locked_at.desc().nullslast(), CaptureFolder.id.asc())
    else:  # completed
        statement = statement.where(
            func.lower(CaptureFolder.qc_status).in_(["pass", "rework"]),
        )
        statement = statement.order_by(CaptureFolder.updated_at.desc())

    total = db.scalar(select(func.count()).select_from(statement.order_by(None).subquery())) or 0
    folders = db.scalars(statement.offset((page - 1) * size).limit(size)).unique().all()

    return ok(PageResult(
        records=[to_task_vo(db, folder, current_user.user_id) for folder in folders],
        total=total,
        page=page,
        size=size,
    ))


@router.post("/claim-next", response_model=ApiResponse[MetadataQcTaskVO])
def claim_next(current_user: QcUser, db: DbSession) -> ApiResponse[MetadataQcTaskVO]:
    """在项目权限范围内原子领取最早可审核的 Folder。"""
    project_ids = project_ids_for_user(db, current_user.id)
    if not project_ids:
        raise BusinessError(ApiCodes.NOT_FOUND, "暂无可领取的QC任务", 404)

    # Check if user already has a claimed folder
    existing = db.scalar(
        select(CaptureFolder)
        .options(*folder_options())
        .where(
            *visible_folder_conditions(project_ids),
            func.lower(CaptureFolder.qc_status) == "pending",
            CaptureFolder.qc_locked_by == current_user.user_id,
        )
        .order_by(CaptureFolder.qc_locked_at.desc().nullslast())
        .limit(1)
    )
    if existing:
        db.commit()
        return ok(to_task_vo(db, existing, current_user.user_id))

    # Claim next available folder
    folder = db.scalar(
        select(CaptureFolder)
        .options(*folder_options())
        .where(
            *visible_folder_conditions(project_ids),
            func.lower(CaptureFolder.qc_status) == "pending",
            CaptureFolder.qc_locked_by.is_(None),
        )
        .order_by(CaptureFolder.source_created_at.asc().nullslast(), CaptureFolder.id.asc())
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if folder is None:
        db.commit()
        raise BusinessError(ApiCodes.NOT_FOUND, "暂无可领取的QC任务", 404)

    folder.qc_locked_by = current_user.user_id
    folder.qc_locked_at = now()
    db.commit()
    write_qc_audit("claim_next", current_user.user_id, folder.id, result="success")

    refreshed = folder_or_404(db, folder.id, current_user.id)
    return ok(to_task_vo(db, refreshed, current_user.user_id))


@router.get("/{folder_id}", response_model=ApiResponse[MetadataQcTaskVO])
def get_detail(folder_id: int, current_user: QcUser, db: DbSession) -> ApiResponse[MetadataQcTaskVO]:
    """返回 QC 有权限访问的 Folder 审核详情。"""
    folder = folder_or_404(db, folder_id, current_user.id)
    write_qc_audit("open", current_user.user_id, folder.id, result="success")
    return ok(to_task_vo(db, folder, current_user.user_id))


@router.post("/{folder_id}/claim", response_model=ApiResponse[MetadataQcTaskVO])
def claim_task(folder_id: int, current_user: QcUser, db: DbSession) -> ApiResponse[MetadataQcTaskVO]:
    """领取指定 Folder。"""
    project_ids = project_ids_for_user(db, current_user.id)
    if not project_ids:
        raise BusinessError(ApiCodes.NOT_FOUND, "暂无可领取的QC任务", 404)

    existing = db.scalar(
        select(CaptureFolder)
        .where(
            *visible_folder_conditions(project_ids),
            func.lower(CaptureFolder.qc_status) == "pending",
            CaptureFolder.qc_locked_by == current_user.user_id,
            CaptureFolder.id != folder_id,
        )
        .order_by(CaptureFolder.qc_locked_at.desc().nullslast(), CaptureFolder.id.asc())
        .limit(1)
    )
    if existing:
        raise BusinessError(ApiCodes.CONFLICT, "当前已有领取任务，请先完成当前任务", 409)

    folder = folder_or_404(db, folder_id, current_user.id, lock=True)

    # Already claimed by this user?
    if folder.qc_locked_by == current_user.user_id:
        db.commit()
        return ok(to_task_vo(db, folder, current_user.user_id))

    # Claimed by someone else?
    if folder.qc_locked_by is not None:
        db.rollback()
        raise BusinessError(ApiCodes.CONFLICT, "任务已被其他审核员领取", 409)

    # Wrong status?
    if folder.qc_status.lower() != "pending":
        db.rollback()
        raise BusinessError(ApiCodes.CONFLICT, "任务状态已变化，无法领取", 409)

    folder.qc_locked_by = current_user.user_id
    folder.qc_locked_at = now()
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise BusinessError(ApiCodes.CONFLICT, "当前已有领取任务，请先完成当前任务", 409) from error
    write_qc_audit("claim", current_user.user_id, folder.id, result="success")

    return ok(to_task_vo(db, folder_or_404(db, folder_id, current_user.id), current_user.user_id))


@router.post("/{folder_id}/release", response_model=ApiResponse[None])
def release_task(folder_id: int, current_user: QcUser, db: DbSession) -> ApiResponse[None]:
    """由 QC 主动释放已领取任务，使其重新回到待领取状态。"""
    folder = folder_or_404(db, folder_id, current_user.id, lock=True)
    assert_lock_owner(folder, current_user.user_id)

    manifest = read_manifest(folder.id, current_user.user_id)
    discard_draft(folder.id, current_user.user_id)
    folder.qc_locked_by = None
    folder.qc_locked_at = None
    db.commit()
    write_qc_audit(
        "release",
        current_user.user_id,
        folder.id,
        draft_summary=draft_summary(manifest),
        result="success",
    )
    return ok(None)


@router.post("/{folder_id}/approve", response_model=ApiResponse[None])
def approve_task(folder_id: int, request: ReviewRequest, current_user: QcUser, db: DbSession) -> ApiResponse[None]:
    """提交 Folder 整体通过审核结果。"""
    folder = folder_or_404(db, folder_id, current_user.id, lock=True)
    assert_lock_owner(folder, current_user.user_id)

    verify_reviewable_folder(folder, request.sourceHash)
    manifest = read_manifest(folder.id, current_user.user_id)
    template = metadata_template(folder)
    effective_metadata = effective_metadata_snapshot(folder, manifest, template)
    validate_metadata_for_approval(effective_metadata, template)

    # Verify all images exist
    if not folder.images:
        raise BusinessError(ApiCodes.BAD_REQUEST, "Folder没有图片，不能通过")
    for image in folder.images:
        resolve_image_file(folder, image)

    separation_transaction = None
    try:
        separation_transaction = commit_current_draft(folder, current_user.user_id)
        # Update status and release lock
        folder.qc_status = "PASS"
        folder.qc_locked_by = None
        folder.qc_locked_at = None
        db.commit()
    except Exception as error:
        db.rollback()
        if separation_transaction:
            try:
                separation_transaction.rollback()
            except Exception as rollback_error:
                logger.exception(
                    "QC separation rollback failed after approve commit error; folder=%s",
                    folder_id,
                )
                raise BusinessError(
                    ApiCodes.BAD_REQUEST,
                    f"Draft保存失败，且物理文件回滚失败: {rollback_error}",
                    400,
                ) from error
        if isinstance(error, SeparationFileError):
            raise BusinessError(ApiCodes.BAD_REQUEST, str(error), 400) from error
        raise BusinessError(ApiCodes.BAD_REQUEST, "Draft保存失败", 400) from error

    try:
        discard_draft(folder.id, current_user.user_id)
        if separation_transaction:
            separation_transaction.cleanup_empty_parent_directories()
    except Exception:
        logger.exception("QC draft cleanup failed after approve; folder=%s", folder_id)
    write_qc_audit(
        "approve",
        current_user.user_id,
        folder.id,
        source_hash=request.sourceHash,
        draft_summary=draft_summary(manifest),
        result="success",
        note=request.comment,
    )

    return ok(None)


@router.post("/{folder_id}/reject", response_model=ApiResponse[None])
def reject_task(folder_id: int, request: RejectRequest, current_user: QcUser, db: DbSession) -> ApiResponse[None]:
    """提交按图片返工的审核结果及返工原因。"""
    folder = folder_or_404(db, folder_id, current_user.id, lock=True)
    assert_lock_owner(folder, current_user.user_id)

    verify_reviewable_folder(folder, request.sourceHash)

    rejected_reason_by_id = {}
    if request.rejectedImages:
        for item in request.rejectedImages:
            reason = item.rejectReason.strip()
            if not reason:
                raise BusinessError(ApiCodes.BAD_REQUEST, "每张打回图片都必须填写打回原因")
            rejected_reason_by_id[item.imageId] = reason
    elif request.imageIds and request.rejectReason:
        legacy_reason = request.rejectReason.strip()
        rejected_reason_by_id = {image_id: legacy_reason for image_id in request.imageIds if legacy_reason}
    if not rejected_reason_by_id:
        raise BusinessError(ApiCodes.BAD_REQUEST, "至少选择一张需要返工的图片并填写对应打回原因")

    requested_ids = list(rejected_reason_by_id.keys())
    rejected_images = [image for image in folder.images if image.id in requested_ids]
    if len(rejected_images) != len(requested_ids):
        raise BusinessError(ApiCodes.BAD_REQUEST, "包含不属于当前Folder的图片")

    # Update folder status and reset processing flags (per design doc §6)
    manifest = read_manifest(folder.id, current_user.user_id)
    folder.qc_status = "REWORK"
    folder.qc_locked_by = None
    folder.qc_locked_at = None
    folder.is_deskewed = False
    folder.is_cropped = False
    folder.is_created_thumbnail = False
    discard_draft(folder.id, current_user.user_id)

    # Create rework logs for each rejected image
    for image in rejected_images:
        reason = rejected_reason_by_id[image.id]
        db.add(ReworkLog(
            image_id=image.id,
            assigned_uid=folder.box.user_id,
            folder_id=folder.id,
            created_at=now(),
            rework_comments=reason,
            rework_status="OPEN",
            rework_type="QC Rework",
        ))

    db.commit()
    write_qc_audit(
        "reject",
        current_user.user_id,
        folder.id,
        image_ids=[image.id for image in rejected_images],
        source_hash=request.sourceHash,
        draft_summary=draft_summary(manifest),
        result="success",
        note="; ".join(f"{image.image_name}: {rejected_reason_by_id[image.id]}" for image in rejected_images),
    )
    return ok(None)


@router.put("/{folder_id}/metadata", response_model=ApiResponse[MetadataQcTaskVO])
def update_metadata(
    folder_id: int,
    request: MetadataUpdateRequest,
    current_user: QcUser,
    db: DbSession,
) -> ApiResponse[MetadataQcTaskVO]:
    """在审核过程中修改 Folder 元数据。"""
    folder = folder_or_404(db, folder_id, current_user.id, lock=True)
    assert_lock_owner(folder, current_user.user_id)

    current_hash = source_hash(folder)
    if request.sourceHash != current_hash:
        raise BusinessError(ApiCodes.CONFLICT, "Folder已更新，请刷新后重新审核", 409)

    if folder.qc_status.lower() != "pending":
        raise BusinessError(ApiCodes.CONFLICT, "任务状态已变化", 409)

    template = metadata_template(folder)
    values = normalize_metadata_values(editable_metadata_to_dict(request.metadata), template)
    validate_date_order(values)

    save_metadata_draft(folder.id, current_user.user_id, values)
    write_qc_audit(
        "metadata_draft",
        current_user.user_id,
        folder.id,
        source_hash=request.sourceHash,
        draft_summary=draft_summary(read_manifest(folder.id, current_user.user_id)),
        result="success",
    )
    db.commit()

    return ok(to_task_vo(db, folder, current_user.user_id))


@router.post("/{folder_id}/images/{image_id}/crop", response_model=ApiResponse[MetadataQcTaskVO])
def crop_image(
    folder_id: int,
    image_id: int,
    request: CropImageRequest,
    current_user: QcUser,
    db: DbSession,
) -> ApiResponse[MetadataQcTaskVO]:
    """裁剪指定图片（原子替换，原文件备份到 old/ 目录）。"""
    folder = folder_or_404(db, folder_id, current_user.id, lock=True)
    assert_lock_owner(folder, current_user.user_id)

    current_hash = source_hash(folder)
    if request.sourceHash != current_hash:
        raise BusinessError(ApiCodes.CONFLICT, "Folder已更新，请刷新后重新审核", 409)
    if folder.qc_status.lower() != "pending":
        raise BusinessError(ApiCodes.CONFLICT, "任务状态已变化", 409)

    work_path, image_name = ensure_editable_work_path(folder, current_user.user_id, image_id)
    mark_dirty(folder.id, current_user.user_id, image_id, "crop")
    try:
        with Image.open(work_path) as src:
            frame = ImageOps.exif_transpose(src)
            original_format = src.format
            scale_x = frame.width / request.previewWidth if request.previewWidth else 1
            scale_y = frame.height / request.previewHeight if request.previewHeight else 1
            crop_x = max(0, min(frame.width - 1, round(request.x * scale_x)))
            crop_y = max(0, min(frame.height - 1, round(request.y * scale_y)))
            right = max(crop_x + 1, min(frame.width, round((request.x + request.width) * scale_x)))
            bottom = max(crop_y + 1, min(frame.height, round((request.y + request.height) * scale_y)))
            if crop_x >= frame.width or crop_y >= frame.height or right > frame.width or bottom > frame.height:
                raise BusinessError(ApiCodes.BAD_REQUEST, "裁剪区域超出图片范围")
            cropped = frame.crop((crop_x, crop_y, right, bottom))
            save_format = original_format or Path(image_name).suffix.lstrip(".").upper()
            if save_format == "JPG":
                save_format = "JPEG"
            temp_path = work_path.with_name(f".{work_path.stem}.crop_tmp{work_path.suffix}")
            save_kwargs: dict = {"format": save_format}
            if save_format == "JPEG":
                if cropped.mode not in {"RGB", "L"}:
                    cropped = cropped.convert("RGB")
                save_kwargs["quality"] = 95
            cropped.save(temp_path, **save_kwargs)
    except BusinessError:
        raise
    except UnidentifiedImageError as error:
        raise BusinessError(ApiCodes.BAD_REQUEST, "不支持的图片格式", 400) from error
    except Exception as error:
        raise BusinessError(ApiCodes.BAD_REQUEST, "图片裁剪失败", 400) from error

    try:
        temp_path.replace(work_path)
    except Exception as error:
        if temp_path.is_file():
            temp_path.unlink(missing_ok=True)
        raise BusinessError(ApiCodes.BAD_REQUEST, "Draft图片替换失败", 400) from error

    write_qc_audit(
        "crop_draft",
        current_user.user_id,
        folder.id,
        image_ids=[image_id],
        source_hash=request.sourceHash,
        draft_summary=draft_summary(read_manifest(folder.id, current_user.user_id)),
        result="success",
    )
    db.commit()

    return ok(to_task_vo(db, folder, current_user.user_id))


@router.post("/{folder_id}/images/{image_id}/luminance", response_model=ApiResponse[MetadataQcTaskVO])
def luminance_image(
    folder_id: int,
    image_id: int,
    request: LuminanceRequest,
    current_user: QcUser,
    db: DbSession,
) -> ApiResponse[MetadataQcTaskVO]:
    """Apply luminance correction to a draft copy of one image."""
    folder = folder_or_404(db, folder_id, current_user.id, lock=True)
    assert_lock_owner(folder, current_user.user_id)
    verify_reviewable_folder(folder, request.sourceHash)

    work_path, _image_name = ensure_editable_work_path(folder, current_user.user_id, image_id)
    mark_dirty(folder.id, current_user.user_id, image_id, "luminance")
    try:
        apply_luminance(work_path)
    except Exception as error:
        raise BusinessError(ApiCodes.BAD_REQUEST, "Luminance处理失败", 400) from error
    write_qc_audit(
        "luminance",
        current_user.user_id,
        folder.id,
        image_ids=[image_id],
        source_hash=request.sourceHash,
        draft_summary=draft_summary(read_manifest(folder.id, current_user.user_id)),
        result="success",
    )
    db.commit()

    refreshed = folder_or_404(db, folder_id, current_user.id)
    return ok(to_task_vo(db, refreshed, current_user.user_id))


@router.post("/{folder_id}/images/luminance-batch", response_model=ApiResponse[MetadataQcTaskVO])
def luminance_batch(
    folder_id: int,
    request: BatchLuminanceRequest,
    current_user: QcUser,
    db: DbSession,
) -> ApiResponse[MetadataQcTaskVO]:
    """Apply luminance correction to draft copies of selected images."""
    folder = folder_or_404(db, folder_id, current_user.id, lock=True)
    assert_lock_owner(folder, current_user.user_id)
    verify_reviewable_folder(folder, request.sourceHash)

    requested_ids = list(dict.fromkeys(request.imageIds))
    for image_id in requested_ids:
        work_path, image_name = ensure_editable_work_path(folder, current_user.user_id, image_id)
        mark_dirty(folder.id, current_user.user_id, image_id, "luminance")
        try:
            apply_luminance(work_path)
        except Exception as error:
            raise BusinessError(ApiCodes.BAD_REQUEST, f"Luminance处理失败: {image_name}", 400) from error

    write_qc_audit(
        "luminance_batch",
        current_user.user_id,
        folder.id,
        image_ids=requested_ids,
        source_hash=request.sourceHash,
        draft_summary=draft_summary(read_manifest(folder.id, current_user.user_id)),
        result="success",
    )
    db.commit()

    refreshed = folder_or_404(db, folder_id, current_user.id)
    return ok(to_task_vo(db, refreshed, current_user.user_id))


@router.post("/{folder_id}/images/{image_id}/replace", response_model=ApiResponse[MetadataQcTaskVO])
def replace_image(
    folder_id: int,
    image_id: int,
    current_user: QcUser,
    db: DbSession,
    sourceHash: str = Form(...),
    file: UploadFile = File(...),
) -> ApiResponse[MetadataQcTaskVO]:
    folder = folder_or_404(db, folder_id, current_user.id, lock=True)
    assert_lock_owner(folder, current_user.user_id)
    verify_reviewable_folder(folder, sourceHash)
    filename = validate_upload_filename(file.filename)
    temp_path = save_upload_to_temp(folder.id, current_user.user_id, file, filename)
    if image_id > 0:
        image = next((item for item in folder.images if item.id == image_id), None)
        if image is None:
            raise BusinessError(ApiCodes.NOT_FOUND, "图片不属于当前Folder", 404)
        image_name = replacement_image_name(image.image_name, filename)
    else:
        item = draft_image_item(read_manifest(folder.id, current_user.user_id), image_id)
        if not item:
            raise BusinessError(ApiCodes.NOT_FOUND, "Draft图片不存在", 404)
        image_name = filename
    draft_replace_image(folder.id, current_user.user_id, image_id, image_name, temp_path, official_image_ids(folder))
    db.commit()
    write_qc_audit("replace", current_user.user_id, folder.id, image_ids=[image_id], source_hash=sourceHash, result="success")
    return ok(to_task_vo(db, folder_or_404(db, folder_id, current_user.id), current_user.user_id))


@router.post("/{folder_id}/images/{image_id}/insert-before", response_model=ApiResponse[MetadataQcTaskVO])
def insert_image_before(
    folder_id: int,
    image_id: int,
    current_user: QcUser,
    db: DbSession,
    sourceHash: str = Form(...),
    file: UploadFile = File(...),
) -> ApiResponse[MetadataQcTaskVO]:
    folder = folder_or_404(db, folder_id, current_user.id, lock=True)
    assert_lock_owner(folder, current_user.user_id)
    verify_reviewable_folder(folder, sourceHash)
    filename = validate_upload_filename(file.filename)
    if image_id not in visible_order(read_manifest(folder.id, current_user.user_id), official_image_ids(folder)):
        raise BusinessError(ApiCodes.NOT_FOUND, "插入位置图片不存在", 404)
    temp_path = save_upload_to_temp(folder.id, current_user.user_id, file, filename)
    temp_id = create_inserted_image(folder.id, current_user.user_id, filename, temp_path, image_id, official_image_ids(folder))
    db.commit()
    write_qc_audit("insert_before", current_user.user_id, folder.id, image_ids=[temp_id], source_hash=sourceHash, result="success")
    return ok(to_task_vo(db, folder_or_404(db, folder_id, current_user.id), current_user.user_id))


@router.post("/{folder_id}/images/{image_id}/delete", response_model=ApiResponse[MetadataQcTaskVO])
def delete_qc_image(
    folder_id: int,
    image_id: int,
    request: ReviewRequest,
    current_user: QcUser,
    db: DbSession,
) -> ApiResponse[MetadataQcTaskVO]:
    folder = folder_or_404(db, folder_id, current_user.id, lock=True)
    assert_lock_owner(folder, current_user.user_id)
    verify_reviewable_folder(folder, request.sourceHash)
    manifest = read_manifest(folder.id, current_user.user_id)
    current_order = visible_order(manifest, official_image_ids(folder))
    if image_id not in current_order:
        raise BusinessError(ApiCodes.NOT_FOUND, "图片不存在", 404)
    if len(current_order) <= 1:
        raise BusinessError(ApiCodes.BAD_REQUEST, "不能删除最后一张图片", 400)
    draft_delete_image(folder.id, current_user.user_id, image_id, official_image_ids(folder))
    db.commit()
    write_qc_audit("delete", current_user.user_id, folder.id, image_ids=[image_id], source_hash=request.sourceHash, result="success")
    return ok(to_task_vo(db, folder_or_404(db, folder_id, current_user.id), current_user.user_id))


@router.post("/{folder_id}/images/{image_id}/rotate", response_model=ApiResponse[MetadataQcTaskVO])
def rotate_qc_image(
    folder_id: int,
    image_id: int,
    request: RotateImageRequest,
    current_user: QcUser,
    db: DbSession,
) -> ApiResponse[MetadataQcTaskVO]:
    folder = folder_or_404(db, folder_id, current_user.id, lock=True)
    assert_lock_owner(folder, current_user.user_id)
    verify_reviewable_folder(folder, request.sourceHash)
    if request.degrees not in {-90, 90, 180}:
        raise BusinessError(ApiCodes.BAD_REQUEST, "旋转角度只允许 90/-90/180", 400)
    work_path, _image_name = ensure_editable_work_path(folder, current_user.user_id, image_id)
    mark_dirty(folder.id, current_user.user_id, image_id, f"rotate_{request.degrees}")
    apply_rotate(work_path, request.degrees)
    db.commit()
    write_qc_audit("rotate", current_user.user_id, folder.id, image_ids=[image_id], source_hash=request.sourceHash, result="success")
    return ok(to_task_vo(db, folder_or_404(db, folder_id, current_user.id), current_user.user_id))


@router.post("/{folder_id}/images/rotate-batch", response_model=ApiResponse[MetadataQcTaskVO])
def rotate_qc_batch(
    folder_id: int,
    request: BatchRotateRequest,
    current_user: QcUser,
    db: DbSession,
) -> ApiResponse[MetadataQcTaskVO]:
    folder = folder_or_404(db, folder_id, current_user.id, lock=True)
    assert_lock_owner(folder, current_user.user_id)
    verify_reviewable_folder(folder, request.sourceHash)
    if request.degrees not in {-90, 90, 180}:
        raise BusinessError(ApiCodes.BAD_REQUEST, "旋转角度只允许 90/-90/180", 400)
    requested_ids = list(dict.fromkeys(request.imageIds))
    for image_id in requested_ids:
        work_path, _image_name = ensure_editable_work_path(folder, current_user.user_id, image_id)
        mark_dirty(folder.id, current_user.user_id, image_id, f"rotate_{request.degrees}")
        apply_rotate(work_path, request.degrees)
    db.commit()
    write_qc_audit("rotate_batch", current_user.user_id, folder.id, image_ids=requested_ids, source_hash=request.sourceHash, result="success")
    return ok(to_task_vo(db, folder_or_404(db, folder_id, current_user.id), current_user.user_id))


@router.post("/{folder_id}/images/{image_id}/deskew", response_model=ApiResponse[MetadataQcTaskVO])
def deskew_qc_image(
    folder_id: int,
    image_id: int,
    request: DeskewImageRequest,
    current_user: QcUser,
    db: DbSession,
) -> ApiResponse[MetadataQcTaskVO]:
    folder = folder_or_404(db, folder_id, current_user.id, lock=True)
    assert_lock_owner(folder, current_user.user_id)
    verify_reviewable_folder(folder, request.sourceHash)
    if request.degrees not in {-1, 1}:
        raise BusinessError(ApiCodes.BAD_REQUEST, "纠偏只允许 -1 或 1 度", 400)
    work_path, _image_name = ensure_editable_work_path(folder, current_user.user_id, image_id)
    mark_dirty(folder.id, current_user.user_id, image_id, f"deskew_{request.degrees}")
    apply_rotate(work_path, request.degrees)
    db.commit()
    write_qc_audit("deskew", current_user.user_id, folder.id, image_ids=[image_id], source_hash=request.sourceHash, result="success")
    return ok(to_task_vo(db, folder_or_404(db, folder_id, current_user.id), current_user.user_id))


@router.post("/{folder_id}/images/reorder", response_model=ApiResponse[MetadataQcTaskVO])
def reorder_qc_images(
    folder_id: int,
    request: ReorderImagesRequest,
    current_user: QcUser,
    db: DbSession,
) -> ApiResponse[MetadataQcTaskVO]:
    folder = folder_or_404(db, folder_id, current_user.id, lock=True)
    assert_lock_owner(folder, current_user.user_id)
    verify_reviewable_folder(folder, request.sourceHash)
    current_ids = visible_order(read_manifest(folder.id, current_user.user_id), official_image_ids(folder))
    if set(request.imageIds) != set(current_ids) or len(request.imageIds) != len(current_ids):
        raise BusinessError(ApiCodes.BAD_REQUEST, "排序列表必须完整匹配当前图片", 400)
    set_order(folder.id, current_user.user_id, request.imageIds, official_image_ids(folder))
    db.commit()
    write_qc_audit("reorder", current_user.user_id, folder.id, image_ids=request.imageIds, source_hash=request.sourceHash, result="success")
    return ok(to_task_vo(db, folder_or_404(db, folder_id, current_user.id), current_user.user_id))


@router.post("/{folder_id}/images/{image_id}/restore-original", response_model=ApiResponse[MetadataQcTaskVO])
def restore_qc_image(
    folder_id: int,
    image_id: int,
    request: ReviewRequest,
    current_user: QcUser,
    db: DbSession,
) -> ApiResponse[MetadataQcTaskVO]:
    folder = folder_or_404(db, folder_id, current_user.id, lock=True)
    assert_lock_owner(folder, current_user.user_id)
    verify_reviewable_folder(folder, request.sourceHash)
    draft_restore_original(folder.id, current_user.user_id, image_id, official_image_ids(folder))
    db.commit()
    write_qc_audit("restore_original", current_user.user_id, folder.id, image_ids=[image_id], source_hash=request.sourceHash, result="success")
    return ok(to_task_vo(db, folder_or_404(db, folder_id, current_user.id), current_user.user_id))


@router.post("/{folder_id}/draft/undo", response_model=ApiResponse[MetadataQcTaskVO])
def undo_qc_draft(folder_id: int, current_user: QcUser, db: DbSession) -> ApiResponse[MetadataQcTaskVO]:
    folder = folder_or_404(db, folder_id, current_user.id, lock=True)
    assert_lock_owner(folder, current_user.user_id)
    undo_manifest(folder.id, current_user.user_id)
    db.commit()
    write_qc_audit("undo", current_user.user_id, folder.id, result="success")
    return ok(to_task_vo(db, folder_or_404(db, folder_id, current_user.id), current_user.user_id))


@router.post("/{folder_id}/draft/redo", response_model=ApiResponse[MetadataQcTaskVO])
def redo_qc_draft(folder_id: int, current_user: QcUser, db: DbSession) -> ApiResponse[MetadataQcTaskVO]:
    folder = folder_or_404(db, folder_id, current_user.id, lock=True)
    assert_lock_owner(folder, current_user.user_id)
    redo_manifest(folder.id, current_user.user_id)
    db.commit()
    write_qc_audit("redo", current_user.user_id, folder.id, result="success")
    return ok(to_task_vo(db, folder_or_404(db, folder_id, current_user.id), current_user.user_id))


@router.put("/{folder_id}/separation-markers", response_model=ApiResponse[MetadataQcTaskVO])
def update_separation_markers(
    folder_id: int,
    request: SeparationMarkersRequest,
    current_user: QcUser,
    db: DbSession,
) -> ApiResponse[MetadataQcTaskVO]:
    folder = folder_or_404(db, folder_id, current_user.id, lock=True)
    assert_lock_owner(folder, current_user.user_id)
    verify_reviewable_folder(folder, request.sourceHash)
    current_ids = visible_order(read_manifest(folder.id, current_user.user_id), official_image_ids(folder))
    marker_ids = list(dict.fromkeys(request.firstPageImageIds))
    if any(image_id not in current_ids for image_id in marker_ids):
        raise BusinessError(ApiCodes.BAD_REQUEST, "分离起始页不属于当前图片", 400)
    if marker_ids and (len(marker_ids) < 2 or current_ids[0] not in marker_ids):
        raise BusinessError(ApiCodes.BAD_REQUEST, "分离至少需要两个起始页，且第一张必须标记", 400)
    set_separation_markers(folder.id, current_user.user_id, marker_ids, official_image_ids(folder))
    db.commit()
    write_qc_audit("separation_markers", current_user.user_id, folder.id, image_ids=marker_ids, source_hash=request.sourceHash, result="success")
    return ok(to_task_vo(db, folder_or_404(db, folder_id, current_user.id), current_user.user_id))


@router.post("/{folder_id}/draft/save", response_model=ApiResponse[MetadataQcTaskVO])
def save_draft(
    folder_id: int,
    request: ReviewRequest,
    current_user: QcUser,
    db: DbSession,
) -> ApiResponse[MetadataQcTaskVO]:
    """Commit current user's QC draft image changes to official images."""
    folder = folder_or_404(db, folder_id, current_user.id, lock=True)
    assert_lock_owner(folder, current_user.user_id)
    verify_reviewable_folder(folder, request.sourceHash)
    manifest = read_manifest(folder.id, current_user.user_id)
    metadata_values = normalize_metadata_values(
        metadata_values_from_manifest(manifest),
        metadata_template(folder),
    )
    validate_date_order(metadata_values)
    has_separation = bool((manifest or {}).get("separation_markers"))
    parent_folder_name = folder.folder_name

    def response_folder_after_save() -> CaptureFolder:
        if not has_separation:
            return folder
        child = db.scalar(
            select(CaptureFolder)
            .options(*folder_options())
            .where(
                CaptureFolder.box_id == folder.box_id,
                CaptureFolder.folder_name.like(f"{parent_folder_name}_%"),
                func.lower(CaptureFolder.qc_status) == "pending",
            )
            .order_by(CaptureFolder.folder_seq.asc(), CaptureFolder.id.asc())
            .limit(1)
        )
        if child is None:
            return folder
        if child.qc_locked_by is None:
            child.qc_locked_by = current_user.user_id
            child.qc_locked_at = now()
            db.commit()
        return child

    separation_transaction = None
    try:
        separation_transaction = commit_current_draft(folder, current_user.user_id)
        db.commit()
    except Exception as error:
        db.rollback()
        if separation_transaction:
            try:
                separation_transaction.rollback()
            except Exception as rollback_error:
                logger.exception(
                    "QC separation rollback failed after save commit error; folder=%s",
                    folder_id,
                )
                raise BusinessError(
                    ApiCodes.BAD_REQUEST,
                    f"Draft保存失败，且物理文件回滚失败: {rollback_error}",
                    400,
                ) from error
        if isinstance(error, SeparationFileError):
            raise BusinessError(ApiCodes.BAD_REQUEST, str(error), 400) from error
        raise BusinessError(ApiCodes.BAD_REQUEST, "Draft保存失败", 400) from error

    # The session keeps in-memory values after commit (expire_on_commit=False),
    # but sourceHash is built from timestamp isoformat() strings — and the
    # in-memory representation differs from what PostgreSQL hands back on the
    # next request: TIMESTAMPTZ(3) rounds our microsecond datetimes to
    # milliseconds, and reads come back in the connection's timezone, not UTC.
    # Hashing the in-memory values therefore returned a sourceHash no later
    # request could ever match (409 "Folder已更新" on the very next action).
    # Expiring forces the VO below to rebuild from persisted values — exactly
    # the representation every subsequent request will compute against.
    db.expire_all()

    try:
        discard_draft(folder.id, current_user.user_id)
        if separation_transaction:
            separation_transaction.cleanup_empty_parent_directories()
    except Exception:
        logger.exception("QC draft cleanup failed after save; folder=%s", folder_id)
    write_qc_audit(
        "save",
        current_user.user_id,
        folder.id,
        source_hash=request.sourceHash,
        draft_summary=draft_summary(manifest),
        result="success",
        note=request.comment,
    )

    return ok(to_task_vo(db, response_folder_after_save(), current_user.user_id))


@router.post("/{folder_id}/draft/discard", response_model=ApiResponse[MetadataQcTaskVO])
def discard_current_draft(
    folder_id: int,
    current_user: QcUser,
    db: DbSession,
) -> ApiResponse[MetadataQcTaskVO]:
    """Discard current user's QC draft image changes."""
    folder = folder_or_404(db, folder_id, current_user.id, lock=True)
    assert_lock_owner(folder, current_user.user_id)
    manifest = read_manifest(folder.id, current_user.user_id)
    discard_draft(folder.id, current_user.user_id)
    db.commit()
    write_qc_audit(
        "discard",
        current_user.user_id,
        folder.id,
        draft_summary=draft_summary(manifest),
        result="success",
    )

    refreshed = folder_or_404(db, folder_id, current_user.id)
    return ok(to_task_vo(db, refreshed, current_user.user_id))


@router.get("/{folder_id}/images/{image_id}/preview")
def preview(folder_id: int, image_id: int, current_user: QcUser, db: DbSession) -> FileResponse:
    """校验 QC 权限后返回指定图片的预览文件。"""
    folder = folder_or_404(db, folder_id, current_user.id)
    source_path = None
    if folder.qc_locked_by == current_user.user_id:
        source_path = draft_image_path(folder.id, current_user.user_id, image_id)
    if source_path is None:
        image = next((item for item in folder.images if item.id == image_id), None)
        if image is None:
            raise BusinessError(ApiCodes.NOT_FOUND, "图片不属于当前Folder", 404)
        try:
            source_path = resolve_image_file(folder, image, thumbnail=True)
        except BusinessError:
            source_path = resolve_image_file(folder, image)
    try:
        preview_path = generate_preview_image(source_path)
    except Exception as error:
        raise BusinessError(ApiCodes.BAD_REQUEST, "图片预览生成失败", 400) from error
    if preview_path is None:
        raise BusinessError(ApiCodes.BAD_REQUEST, "不支持的图片格式", 400)
    return FileResponse(
        preview_path,
        media_type=PREVIEW_MIME_TYPE,
        filename=f"{source_path.stem}.jpg",
        content_disposition_type="inline",
    )
