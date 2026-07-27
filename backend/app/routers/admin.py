from datetime import date, datetime, time, timedelta, timezone

from fastapi import APIRouter, Query
from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import lazyload, selectinload

from app.core.errors import ApiCodes, BusinessError
from app.core.responses import ApiResponse, PageResult, ok
from app.core.security import hash_password
from app.dependencies import AdminUser, DbSession
from app.models.capture import CaptureBox, CaptureFolder, CaptureImage
from app.models.project import Project, Role, UserProject
from app.models.user import ROLE_ADMIN, ROLE_QC, User
from app.schemas.admin import (
    AdminQcTaskVO,
    CreateUserRequest,
    ProjectOptionVO,
    ResetPasswordRequest,
    StatsOverviewVO,
    UpdateUserRequest,
    UserAdminVO,
)
from app.services.serializers import to_user_admin_vo

router = APIRouter(prefix="/admin", tags=["admin"])
ALLOWED_ROLES = {"admin": ROLE_ADMIN, "qc": ROLE_QC}
ALLOWED_STATUSES = {"active", "disabled"}
FOLDER_STATUS_LABELS = {
    "pending": "pending",
    "reviewing": "reviewing",
    "pass": "passed",
    "rework": "rework",
}


def now() -> datetime:
    return datetime.now(timezone.utc)


def user_or_404(db, user_id: int) -> User:
    user = db.scalar(select(User).options(selectinload(User.projects)).where(User.id == user_id))
    if user is None or user.is_deleted is True:
        raise BusinessError(ApiCodes.NOT_FOUND, "用户不存在", 404)
    return user


def canonical_role(role: str) -> str:
    result = ALLOWED_ROLES.get(role.strip().lower())
    if result is None:
        raise BusinessError(ApiCodes.BAD_REQUEST, "只允许创建管理员或QC账号")
    return result


def active_projects(db, project_ids: list[int]) -> list[Project]:
    ids = list(dict.fromkeys(project_ids))
    if not ids:
        return []
    projects = db.scalars(
        select(Project).where(Project.id.in_(ids), Project.is_deleted.is_not(True))
    ).all()
    if len(projects) != len(ids):
        raise BusinessError(ApiCodes.BAD_REQUEST, "包含不存在或已删除的项目")
    return list(projects)


def apply_role_projects(user: User, role: str, status: str, projects: list[Project]) -> None:
    if status not in ALLOWED_STATUSES:
        raise BusinessError(ApiCodes.BAD_REQUEST, "不支持的用户状态")
    if role == ROLE_QC and status == "active" and not projects:
        raise BusinessError(ApiCodes.BAD_REQUEST, "启用的QC账号至少需要分配一个项目")
    user.roles = role
    user.active = status == "active"


def role_id_for(db, role_name: str) -> int:
    role_id = db.scalar(select(Role.id).where(func.lower(Role.role_name) == role_name.lower()))
    if role_id is None:
        raise BusinessError(ApiCodes.BAD_REQUEST, f"Role {role_name} does not exist")
    return role_id


def replace_user_projects(db, user: User, role: str, projects: list[Project]) -> None:
    db.execute(delete(UserProject).where(UserProject.user_id == user.id))
    if role != ROLE_QC:
        return
    role_id = role_id_for(db, ROLE_QC)
    db.add_all([
        UserProject(user_id=user.id, project_id=project.id, role_id=role_id)
        for project in projects
    ])


@router.get("/users", response_model=ApiResponse[PageResult[UserAdminVO]])
def list_users(
    _: AdminUser,
    db: DbSession,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
    keyword: str | None = None,
    role: str | None = None,
    status: str | None = None,
) -> ApiResponse[PageResult[UserAdminVO]]:
    statement = select(User).options(selectinload(User.projects)).where(User.is_deleted.is_not(True))
    if keyword and keyword.strip():
        statement = statement.where(User.user_id.ilike(f"%{keyword.strip()}%"))
    if role:
        role_value = role.strip().lower()
        database_role = ALLOWED_ROLES.get(role_value)
        if role_value == "super_admin":
            database_role = "SuperAdmin"
        if database_role is None:
            raise BusinessError(ApiCodes.BAD_REQUEST, "不支持的用户角色")
        statement = statement.where(func.lower(User.roles) == database_role.lower())
    if status:
        if status not in ALLOWED_STATUSES:
            raise BusinessError(ApiCodes.BAD_REQUEST, "不支持的用户状态")
        statement = statement.where(User.active.is_(status == "active"))

    total = db.scalar(select(func.count()).select_from(statement.order_by(None).subquery())) or 0
    users = db.scalars(
        statement.order_by(User.created_at.desc()).offset((page - 1) * size).limit(size)
    ).unique().all()
    return ok(PageResult(records=[to_user_admin_vo(user) for user in users], total=total, page=page, size=size))


@router.post("/users", response_model=ApiResponse[UserAdminVO])
def create_user(request: CreateUserRequest, current_user: AdminUser, db: DbSession) -> ApiResponse[UserAdminVO]:
    login_id = request.userId.strip()
    if db.scalar(select(User.id).where(User.user_id == login_id)) is not None:
        raise BusinessError(ApiCodes.CONFLICT, "账号已存在", 409)
    role = canonical_role(request.role)
    projects = active_projects(db, request.projectIds)
    user = User(
        user_id=login_id,
        password=hash_password(request.password),
        roles=role,
        active=True,
        must_change_password=True,
        created_by=current_user.id,
        updated_by=current_user.id,
        is_deleted=False,
    )
    apply_role_projects(user, role, "active", projects)
    db.add(user)
    db.flush()
    replace_user_projects(db, user, role, projects)
    db.commit()
    db.expire(user, ["projects"])
    return ok(to_user_admin_vo(user_or_404(db, user.id)))


@router.put("/users/{user_id}", response_model=ApiResponse[UserAdminVO])
def update_user(
    user_id: int,
    request: UpdateUserRequest,
    current_user: AdminUser,
    db: DbSession,
) -> ApiResponse[UserAdminVO]:
    user = user_or_404(db, user_id)
    if user.id == current_user.id and request.status == "disabled":
        raise BusinessError(ApiCodes.BAD_REQUEST, "不能禁用当前登录账号")
    if user.role == "super_admin":
        raise BusinessError(ApiCodes.BAD_REQUEST, "SuperAdmin账号不能在此修改")
    role = canonical_role(request.role)
    projects = active_projects(db, request.projectIds)
    apply_role_projects(user, role, request.status, projects)
    replace_user_projects(db, user, role, projects)
    user.updated_by = current_user.id
    db.commit()
    db.expire(user, ["projects"])
    return ok(to_user_admin_vo(user_or_404(db, user.id)))


@router.delete("/users/{user_id}", response_model=ApiResponse[None])
def delete_user(user_id: int, current_user: AdminUser, db: DbSession) -> ApiResponse[None]:
    if user_id == current_user.id:
        raise BusinessError(ApiCodes.BAD_REQUEST, "不能删除当前登录账号")
    user = user_or_404(db, user_id)
    if user.role == "super_admin":
        raise BusinessError(ApiCodes.BAD_REQUEST, "SuperAdmin账号不能删除")
    user.active = False
    user.is_deleted = True
    user.deleted_at = now()
    user.updated_by = current_user.id
    db.execute(delete(UserProject).where(UserProject.user_id == user.id))
    db.commit()
    return ok(None)


@router.put("/users/{user_id}/password", response_model=ApiResponse[None])
def reset_password(
    user_id: int,
    request: ResetPasswordRequest,
    current_user: AdminUser,
    db: DbSession,
) -> ApiResponse[None]:
    user = user_or_404(db, user_id)
    user.password = hash_password(request.newPassword)
    user.must_change_password = True
    user.updated_by = current_user.id
    db.commit()
    return ok(None)


@router.get("/projects/options", response_model=ApiResponse[list[ProjectOptionVO]])
def project_options(_: AdminUser, db: DbSession) -> ApiResponse[list[ProjectOptionVO]]:
    projects = db.scalars(
        select(Project).where(Project.is_deleted.is_not(True)).order_by(Project.project_name.asc())
    ).all()
    return ok([
        ProjectOptionVO(id=project.id, projectId=project.project_id, projectName=project.project_name)
        for project in projects
    ])


@router.get("/qc-tasks", response_model=ApiResponse[PageResult[AdminQcTaskVO]])
def list_reviewing_qc_tasks(
    _: AdminUser,
    db: DbSession,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
    keyword: str | None = None,
    project_id: int | None = Query(default=None, alias="projectId"),
) -> ApiResponse[PageResult[AdminQcTaskVO]]:
    conditions = [
        func.lower(CaptureFolder.qc_status) == "pending",
        CaptureFolder.qc_locked_by.is_not(None),
        CaptureFolder.is_deleted.is_not(True),
        CaptureBox.is_deleted.is_not(True),
    ]
    if keyword and keyword.strip():
        pattern = f"%{keyword.strip()}%"
        conditions.append(or_(
            CaptureFolder.folder_name.ilike(pattern),
            CaptureBox.box_name.ilike(pattern),
            CaptureFolder.qc_locked_by.ilike(pattern),
            Project.project_name.ilike(pattern),
            Project.project_id.ilike(pattern),
        ))
    if project_id is not None:
        conditions.append(CaptureBox.project_id == project_id)

    image_count = (
        select(func.count(CaptureImage.id))
        .where(CaptureImage.folder_id == CaptureFolder.id)
        .correlate(CaptureFolder)
        .scalar_subquery()
    )
    statement = (
        select(CaptureFolder, CaptureBox, Project, image_count.label("image_count"))
        .join(CaptureBox, CaptureBox.box_id == CaptureFolder.box_id)
        .outerjoin(Project, Project.id == CaptureBox.project_id)
        .where(*conditions)
    )
    total = db.scalar(
        select(func.count(CaptureFolder.id))
        .select_from(CaptureFolder)
        .join(CaptureBox, CaptureBox.box_id == CaptureFolder.box_id)
        .outerjoin(Project, Project.id == CaptureBox.project_id)
        .where(*conditions)
    ) or 0
    rows = db.execute(
        statement.order_by(CaptureFolder.qc_locked_at.asc().nullslast(), CaptureFolder.id.asc())
        .offset((page - 1) * size)
        .limit(size)
    ).all()

    records = []
    for folder, box, project, count in rows:
        reviewer_id = None
        if folder.qc_locked_by:
            reviewer_id = db.scalar(select(User.id).where(User.user_id == folder.qc_locked_by))
        records.append(AdminQcTaskVO(
            folderId=folder.id,
            folderName=folder.folder_name,
            folderSeq=folder.folder_seq,
            boxId=box.box_id,
            boxName=box.box_name,
            projectId=project.id if project else None,
            projectCode=project.project_id if project else None,
            projectName=project.project_name if project else None,
            reviewerId=reviewer_id,
            reviewerUserId=folder.qc_locked_by or "",
            imageCount=count or 0,
            claimedAt=folder.qc_locked_at,
            updatedAt=folder.updated_at,
        ))
    return ok(PageResult(records=records, total=total, page=page, size=size))


@router.post("/qc-tasks/{folder_id}/release", response_model=ApiResponse[None])
def admin_release_qc_task(
    folder_id: int,
    current_user: AdminUser,
    db: DbSession,
) -> ApiResponse[None]:
    folder = db.scalar(
        select(CaptureFolder)
        .options(lazyload("*"))
        .where(CaptureFolder.id == folder_id)
        .with_for_update()
    )
    if folder is None or folder.is_deleted is True:
        raise BusinessError(ApiCodes.NOT_FOUND, "QC任务不存在", 404)
    if folder.qc_status.lower() != "pending":
        raise BusinessError(ApiCodes.CONFLICT, "任务已不在审核中，请刷新列表", 409)
    if folder.qc_locked_by is None:
        raise BusinessError(ApiCodes.CONFLICT, "任务未被领取，请刷新列表", 409)

    folder.qc_locked_by = None
    folder.qc_locked_at = None
    folder.updated_at = now()
    db.commit()
    return ok(None)


@router.get("/stats/overview", response_model=ApiResponse[StatsOverviewVO])
def stats_overview(_: AdminUser, db: DbSession) -> ApiResponse[StatsOverviewVO]:
    today_start = datetime.combine(date.today(), time.min, tzinfo=timezone.utc)
    tomorrow = today_start + timedelta(days=1)

    today_new = db.scalar(
        select(func.count()).select_from(CaptureFolder).where(
            CaptureFolder.is_deleted.is_not(True),
            CaptureFolder.source_created_at >= today_start,
            CaptureFolder.source_created_at < tomorrow,
        )
    ) or 0
    today_reviews = db.scalar(
        select(func.count()).select_from(CaptureFolder).where(
            CaptureFolder.is_deleted.is_not(True),
            func.lower(CaptureFolder.qc_status).in_(["pass", "rework"]),
            CaptureFolder.updated_at >= today_start,
            CaptureFolder.updated_at < tomorrow,
        )
    ) or 0
    today_passed = db.scalar(
        select(func.count()).select_from(CaptureFolder).where(
            CaptureFolder.is_deleted.is_not(True),
            func.lower(CaptureFolder.qc_status) == "pass",
            CaptureFolder.updated_at >= today_start,
            CaptureFolder.updated_at < tomorrow,
        )
    ) or 0
    total_users = db.scalar(select(func.count()).select_from(User).where(User.is_deleted.is_not(True))) or 0
    total_tasks = db.scalar(
        select(func.count()).select_from(CaptureFolder).where(CaptureFolder.is_deleted.is_not(True))
    ) or 0
    pending = db.scalar(
        select(func.count()).select_from(CaptureFolder).where(
            CaptureFolder.is_deleted.is_not(True),
            func.lower(CaptureFolder.qc_status) == "pending",
            CaptureFolder.qc_locked_by.is_(None),
        )
    ) or 0
    reviewing = db.scalar(
        select(func.count()).select_from(CaptureFolder).where(
            CaptureFolder.is_deleted.is_not(True),
            func.lower(CaptureFolder.qc_status) == "pending",
            CaptureFolder.qc_locked_by.is_not(None),
        )
    ) or 0

    distribution_rows = db.execute(
        select(func.lower(CaptureFolder.qc_status), func.count(CaptureFolder.id))
        .where(CaptureFolder.is_deleted.is_not(True), CaptureFolder.qc_status.is_not(None))
        .group_by(func.lower(CaptureFolder.qc_status))
    ).all()
    distribution = []
    for status, count in distribution_rows:
        adjusted_count = pending if status == "pending" else count
        distribution.append({
            "status": FOLDER_STATUS_LABELS.get(status, status),
            "label": status,
            "count": adjusted_count,
        })
    if reviewing:
        distribution.append({"status": "reviewing", "label": "reviewing", "count": reviewing})

    trend = []
    for offset in range(6, -1, -1):
        day = date.today() - timedelta(days=offset)
        start = datetime.combine(day, time.min, tzinfo=timezone.utc)
        end = start + timedelta(days=1)
        count = db.scalar(
            select(func.count()).select_from(CaptureFolder).where(
                CaptureFolder.is_deleted.is_not(True),
                func.lower(CaptureFolder.qc_status).in_(["pass", "rework"]),
                CaptureFolder.updated_at >= start,
                CaptureFolder.updated_at < end,
            )
        ) or 0
        trend.append({"date": day.isoformat(), "count": count})

    workload_rows = db.execute(
        select(User.id, User.user_id)
        .where(User.is_deleted.is_not(True), func.lower(User.roles) == ROLE_QC.lower())
        .order_by(User.user_id.asc())
    ).all()
    workload = [
        {"reviewerId": user_id, "reviewerName": name, "total": 0, "approved": 0, "rejected": 0}
        for user_id, name in workload_rows
    ]

    return ok(StatsOverviewVO(
        todayNewTasks=today_new,
        todayCompletedTasks=today_reviews,
        todayQcPassRate=round(today_passed * 100 / today_reviews, 2) if today_reviews else 0.0,
        totalUsers=total_users,
        totalTasks=total_tasks,
        pendingClaimTasks=pending,
        taskTrend=trend,
        taskStatusDistribution=distribution,
        reviewerWorkload=workload,
    ))
