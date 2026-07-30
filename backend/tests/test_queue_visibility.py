"""The QC queue must not offer folders LWIP has not finished.

qc_status defaults to 'PENDING' the moment a folder syncs, so without the
folder_path gate a folder becomes claimable before its images exist on disk.
Compiling the clause is enough to catch it being dropped again — no DB needed.
"""

from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from app.models.capture import CaptureFolder
from app.routers.qc import visible_folder_conditions


def compiled() -> str:
    statement = select(CaptureFolder.id).where(*visible_folder_conditions([1]))
    return str(statement.compile(dialect=postgresql.dialect()))


def test_queue_requires_an_image_directory() -> None:
    assert "folder_path IS NOT NULL" in compiled()


def test_queue_still_excludes_deleted_folders() -> None:
    sql = compiled()
    assert "is_deleted" in sql
    assert "project_id IN" in sql
