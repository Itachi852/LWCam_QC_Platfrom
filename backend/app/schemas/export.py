from datetime import datetime
from typing import Any

from pydantic import BaseModel


class ExportableFolderVO(BaseModel):
    folderId: int
    folderName: str
    folderSeq: int
    boxName: str
    projectId: str
    projectName: str
    imageCount: int


class ExportFolderVO(ExportableFolderVO):
    qcStatus: str
    isExported: bool
    exportedTime: datetime | None
    groupId: str | None
    exportable: bool


class ExportPreflightVO(BaseModel):
    ready: bool
    errors: list[str]
    eligibleCount: int
    exportedCount: int
    invalidProjects: list[dict[str, Any]]
    config: dict[str, Any] | None
    activeRun: dict[str, Any] | None
