from typing import Any

from pydantic import BaseModel


class ExportPreflightVO(BaseModel):
    ready: bool
    errors: list[str]
    eligibleCount: int
    invalidProjects: list[dict[str, Any]]
    config: dict[str, Any] | None
    activeRun: dict[str, Any] | None
