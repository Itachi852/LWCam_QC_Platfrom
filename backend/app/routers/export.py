from typing import Any

from fastapi import APIRouter
from app.core.errors import ApiCodes, BusinessError
from app.core.responses import ApiResponse, ok
from app.dependencies import AdminUser, DbSession
from app.schemas.export import ExportPreflightVO
from app.services.export import ExportError, export_coordinator

router = APIRouter(prefix="/admin/exports", tags=["exports"])


def as_business_error(error: ExportError, status: int = 400) -> BusinessError:
    code = ApiCodes.CONFLICT if status == 409 else ApiCodes.BAD_REQUEST
    return BusinessError(code, str(error), status)


@router.get("/preflight", response_model=ApiResponse[ExportPreflightVO])
def export_preflight(_: AdminUser, db: DbSession) -> ApiResponse[ExportPreflightVO]:
    return ok(ExportPreflightVO.model_validate(export_coordinator.preflight(db)))


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


@router.get("/runs", response_model=ApiResponse[list[dict[str, Any]]])
def export_runs(_: AdminUser) -> ApiResponse[list[dict[str, Any]]]:
    return ok(export_coordinator.history())


@router.post("/retry", response_model=ApiResponse[dict[str, Any]])
def retry_export(current_user: AdminUser) -> ApiResponse[dict[str, Any]]:
    try:
        return ok(export_coordinator.retry_failed(current_user.user_id))
    except ExportError as error:
        raise as_business_error(error, 409) from error

