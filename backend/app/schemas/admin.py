from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class CreateUserRequest(BaseModel):
    userId: str = Field(min_length=3, max_length=255, pattern=r"^[a-zA-Z0-9_.@-]+$")
    password: str = Field(min_length=6, max_length=64)
    role: str
    projectIds: list[int] = Field(default_factory=list)


class UpdateUserRequest(BaseModel):
    role: str
    status: str
    projectIds: list[int] = Field(default_factory=list)


class ResetPasswordRequest(BaseModel):
    newPassword: str = Field(min_length=6, max_length=64)


class UserAdminVO(BaseModel):
    id: int
    userId: str
    role: str
    status: str
    projectIds: list[int]
    projectNames: list[str]
    createdAt: datetime
    lastLoginAt: datetime | None = None
    mustChangePassword: bool


class ProjectOptionVO(BaseModel):
    id: int
    projectId: str
    projectName: str


class AdminQcTaskVO(BaseModel):
    folderId: int
    folderName: str
    folderSeq: int
    boxId: int
    boxName: str
    projectId: int | None = None
    projectCode: str | None = None
    projectName: str | None = None
    reviewerId: int | None = None
    reviewerUserId: str
    imageCount: int
    claimedAt: datetime | None = None
    updatedAt: datetime


class StatsOverviewVO(BaseModel):
    todayNewTasks: int
    todayCompletedTasks: int
    todayQcPassRate: float
    totalUsers: int
    totalTasks: int
    pendingClaimTasks: int
    taskTrend: list[dict[str, Any]]
    taskStatusDistribution: list[dict[str, Any]]
    reviewerWorkload: list[dict[str, Any]]
