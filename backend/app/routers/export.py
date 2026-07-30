from typing import Any

from fastapi import APIRouter, Query
from app.core.errors import ApiCodes, BusinessError
from app.core.responses import ApiResponse, PageResult, ok
from app.dependencies import AdminUser, DbSession
from app.models.capture import CaptureFolder
from app.schemas.export import ExportFolderVO, ExportPreflightVO
from app.services.export import ExportError, export_coordinator, list_export_folders

router = APIRouter(prefix="/admin/exports", tags=["exports"])


def as_business_error(error: ExportError, status: int = 400) -> BusinessError:
    code = ApiCodes.CONFLICT if status == 409 else ApiCodes.BAD_REQUEST
    return BusinessError(code, str(error), status)


@router.get("/preflight", response_model=ApiResponse[ExportPreflightVO])
def export_preflight(_: AdminUser, db: DbSession) -> ApiResponse[ExportPreflightVO]:
    return ok(ExportPreflightVO.model_validate(export_coordinator.preflight(db)))


@router.get("/folders", response_model=ApiResponse[PageResult[ExportFolderVO]])
def export_folders(
    _: AdminUser,
    db: DbSession,
    export_status: str = Query(default="all", alias="exportStatus", pattern="^(all|exported|unexported)$"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
) -> ApiResponse[PageResult[ExportFolderVO]]:
    folders, total = list_export_folders(
        db,
        export_status,
        page=page,
        size=size,
    )
    return ok(
        PageResult(
            records=[ExportFolderVO.model_validate(folder) for folder in folders],
            total=total,
            page=page,
            size=size,
        )
    )


@router.post("/folders/{folder_id}", response_model=ApiResponse[dict[str, Any]])
def run_folder_export(
    folder_id: int,
    current_user: AdminUser,
    db: DbSession,
) -> ApiResponse[dict[str, Any]]:
    folder = db.get(CaptureFolder, folder_id)
    if folder is None or folder.is_deleted:
        raise BusinessError(ApiCodes.NOT_FOUND, "Folder 不存在", 404)
    if folder.is_exported:
        raise BusinessError(ApiCodes.CONFLICT, "Folder 已导出，不可重复导出", 409)
    if folder.qc_status.lower() != "pass":
        raise BusinessError(ApiCodes.BAD_REQUEST, "Folder 尚未通过 QC，不能导出")
    try:
        return ok(export_coordinator.start(current_user.user_id, [folder_id]))
    except ExportError as error:
        raise as_business_error(error, 409) from error


@router.post("/run", response_model=ApiResponse[dict[str, Any]])
def run_export(current_user: AdminUser, db: DbSession) -> ApiResponse[dict[str, Any]]:
    preflight = export_coordinator.preflight(db)
    if not preflight["ready"]:
        raise BusinessError(
            ApiCodes.BAD_REQUEST,
            "；".join(preflight["errors"]),
        )
    try:
        return ok(export_coordinator.start(current_user.user_id))
    except ExportError as error:
        raise as_business_error(error, 409) from error


@router.get("/current", response_model=ApiResponse[dict[str, Any] | None])
def current_export(_: AdminUser) -> ApiResponse[dict[str, Any] | None]:
    return ok(export_coordinator.current())

