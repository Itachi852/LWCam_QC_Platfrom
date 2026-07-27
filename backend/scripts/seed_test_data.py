#!/usr/bin/env python3
from __future__ import annotations

import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings
from app.core.security import hash_password
from app.models.capture import CaptureBox, CaptureFolder, CaptureImage
from app.models.project import Device, Project, Role, UserProject
from app.models.qc_session import ReworkLog
from app.models.user import User


PROJECT_ROOT = Path(__file__).resolve().parents[2]
TESTDATA_ROOT = Path(r"E:\LifeWodd\testdata")
NOW = datetime.now(timezone.utc)

TITLE_RECORD_TYPE_MAP = {
    "WWI South African Mounted Rifles Military Personnel Cards": "Military Service Records",
    "WWI South African Mounted Rifles Military Indexes": "Military Service Record Indexes",
    "WWI Medical Files": "Military Medical Records",
    "WWII Medical Files": "Military Medical Records",
}

PROJECT_TEMPLATE = {
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
        {"key": "startDate", "label": "Start Date", "input": "select", "mandatory": True, "exported": True, "options": ["1914", "1939"]},
        {"key": "endDate", "label": "End Date", "input": "select", "mandatory": True, "exported": True, "options": ["1918", "1945"]},
        {"key": "archivalRefNo", "label": "Archival Reference Number", "input": "text", "mandatory": False, "exported": True},
        {"key": "recordType", "label": "Record Type", "input": "fixed", "value": "Military Medical Records", "exported": True},
        {"key": "place", "label": "Place", "input": "fixed", "value": "South Africa", "exported": True},
        {"key": "language", "label": "Language", "input": "fixed", "value": "English", "exported": True},
        {"key": "recordCustodian", "label": "Record Custodian", "input": "fixed", "value": "South Africa Department of Defense", "exported": True},
        {"key": "digitizingEntity", "label": "Digitizing Entity", "input": "fixed", "value": "Lifewood", "exported": True},
        {"key": "captureOperatorId", "label": "Capture Operator ID", "input": "fixed", "value": "cis.user.MM38-RXW3"},
        {"key": "captureOperatorName", "label": "Capture Operator Name", "input": "fixed", "value": "lifewoodza01"},
    ],
    "titleRecordTypeMap": TITLE_RECORD_TYPE_MAP,
}

ACCOUNTS = [
    {"user_id": "admin", "password": "Admin@123456", "roles": "admin"},
    {"user_id": "qc_test", "password": "Test@123456", "roles": "qc"},
]

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}


def folder_seq_from_name(name: str, fallback: int) -> int:
    digits = "".join(char for char in name if char.isdigit())
    return int(digits) if digits else fallback


def discover_testdata() -> list[dict]:
    if not TESTDATA_ROOT.is_dir():
        raise RuntimeError(f"Test data directory not found: {TESTDATA_ROOT}")

    discovered: list[dict] = []
    for box_dir in sorted(path for path in TESTDATA_ROOT.iterdir() if path.is_dir()):
        folder_path_dirs = sorted(path for path in box_dir.iterdir() if path.is_dir() and path.name.endswith("_path") and not path.name.endswith("_thumbnail_path"))
        folders: list[dict] = []
        for index, folder_path in enumerate(folder_path_dirs, start=1):
            prefix = folder_path.name.removesuffix("_path")
            thumbnail_path = box_dir / f"{prefix}_thumbnail_path"
            images = sorted(path for path in folder_path.iterdir() if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS)
            if not images:
                continue
            folders.append({
                "name": prefix,
                "seq": folder_seq_from_name(prefix, index),
                "folder_path": folder_path.resolve(),
                "thumbnail_path": thumbnail_path.resolve() if thumbnail_path.is_dir() else None,
                "images": images,
            })
        if folders:
            discovered.append({
                "box_name": box_dir.name,
                "root": box_dir.resolve(),
                "folders": folders,
            })

    if not discovered:
        raise RuntimeError(f"No usable box/folder image data found under {TESTDATA_ROOT}")
    return discovered


def clear_all(db: Session) -> None:
    db.execute(text("""
        TRUNCATE
            rework_logs,
            capture_images,
            capture_folders,
            capture_boxes,
            user_projects,
            devices,
            projects,
            users,
            roles
        RESTART IDENTITY CASCADE
    """))
    db.commit()


def clear_qc_cache() -> None:
    for path in [PROJECT_ROOT / "backend" / ".cache" / "qc_work", PROJECT_ROOT / "backend" / ".cache" / "qc_deleted"]:
        if path.exists():
            for manifest in path.rglob("manifest.json"):
                manifest.unlink(missing_ok=True)
            try:
                shutil.rmtree(path)
            except PermissionError as error:
                print(f"WARNING: QC cache cleanup skipped locked file: {error}")


def seed(db: Session) -> None:
    role_admin = Role(role_name="Admin")
    role_qc = Role(role_name="QC")
    db.add_all([role_admin, role_qc])
    db.flush()

    users: dict[str, User] = {}
    for account in ACCOUNTS:
        user = User(
            user_id=account["user_id"],
            password=hash_password(account["password"]),
            roles=account["roles"],
            active=True,
            must_change_password=False,
        )
        db.add(user)
        users[account["user_id"]] = user
    db.flush()

    project = Project(
        project_id="QC_TEST_001",
        project_key="qc_test_project",
        project_name="QC Split Test Project",
        country_location_code="ZA-QC",
        start_date=NOW,
        has_data=True,
        template=PROJECT_TEMPLATE,
    )
    db.add(project)
    db.flush()

    device = Device(
        device_id="QC-STATION-01",
        country_location_code=project.country_location_code,
        user_id=users["qc_test"].id,
    )
    db.add(device)
    db.flush()

    db.add(UserProject(user_id=users["admin"].id, project_id=project.id, role_id=role_admin.id))
    db.add(UserProject(user_id=users["qc_test"].id, project_id=project.id, role_id=role_qc.id))
    db.flush()

    for box_index, box_data in enumerate(discover_testdata(), start=1):
        box = CaptureBox(
            box_name=box_data["box_name"],
            device_id=device.id,
            status="TRANSFERRED",
            user_id=users["qc_test"].id,
            project_id=project.id,
            transfer_start_at=NOW - timedelta(days=3, minutes=box_index),
            transfer_end_at=NOW - timedelta(days=2, minutes=box_index),
            transferred_to=str(box_data["root"]),
        )
        db.add(box)
        db.flush()

        for folder_index, folder_data in enumerate(box_data["folders"], start=1):
            source_time = NOW - timedelta(days=box_index, minutes=folder_index)
            folder = CaptureFolder(
                folder_name=f"{box_data['box_name']}_{folder_data['name']}",
                box_id=box.box_id,
                device_id=device.id,
                folder_seq=folder_data["seq"],
                qc_status="PENDING",
                folder_path=str(folder_data["folder_path"]),
                thumbnail_path=str(folder_data["thumbnail_path"]) if folder_data["thumbnail_path"] else None,
                cover_tag="Cover Will Be Captured",
                image_tags="Faded or Damaged Documents",
                title="WWII Medical Files",
                volume=f"{box_data['box_name']} {folder_data['name']}",
                start_date=datetime(1939, 1, 1, tzinfo=timezone.utc),
                end_date=datetime(1945, 1, 1, tzinfo=timezone.utc),
                archival_ref_no=f"{box_data['box_name'].upper()}-{folder_data['seq']:03d}",
                record_type="Military Medical Records",
                place="South Africa",
                language="English",
                record_custodian="South Africa Department of Defense",
                digitizing_entity="Lifewood",
                capture_operator_id="cis.user.MM38-RXW3",
                capture_operator_name="lifewoodza01",
                is_deskewed=True,
                is_cropped=True,
                is_created_thumbnail=folder_data["thumbnail_path"] is not None,
                source_created_at=source_time,
                source_updated_at=source_time,
            )
            db.add(folder)
            db.flush()

            for image_index, image_path in enumerate(folder_data["images"]):
                db.add(CaptureImage(
                    image_name=image_path.name,
                    device_id=device.id,
                    folder_id=folder.id,
                    file_format=image_path.suffix.lstrip(".").lower(),
                    image_created_at=source_time + timedelta(seconds=image_index),
                ))

    db.commit()


def verify(db: Session) -> None:
    counts = db.execute(text("""
        SELECT
            (SELECT count(*) FROM users) AS users,
            (SELECT count(*) FROM projects) AS projects,
            (SELECT count(*) FROM capture_folders) AS folders,
            (SELECT count(*) FROM capture_images) AS images
    """)).fetchone()
    print(f"users={counts.users}, projects={counts.projects}, folders={counts.folders}, images={counts.images}")

    rows = db.execute(text("""
        SELECT f.id, f.folder_name, f.qc_status, count(i.id) AS image_count
        FROM capture_folders f
        LEFT JOIN capture_images i ON i.folder_id = f.id
        GROUP BY f.id, f.folder_name, f.qc_status
        ORDER BY f.folder_seq
    """)).fetchall()
    for row in rows:
        print(f"folder_id={row.id} name={row.folder_name} status={row.qc_status} images={row.image_count}")


if __name__ == "__main__":
    print(f"Connecting to {settings.db_host}:{settings.db_port}/{settings.db_name}")
    engine = create_engine(settings.database_url, echo=False)
    with Session(engine) as db:
        clear_all(db)
        clear_qc_cache()
        seed(db)
        verify(db)

    print("\nAccounts:")
    for account in ACCOUNTS:
        print(f"  {account['user_id']} / {account['password']}")
