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
    if status == 404:
        code = ApiCodes.NOT_FOUND
    elif status == 409:
        code = ApiCodes.CONFLICT
    else:
        code = ApiCodes.BAD_REQUEST
    return BusinessError(code, str(error), status, error.to_dict())


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
        raise as_business_error(ExportError("folderMissing"), 404)
    if folder.is_exported:
        raise as_business_error(ExportError("folderAlreadyExported"), 409)
    if folder.qc_status.lower() != "pass":
        raise as_business_error(ExportError("folderNotPass"))
    try:
        return ok(export_coordinator.start(current_user.user_id, [folder_id]))
    except ExportError as error:
        raise as_business_error(error, 409) from error


@router.post("/run", response_model=ApiResponse[dict[str, Any]])
def run_export(current_user: AdminUser, db: DbSession) -> ApiResponse[dict[str, Any]]:
    preflight = export_coordinator.preflight(db)
    if not preflight["ready"]:
        issue = preflight["errors"][0]
        raise as_business_error(
            ExportError(issue["errorKey"], issue.get("errorParams")),
        )
    try:
        return ok(export_coordinator.start(current_user.user_id))
    except ExportError as error:
        raise as_business_error(error, 409) from error


@router.get("/current", response_model=ApiResponse[dict[str, Any] | None])
def current_export(_: AdminUser) -> ApiResponse[dict[str, Any] | None]:
    return ok(export_coordinator.current())
