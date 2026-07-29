from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import shutil
import threading
import uuid
import zipfile
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from PIL import Image
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, joinedload, lazyload, selectinload

from app.core.config import settings
from app.db.session import SessionLocal, engine
from app.models.capture import CaptureBox, CaptureFolder, CaptureImage
from app.models.project import Project

GROUP_CSV_HEADERS = [
    "Rework",
    "Title",
    "Place",
    "Start Date",
    "End Date",
    "Record Type",
    "Language",
    "Record Custodian",
    "Archival Reference Number",
    "Capture ID",
    "Capture Operator Name",
    "Capture Operator ID",
    "Total Artifacts",
    "Volume",
    "Capture Date",
    "Digitizing Entity",
]

ARTIFACT_CSV_HEADERS = [
    "Filename",
    "File Size",
    "Artifact Type",
    "Hash Algorithm",
    "Hash",
    "Image Width",
    "Image Height",
    "Capture ID",
]

SOURCE_NAME_PATTERN = re.compile(
    r"^(?P<user>[A-Za-z0-9_-]+)_IMG_(?P<date>\d{8})_(?P<time>\d{6})"
    r"(?:_\d{3})?\.[^.]+$",
    re.IGNORECASE,
)
SAFE_GROUP_PART = re.compile(r"^[A-Za-z0-9_-]+$")
DEFLATE_COMPRESSION_TAGS = {8, 32946}


class ExportError(RuntimeError):
    pass


@dataclass(frozen=True)
class ExportRuntimeConfig:
    temp_dir: Path
    output_dir: Path
    encoding: str
    line_ending_name: str
    line_ending: str

    def to_json(self) -> dict[str, Any]:
        return {
            "tempDir": str(self.temp_dir),
            "outputDir": str(self.output_dir),
            "csvEncoding": self.encoding,
            "csvLineEnding": self.line_ending_name,
        }


@dataclass(frozen=True)
class ImageSource:
    id: int
    name: str
    path: Path
    size: int
    mtime_ns: int


@dataclass(frozen=True)
class FolderExportSnapshot:
    folder_id: int
    project_id: int
    ingest_project_id: str
    location_code: str
    metadata: dict[str, Any]
    images: list[ImageSource]
    source_user_id: str
    source_date: date


@dataclass(frozen=True)
class ExportedZip:
    path: Path
    size: int
    sha256: str


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def runtime_config() -> ExportRuntimeConfig:
    errors: list[str] = []
    temp_value = settings.export_temp_dir.strip()
    output_value = settings.export_output_dir.strip()
    encoding_value = settings.export_csv_encoding.strip().lower()
    line_ending_value = settings.export_csv_line_ending.strip().upper()
    if not temp_value:
        errors.append("EXPORT_TEMP_DIR 未配置")
    if not output_value:
        errors.append("EXPORT_OUTPUT_DIR 未配置")
    if encoding_value not in {"utf-8", "utf-8-sig"}:
        errors.append("EXPORT_CSV_ENCODING 必须是 utf-8 或 utf-8-sig")
    if line_ending_value not in {"LF", "CRLF"}:
        errors.append("EXPORT_CSV_LINE_ENDING 必须是 LF 或 CRLF")
    if errors:
        raise ExportError("；".join(errors))
    return ExportRuntimeConfig(
        temp_dir=Path(temp_value).expanduser(),
        output_dir=Path(output_value).expanduser(),
        encoding=encoding_value,
        line_ending_name=line_ending_value,
        line_ending="\n" if line_ending_value == "LF" else "\r\n",
    )


def validate_runtime_paths(config: ExportRuntimeConfig) -> None:
    for label, directory in (
        ("EXPORT_TEMP_DIR", config.temp_dir),
        ("EXPORT_OUTPUT_DIR", config.output_dir),
    ):
        probe = directory / f".lwcam-write-test-{uuid.uuid4().hex}"
        try:
            directory.mkdir(parents=True, exist_ok=True)
            probe.write_bytes(b"ok")
        except OSError as error:
            raise ExportError(f"{label} 不可写: {directory}") from error
        finally:
            try:
                probe.unlink(missing_ok=True)
            except OSError:
                pass


def project_ingest_id(project: Project) -> str:
    value = str(project.project_id or "").strip()
    if not value:
        raise ExportError(f"项目 {project.project_name} 未配置 projects.project_id")
    validate_group_part("ProjectID", value)
    return value


def fixed_template_value(project: Project, key: str) -> str:
    template = project.template if isinstance(project.template, dict) else {}
    fields = template.get("fields") if isinstance(template.get("fields"), list) else []
    for item in fields:
        if isinstance(item, dict) and item.get("key") == key:
            return str(item.get("value") or "").strip()
    return ""


def mapped_record_type(project: Project, title: str) -> str:
    template = project.template if isinstance(project.template, dict) else {}
    mapping = (
        template.get("titleRecordTypeMap")
        if isinstance(template.get("titleRecordTypeMap"), dict)
        else {}
    )
    return str(mapping.get(title) or "").strip()


def validate_group_part(label: str, value: str) -> None:
    if not value or not SAFE_GROUP_PART.fullmatch(value):
        raise ExportError(f"{label} 只能包含字母、数字、下划线和连字符")


def parse_source_identity(filename: str) -> tuple[str, date]:
    match = SOURCE_NAME_PATTERN.fullmatch(filename)
    if match is None:
        raise ExportError(
            f"首张图片文件名不符合 <UserID>_IMG_YYYYMMDD_HHMMSS_NNN.ext: {filename}"
        )
    user_id = match.group("user")
    try:
        source_date = datetime.strptime(match.group("date"), "%Y%m%d").date()
    except ValueError as error:
        raise ExportError(f"首张图片日期无效: {filename}") from error
    return user_id, source_date


def format_date(value: Any) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text_value = str(value).strip()
    if not text_value:
        return ""
    try:
        return datetime.fromisoformat(text_value.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return text_value


def allocate_sequence(db: Session, project_id: int) -> int:
    if project_id <= 0:
        raise ExportError("项目 ID 无效")
    sequence_name = f"lwcam_export_project_{project_id}_seq"
    db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:resource, 0))"),
        {"resource": f"lwcam-export-sequence:{project_id}"},
    )
    db.execute(
        text(
            f"CREATE SEQUENCE IF NOT EXISTS public.{sequence_name} "
            "AS BIGINT START WITH 1 INCREMENT BY 1 MAXVALUE 999999 NO CYCLE"
        )
    )
    value = int(
        db.scalar(text(f"SELECT nextval('public.{sequence_name}'::regclass)")) or 0
    )
    if value < 1 or value > 999999:
        raise ExportError(f"项目 {project_id} 的导出序列已耗尽")
    return value


def build_group_id(snapshot: FolderExportSnapshot, sequence: int) -> str:
    validate_group_part("LocationCode", snapshot.location_code)
    validate_group_part("UserID", snapshot.source_user_id)
    group_id = (
        f"{snapshot.ingest_project_id}{snapshot.location_code}{snapshot.source_user_id}"
        f"{snapshot.source_date.strftime('%y%m%d')}{sequence:06d}"
    )
    if len(group_id) > 255:
        raise ExportError("Group ID 超过 255 个字符")
    return group_id


def ordered_images(folder: CaptureFolder) -> list[CaptureImage]:
    minimum = datetime.min.replace(tzinfo=timezone.utc)
    return sorted(folder.images, key=lambda item: (item.image_created_at or minimum, item.id))


def load_folder_snapshot(db: Session, folder_id: int) -> FolderExportSnapshot:
    folder = db.scalar(
        select(CaptureFolder)
        .options(
            selectinload(CaptureFolder.images),
            joinedload(CaptureFolder.box).joinedload(CaptureBox.project),
        )
        .where(CaptureFolder.id == folder_id)
    )
    if folder is None or folder.is_deleted:
        raise ExportError("Folder 不存在或已删除")
    if folder.qc_status.lower() != "pass":
        raise ExportError("Folder 尚未通过 QC")
    if folder.is_exported:
        raise ExportError("Folder 已导出")
    if not folder.folder_path:
        raise ExportError("Folder 原图目录未配置")
    project = folder.box.project
    if project is None or project.is_deleted:
        raise ExportError("Folder 所属项目不存在或已删除")
    image_dir = Path(folder.folder_path).expanduser().resolve()
    if not image_dir.is_dir():
        raise ExportError(f"Folder 原图目录不存在: {image_dir}")
    image_sources: list[ImageSource] = []
    for image in ordered_images(folder):
        if Path(image.image_name).name != image.image_name:
            raise ExportError(f"图片文件名无效: {image.image_name}")
        source_path = (image_dir / image.image_name).resolve()
        try:
            source_path.relative_to(image_dir)
        except ValueError as error:
            raise ExportError(f"图片路径越界: {image.image_name}") from error
        if not source_path.is_file():
            raise ExportError(f"图片文件不存在: {image.image_name}")
        source_stat = source_path.stat()
        image_sources.append(
            ImageSource(
                id=image.id,
                name=image.image_name,
                path=source_path,
                size=source_stat.st_size,
                mtime_ns=source_stat.st_mtime_ns,
            )
        )
    if not image_sources:
        raise ExportError("Folder 没有图片")
    source_user_id, source_date = parse_source_identity(image_sources[0].name)
    metadata = {
        "clientRework": bool(folder.client_rework),
        "title": folder.title or "",
        "place": fixed_template_value(project, "place"),
        "startDate": folder.start_date,
        "endDate": folder.end_date,
        "recordType": mapped_record_type(project, folder.title or ""),
        "language": fixed_template_value(project, "language"),
        "recordCustodian": fixed_template_value(project, "recordCustodian"),
        "archivalRefNo": folder.archival_ref_no or "",
        "captureOperatorName": fixed_template_value(project, "captureOperatorName"),
        "captureOperatorId": fixed_template_value(project, "captureOperatorId"),
        "volume": folder.volume or "",
        "digitizingEntity": fixed_template_value(project, "digitizingEntity"),
    }
    required_metadata = {
        "Title": metadata["title"],
        "Place": metadata["place"],
        "Start Date": metadata["startDate"],
        "End Date": metadata["endDate"],
        "Record Type": metadata["recordType"],
        "Language": metadata["language"],
        "Record Custodian": metadata["recordCustodian"],
        "Capture Operator Name": metadata["captureOperatorName"],
        "Capture Operator ID": metadata["captureOperatorId"],
        "Volume": metadata["volume"],
        "Digitizing Entity": metadata["digitizingEntity"],
    }
    missing = [name for name, value in required_metadata.items() if value in (None, "")]
    if missing:
        raise ExportError(f"Folder 导出必填元数据缺失: {', '.join(missing)}")
    return FolderExportSnapshot(
        folder_id=folder.id,
        project_id=project.id,
        ingest_project_id=project_ingest_id(project),
        location_code=project.country_location_code,
        metadata=metadata,
        images=image_sources,
        source_user_id=source_user_id,
        source_date=source_date,
    )


def md5_file(path: Path) -> str:
    digest = hashlib.md5(usedforsecurity=False)
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def convert_to_tiff(source_path: Path, target_path: Path) -> tuple[int, int]:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = target_path.with_name(f".{target_path.name}.tmp")
    try:
        with Image.open(source_path) as source:
            if getattr(source, "n_frames", 1) > 1:
                source.seek(0)
            frame = source.copy()
            save_options: dict[str, Any] = {"compression": "tiff_adobe_deflate"}
            if source.info.get("icc_profile"):
                save_options["icc_profile"] = source.info["icc_profile"]
            if source.info.get("dpi"):
                save_options["dpi"] = source.info["dpi"]
            frame.save(temp_path, format="TIFF", **save_options)
        os.replace(temp_path, target_path)
    finally:
        temp_path.unlink(missing_ok=True)
    with Image.open(target_path) as result:
        compression = result.tag_v2.get(259)
        if compression not in DEFLATE_COMPRESSION_TAGS:
            raise ExportError(f"TIFF 未使用 adobe_deflate: {target_path.name}")
        width, height = result.size
        result.verify()
    return width, height


def write_csv(
    path: Path,
    headers: list[str],
    rows: list[dict[str, Any]],
    config: ExportRuntimeConfig,
) -> None:
    with path.open("w", encoding=config.encoding, newline="") as output:
        writer = csv.DictWriter(
            output,
            fieldnames=headers,
            extrasaction="raise",
            lineterminator=config.line_ending,
        )
        writer.writeheader()
        writer.writerows(rows)


def verify_sources_unchanged(snapshot: FolderExportSnapshot) -> None:
    for source in snapshot.images:
        if not source.path.is_file():
            raise ExportError(f"导出期间源图片被删除: {source.name}")
        current = source.path.stat()
        if current.st_size != source.size or current.st_mtime_ns != source.mtime_ns:
            raise ExportError(f"导出期间源图片发生变化: {source.name}")


def build_export_zip(
    snapshot: FolderExportSnapshot,
    group_id: str,
    run_id: str,
    config: ExportRuntimeConfig,
) -> ExportedZip:
    work_dir = config.temp_dir / ".lwcam-export" / "work" / run_id / str(snapshot.folder_id)
    if work_dir.exists():
        shutil.rmtree(work_dir)
    artifacts_dir = work_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    artifact_rows: list[dict[str, Any]] = []
    for index, source in enumerate(snapshot.images, start=1):
        artifact_name = f"{group_id}_Image{index:04d}.tif"
        artifact_path = artifacts_dir / artifact_name
        width, height = convert_to_tiff(source.path, artifact_path)
        artifact_rows.append(
            {
                "Filename": artifact_name,
                "File Size": artifact_path.stat().st_size,
                "Artifact Type": "Image",
                "Hash Algorithm": "MD5",
                "Hash": md5_file(artifact_path),
                "Image Width": width,
                "Image Height": height,
                "Capture ID": artifact_path.stem,
            }
        )
    metadata = snapshot.metadata
    group_rows = [
        {
            "Rework": "TRUE" if metadata["clientRework"] else "FALSE",
            "Title": metadata["title"],
            "Place": metadata["place"],
            "Start Date": format_date(metadata["startDate"]),
            "End Date": format_date(metadata["endDate"]),
            "Record Type": metadata["recordType"],
            "Language": metadata["language"],
            "Record Custodian": metadata["recordCustodian"],
            "Archival Reference Number": metadata["archivalRefNo"],
            "Capture ID": group_id,
            "Capture Operator Name": metadata["captureOperatorName"],
            "Capture Operator ID": metadata["captureOperatorId"],
            "Total Artifacts": len(artifact_rows),
            "Volume": metadata["volume"],
            "Capture Date": snapshot.source_date.isoformat(),
            "Digitizing Entity": metadata["digitizingEntity"],
        }
    ]
    write_csv(work_dir / "GroupMetadataImage.csv", GROUP_CSV_HEADERS, group_rows, config)
    write_csv(work_dir / "ArtifactMetadata.csv", ARTIFACT_CSV_HEADERS, artifact_rows, config)
    verify_sources_unchanged(snapshot)

    zip_path = work_dir / f"{group_id}.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.write(work_dir / "GroupMetadataImage.csv", "GroupMetadataImage.csv")
        archive.write(work_dir / "ArtifactMetadata.csv", "ArtifactMetadata.csv")
        for row in artifact_rows:
            artifact_name = str(row["Filename"])
            archive.write(artifacts_dir / artifact_name, f"artifacts/{artifact_name}")
    expected_names = [
        "GroupMetadataImage.csv",
        "ArtifactMetadata.csv",
        *[f"artifacts/{row['Filename']}" for row in artifact_rows],
    ]
    with zipfile.ZipFile(zip_path) as archive:
        if archive.namelist() != expected_names:
            raise ExportError("ZIP 内文件结构或顺序不符合契约")
        if archive.testzip() is not None:
            raise ExportError("ZIP CRC 校验失败")
    return ExportedZip(
        path=zip_path,
        size=zip_path.stat().st_size,
        sha256=sha256_file(zip_path),
    )


def verify_published_zip(path: Path, group_id: str, artifact_count: int) -> None:
    expected_names = [
        "GroupMetadataImage.csv",
        "ArtifactMetadata.csv",
        *[
            f"artifacts/{group_id}_Image{index:04d}.tif"
            for index in range(1, artifact_count + 1)
        ],
    ]
    try:
        with zipfile.ZipFile(path) as archive:
            if archive.namelist() != expected_names or archive.testzip() is not None:
                raise ExportError("已发布 ZIP 校验失败")
    except (OSError, zipfile.BadZipFile) as error:
        raise ExportError(f"已发布 ZIP 无法读取: {path}") from error


def publish_zip(exported: ExportedZip, group_id: str, config: ExportRuntimeConfig) -> Path:
    staging_dir = config.output_dir / ".staging"
    staging_dir.mkdir(parents=True, exist_ok=True)
    final_path = config.output_dir / f"{group_id}.zip"
    partial_path = staging_dir / f"{group_id}.zip.partial"
    if final_path.is_file():
        same_size = final_path.stat().st_size == exported.size
        if same_size and sha256_file(final_path) == exported.sha256:
            return final_path
        raise ExportError(f"最终目录存在不同内容的同名 ZIP: {final_path.name}")
    try:
        shutil.copyfile(exported.path, partial_path)
        with partial_path.open("rb+") as output:
            output.flush()
            os.fsync(output.fileno())
        if (
            partial_path.stat().st_size != exported.size
            or sha256_file(partial_path) != exported.sha256
        ):
            raise ExportError("ZIP 复制到最终目录后校验失败")
        os.replace(partial_path, final_path)
    finally:
        partial_path.unlink(missing_ok=True)
    return final_path


def finalize_folder(folder_id: int, group_id: str) -> None:
    with SessionLocal() as db:
        folder = db.scalar(
            select(CaptureFolder)
            .options(lazyload("*"))
            .where(CaptureFolder.id == folder_id)
            .with_for_update(of=CaptureFolder)
        )
        if folder is None or folder.is_deleted:
            raise ExportError("最终写回时 Folder 不存在或已删除")
        if folder.is_exported:
            if folder.group_id != group_id:
                raise ExportError("Folder 已由其他导出写入不同 Group ID")
            return
        if folder.qc_status.lower() != "pass":
            raise ExportError("最终写回时 Folder 已不再是 PASS")
        folder.group_id = group_id
        folder.is_tif_converted = True
        folder.is_exported = True
        folder.exported_time = utc_now()
        db.commit()


def eligible_folder_ids(db: Session) -> list[int]:
    return list(
        db.scalars(
            select(CaptureFolder.id)
            .where(
                func.lower(CaptureFolder.qc_status) == "pass",
                CaptureFolder.is_exported.is_not(True),
                CaptureFolder.is_deleted.is_not(True),
            )
            .order_by(CaptureFolder.source_created_at.asc().nullslast(), CaptureFolder.id.asc())
        ).all()
    )


class ExportCoordinator:
    def __init__(self) -> None:
        self._state_lock = threading.RLock()
        self._start_lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._state: dict[str, Any] | None = None

    def _state_root(self, config: ExportRuntimeConfig) -> Path:
        root = config.temp_dir / ".lwcam-export"
        root.mkdir(parents=True, exist_ok=True)
        (root / "runs").mkdir(parents=True, exist_ok=True)
        return root

    @staticmethod
    def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            temporary.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    def _persist(self, config: ExportRuntimeConfig) -> None:
        with self._state_lock:
            if self._state is None:
                return
            payload = json.loads(json.dumps(self._state, ensure_ascii=False, default=str))
        root = self._state_root(config)
        self._atomic_json(root / "active.json", payload)
        self._atomic_json(root / "runs" / f"{payload['runId']}.json", payload)

    def _cleanup_workspaces(self, config: ExportRuntimeConfig) -> None:
        work_root = self._state_root(config) / "work"
        if not work_root.is_dir():
            return
        cutoff = utc_now() - timedelta(hours=settings.export_temp_retention_hours)
        for path in work_root.iterdir():
            try:
                modified = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
                if path.is_dir() and modified < cutoff:
                    shutil.rmtree(path)
            except OSError:
                continue

    def current(self) -> dict[str, Any] | None:
        with self._state_lock:
            if self._state is not None:
                return json.loads(json.dumps(self._state, ensure_ascii=False, default=str))
        try:
            config = runtime_config()
        except ExportError:
            return None
        path = config.temp_dir / ".lwcam-export" / "active.json"
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def history(self) -> list[dict[str, Any]]:
        try:
            config = runtime_config()
        except ExportError:
            return []
        runs_dir = config.temp_dir / ".lwcam-export" / "runs"
        if not runs_dir.is_dir():
            return []
        records = []
        for path in runs_dir.glob("*.json"):
            try:
                records.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                continue
        return sorted(records, key=lambda item: item.get("createdAt", ""), reverse=True)

    def preflight(self, db: Session) -> dict[str, Any]:
        errors: list[str] = []
        config: ExportRuntimeConfig | None = None
        try:
            config = runtime_config()
            validate_runtime_paths(config)
        except ExportError as error:
            errors.append(str(error))
        folder_ids = eligible_folder_ids(db)
        invalid_projects: list[dict[str, Any]] = []
        if folder_ids:
            project_ids = db.scalars(
                select(CaptureBox.project_id)
                .join(CaptureFolder, CaptureFolder.box_id == CaptureBox.box_id)
                .where(CaptureFolder.id.in_(folder_ids))
                .distinct()
            ).all()
            projects = db.scalars(
                select(Project).where(
                    Project.id.in_(project_ids),
                    Project.is_deleted.is_not(True),
                )
            ).all()
            for project in projects:
                try:
                    project_ingest_id(project)
                except ExportError:
                    invalid_projects.append(
                        {
                            "id": project.id,
                            "projectId": project.project_id,
                            "projectName": project.project_name,
                        }
                    )
        if invalid_projects:
            errors.append("存在 projects.project_id 无效的项目")
        return {
            "ready": not errors,
            "errors": errors,
            "eligibleCount": len(folder_ids),
            "invalidProjects": invalid_projects,
            "config": config.to_json() if config else None,
            "activeRun": self.current(),
        }

    def start(
        self,
        admin_user_id: str,
        folder_ids: list[int] | None = None,
        retry_items: dict[int, dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        config = runtime_config()
        validate_runtime_paths(config)
        self._cleanup_workspaces(config)
        with self._start_lock:
            if self._thread is not None and self._thread.is_alive():
                raise ExportError("已有导出任务正在运行")
            with SessionLocal() as db:
                selected = folder_ids if folder_ids is not None else eligible_folder_ids(db)
                if not selected:
                    raise ExportError("没有可导出的 PASS Folder")
            state = {
                "runId": uuid.uuid4().hex,
                "status": "QUEUED",
                "createdBy": admin_user_id,
                "createdAt": utc_now().isoformat(),
                "startedAt": None,
                "completedAt": None,
                "settings": config.to_json(),
                "total": len(selected),
                "succeeded": 0,
                "failed": 0,
                "currentFolderId": None,
                "items": [
                    {
                        "folderId": folder_id,
                        "status": "PENDING",
                        "groupId": (retry_items or {}).get(folder_id, {}).get("groupId"),
                        "zipPath": (retry_items or {}).get(folder_id, {}).get("zipPath"),
                        "zipSize": (retry_items or {}).get(folder_id, {}).get("zipSize"),
                        "zipSha256": (retry_items or {}).get(folder_id, {}).get("zipSha256"),
                        "error": None,
                    }
                    for folder_id in selected
                ],
            }
            with self._state_lock:
                self._state = state
            self._persist(config)
            self._thread = threading.Thread(
                target=self._run,
                args=(config,),
                name=f"lwcam-export-{state['runId']}",
                daemon=True,
            )
            self._thread.start()
            return self.current() or state

    def retry_failed(self, admin_user_id: str) -> dict[str, Any]:
        current = self.current()
        if not current:
            raise ExportError("没有可重试的导出记录")
        failed_items = {
            int(item["folderId"]): item
            for item in current.get("items", [])
            if item.get("status") == "FAILED"
        }
        failed_ids = list(failed_items)
        if not failed_ids:
            raise ExportError("没有失败的 Folder")
        return self.start(admin_user_id, failed_ids, failed_items)

    def resume_if_needed(self) -> None:
        try:
            config = runtime_config()
        except ExportError:
            return
        active_path = config.temp_dir / ".lwcam-export" / "active.json"
        if not active_path.is_file():
            return
        try:
            state = json.loads(active_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if state.get("status") not in {"QUEUED", "RUNNING"}:
            return
        for item in state.get("items", []):
            if item.get("status") == "RUNNING":
                item["status"] = "PENDING"
                item["error"] = "服务重启后重新处理"
        state["status"] = "QUEUED"
        with self._state_lock:
            self._state = state
        with self._start_lock:
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(
                    target=self._run,
                    args=(config,),
                    name=f"lwcam-export-{state['runId']}",
                    daemon=True,
                )
                self._thread.start()

    def _set_item(self, config: ExportRuntimeConfig, item: dict[str, Any], **values: Any) -> None:
        with self._state_lock:
            item.update(values)
            if self._state:
                self._state["succeeded"] = sum(
                    candidate.get("status") == "SUCCEEDED"
                    for candidate in self._state["items"]
                )
                self._state["failed"] = sum(
                    candidate.get("status") == "FAILED"
                    for candidate in self._state["items"]
                )
        self._persist(config)

    def _run(self, config: ExportRuntimeConfig) -> None:
        with engine.connect() as batch_lock:
            acquired = bool(
                batch_lock.scalar(
                    text(
                        "SELECT pg_try_advisory_lock("
                        "hashtextextended('lwcam-export-batch', 0))"
                    ),
                )
            )
            if not acquired:
                with self._state_lock:
                    if self._state:
                        self._state["status"] = "FAILED"
                        self._state["completedAt"] = utc_now().isoformat()
                        self._state["error"] = "另一个后端进程正在执行导出"
                self._persist(config)
                return
            try:
                with self._state_lock:
                    if not self._state:
                        return
                    self._state["status"] = "RUNNING"
                    self._state["startedAt"] = self._state.get("startedAt") or utc_now().isoformat()
                    items = self._state["items"]
                    run_id = self._state["runId"]
                self._persist(config)
                for item in items:
                    if item.get("status") == "SUCCEEDED":
                        continue
                    folder_id = int(item["folderId"])
                    with self._state_lock:
                        if self._state:
                            self._state["currentFolderId"] = folder_id
                    self._set_item(config, item, status="RUNNING", error=None)
                    try:
                        self._export_one(folder_id, run_id, config, item)
                    except Exception as error:
                        self._set_item(config, item, status="FAILED", error=str(error))
                with self._state_lock:
                    if self._state:
                        succeeded = int(self._state["succeeded"])
                        failed = int(self._state["failed"])
                        self._state["status"] = (
                            "SUCCEEDED"
                            if failed == 0
                            else ("FAILED" if succeeded == 0 else "PARTIAL_FAILED")
                        )
                        self._state["currentFolderId"] = None
                        self._state["completedAt"] = utc_now().isoformat()
                self._persist(config)
            finally:
                batch_lock.execute(
                    text(
                        "SELECT pg_advisory_unlock("
                        "hashtextextended('lwcam-export-batch', 0))"
                    ),
                )

    def _export_one(
        self,
        folder_id: int,
        run_id: str,
        config: ExportRuntimeConfig,
        item: dict[str, Any],
    ) -> None:
        with engine.connect() as folder_lock:
            acquired = bool(
                folder_lock.scalar(
                    text(
                        "SELECT pg_try_advisory_lock("
                        "hashtextextended(:resource, 0))"
                    ),
                    {"resource": f"lwcam-export-folder:{folder_id}"},
                )
            )
            if not acquired:
                raise ExportError("Folder 正由其他导出进程处理")
            try:
                with SessionLocal() as db:
                    folder = db.get(CaptureFolder, folder_id)
                    if folder is not None and folder.is_exported:
                        self._set_item(
                            config,
                            item,
                            status="SUCCEEDED",
                            groupId=folder.group_id,
                            zipPath=str(config.output_dir / f"{folder.group_id}.zip"),
                        )
                        return
                    snapshot = load_folder_snapshot(db, folder_id)
                    group_id = str(item.get("groupId") or "")
                    if not group_id:
                        sequence = allocate_sequence(db, snapshot.project_id)
                        group_id = build_group_id(snapshot, sequence)
                    db.commit()
                self._set_item(config, item, groupId=group_id)
                final_candidate = config.output_dir / f"{group_id}.zip"
                if final_candidate.is_file() and not item.get("zipPath"):
                    verify_published_zip(
                        final_candidate,
                        group_id,
                        len(snapshot.images),
                    )
                    self._set_item(
                        config,
                        item,
                        zipPath=str(final_candidate),
                        zipSize=final_candidate.stat().st_size,
                        zipSha256=sha256_file(final_candidate),
                    )
                    finalize_folder(folder_id, group_id)
                    self._set_item(config, item, status="SUCCEEDED")
                    return
                existing_path_value = item.get("zipPath")
                existing_path = (
                    Path(str(existing_path_value)) if existing_path_value else None
                )
                expected_size = item.get("zipSize")
                expected_sha256 = item.get("zipSha256")
                if (
                    existing_path
                    and existing_path.is_file()
                    and expected_size == existing_path.stat().st_size
                    and expected_sha256 == sha256_file(existing_path)
                ):
                    finalize_folder(folder_id, group_id)
                    self._set_item(config, item, status="SUCCEEDED")
                    return
                exported = build_export_zip(snapshot, group_id, run_id, config)
                final_path = publish_zip(exported, group_id, config)
                self._set_item(
                    config,
                    item,
                    zipPath=str(final_path),
                    zipSize=final_path.stat().st_size,
                    zipSha256=sha256_file(final_path),
                )
                finalize_folder(folder_id, group_id)
                self._set_item(
                    config,
                    item,
                    status="SUCCEEDED",
                )
            finally:
                folder_lock.execute(
                    text(
                        "SELECT pg_advisory_unlock("
                        "hashtextextended(:resource, 0))"
                    ),
                    {"resource": f"lwcam-export-folder:{folder_id}"},
                )


export_coordinator = ExportCoordinator()


__all__ = [
    "ARTIFACT_CSV_HEADERS",
    "GROUP_CSV_HEADERS",
    "ExportCoordinator",
    "ExportError",
    "ExportRuntimeConfig",
    "FolderExportSnapshot",
    "allocate_sequence",
    "build_export_zip",
    "build_group_id",
    "export_coordinator",
    "format_date",
    "parse_source_identity",
    "runtime_config",
]
