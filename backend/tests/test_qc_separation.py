from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image

from app.routers.qc import apply_separation_commit
from app.services.qc_separation import (
    SeparationFileError,
    SeparationFileTransaction,
    child_directory_path,
)


def create_image(path: Path, color: str = "white") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (32, 24), color).save(path, format="TIFF")


class ChildDirectoryPathTests(unittest.TestCase):
    def test_standard_and_recursive_names(self) -> None:
        parent = Path("D:/box/folder1_path")
        self.assertEqual(
            child_directory_path(parent, 1),
            Path("D:/box/folder1_001_path"),
        )
        self.assertEqual(
            child_directory_path(Path("D:/box/folder1_001_path"), 1),
            Path("D:/box/folder1_001_001_path"),
        )
        self.assertEqual(
            child_directory_path(
                Path("D:/box/folder1_thumbnail_path"),
                2,
                thumbnail=True,
            ),
            Path("D:/box/folder1_002_thumbnail_path"),
        )

    def test_nonstandard_name_appends_index(self) -> None:
        self.assertEqual(
            child_directory_path(Path("D:/box/images"), 3),
            Path("D:/box/images_003"),
        )


class SeparationFileTransactionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.image_dir = self.root / "folder1_path"
        self.thumbnail_dir = self.root / "folder1_thumbnail_path"
        self.image_dir.mkdir()
        self.thumbnail_dir.mkdir()
        for index in range(1, 4):
            create_image(self.image_dir / f"page-{index}.tif")
        create_image(self.thumbnail_dir / "page-1.tif", "gray")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def transaction(self) -> SeparationFileTransaction:
        return SeparationFileTransaction(
            self.image_dir,
            self.thumbnail_dir,
            [["page-1.tif"], ["page-2.tif", "page-3.tif"]],
        )

    def test_apply_moves_images_and_builds_missing_thumbnails(self) -> None:
        transaction = self.transaction()
        transaction.apply()

        first = self.root / "folder1_001_path"
        second = self.root / "folder1_002_path"
        first_thumbnails = self.root / "folder1_001_thumbnail_path"
        second_thumbnails = self.root / "folder1_002_thumbnail_path"
        self.assertEqual({item.name for item in first.iterdir()}, {"page-1.tif"})
        self.assertEqual(
            {item.name for item in second.iterdir()},
            {"page-2.tif", "page-3.tif"},
        )
        self.assertEqual(
            {item.name for item in first_thumbnails.iterdir()},
            {"page-1.tif"},
        )
        self.assertEqual(
            {item.name for item in second_thumbnails.iterdir()},
            {"page-2.tif", "page-3.tif"},
        )
        self.assertEqual(list(self.image_dir.iterdir()), [])
        self.assertEqual(list(self.thumbnail_dir.iterdir()), [])

    def test_rollback_restores_original_files_and_removes_generated_thumbnails(self) -> None:
        transaction = self.transaction()
        transaction.apply()
        transaction.rollback()

        self.assertEqual(
            {item.name for item in self.image_dir.iterdir()},
            {"page-1.tif", "page-2.tif", "page-3.tif"},
        )
        self.assertEqual(
            {item.name for item in self.thumbnail_dir.iterdir()},
            {"page-1.tif"},
        )
        self.assertFalse((self.root / "folder1_001_path").exists())
        self.assertFalse((self.root / "folder1_002_path").exists())
        self.assertFalse((self.root / "folder1_001_thumbnail_path").exists())
        self.assertFalse((self.root / "folder1_002_thumbnail_path").exists())

    def test_mid_apply_failure_rolls_back_moved_files(self) -> None:
        transaction = self.transaction()
        real_move = shutil.move
        calls = 0

        def fail_once(source: str, target: str):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("injected move failure")
            return real_move(source, target)

        with patch("app.services.qc_separation.shutil.move", side_effect=fail_once):
            with self.assertRaises(SeparationFileError):
                transaction.apply()

        self.assertEqual(
            {item.name for item in self.image_dir.iterdir()},
            {"page-1.tif", "page-2.tif", "page-3.tif"},
        )
        self.assertEqual(
            {item.name for item in self.thumbnail_dir.iterdir()},
            {"page-1.tif"},
        )
        self.assertFalse((self.root / "folder1_001_path").exists())
        self.assertFalse((self.root / "folder1_002_path").exists())

    def test_existing_target_is_rejected_before_any_move(self) -> None:
        (self.root / "folder1_001_path").mkdir()
        transaction = self.transaction()

        with self.assertRaisesRegex(SeparationFileError, "目标目录已存在"):
            transaction.apply()

        self.assertEqual(
            {item.name for item in self.image_dir.iterdir()},
            {"page-1.tif", "page-2.tif", "page-3.tif"},
        )

    def test_without_thumbnail_directory_creates_image_directories_only(self) -> None:
        transaction = SeparationFileTransaction(
            self.image_dir,
            None,
            [["page-1.tif"], ["page-2.tif", "page-3.tif"]],
        )
        transaction.apply()

        self.assertTrue((self.root / "folder1_001_path").is_dir())
        self.assertTrue((self.root / "folder1_002_path").is_dir())
        self.assertFalse((self.root / "folder1_001_thumbnail_path").exists())
        self.assertFalse((self.root / "folder1_002_thumbnail_path").exists())

    def test_read_only_parent_is_rejected_before_any_move(self) -> None:
        transaction = self.transaction()
        real_access = os.access

        def access(path: Path, mode: int) -> bool:
            if Path(path) == self.image_dir.parent:
                return False
            return real_access(path, mode)

        with patch("app.services.qc_separation.os.access", side_effect=access):
            with self.assertRaisesRegex(SeparationFileError, "原图目录不可写"):
                transaction.apply()

        self.assertEqual(
            {item.name for item in self.image_dir.iterdir()},
            {"page-1.tif", "page-2.tif", "page-3.tif"},
        )

    def test_cleanup_keeps_parent_directory_with_untracked_file(self) -> None:
        transaction = self.transaction()
        transaction.apply()
        (self.image_dir / "untracked.txt").write_text("keep", encoding="utf-8")
        transaction.cleanup_empty_parent_directories()

        self.assertTrue(self.image_dir.is_dir())
        self.assertTrue((self.image_dir / "untracked.txt").is_file())
        self.assertFalse(self.thumbnail_dir.exists())


class FakeScalarResult:
    def __init__(self, values: list[object]) -> None:
        self.values = values

    def all(self) -> list[object]:
        return self.values


class FakeDb:
    def __init__(self, images: list[object]) -> None:
        self.images = images
        self.added: list[object] = []
        self.next_id = 100

    def scalar(self, _statement):
        return 20

    def scalars(self, _statement) -> FakeScalarResult:
        return FakeScalarResult(self.images)

    def add(self, value: object) -> None:
        self.added.append(value)

    def flush(self) -> None:
        for value in self.added:
            if getattr(value, "id", None) is None:
                value.id = self.next_id
                self.next_id += 1


class SeparationDatabaseProjectionTests(unittest.TestCase):
    def test_children_receive_physical_paths_and_parent_is_soft_deleted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            image_dir = root / "folder1_path"
            image_dir.mkdir()
            images = [
                SimpleNamespace(id=index, image_name=f"page-{index}.tif", folder_id=7)
                for index in range(1, 4)
            ]
            for image in images:
                create_image(image_dir / image.image_name)
            folder = SimpleNamespace(
                id=7,
                group_id=None,
                folder_name="box1234_folder1",
                box_id=2,
                device_id=3,
                cover_tag="Cover Will Be Captured",
                image_tags=None,
                title="WWI Medical Files",
                volume="1",
                start_date=None,
                end_date=None,
                archival_ref_no=None,
                record_type="Military Medical Records",
                place="South Africa",
                language="English",
                record_custodian="Custodian",
                capture_operator_id="operator-id",
                capture_operator_name="operator",
                digitizing_entity="Lifewood",
                client_qc_status=None,
                is_deskewed=True,
                is_cropped=True,
                is_created_thumbnail=False,
                folder_path=str(image_dir),
                thumbnail_path=None,
                qc_status="PENDING",
                qc_locked_by="qc01",
                qc_locked_at=datetime.now(timezone.utc),
                is_tif_converted=False,
                is_deleted=False,
                deleted_at=None,
            )
            db = FakeDb(images)

            transaction = apply_separation_commit(
                db,
                folder,
                marker_ids=[1, 2],
                ordered_ids=[1, 2, 3],
                commit_time=datetime.now(timezone.utc),
            )
            try:
                self.assertEqual(len(db.added), 2)
                self.assertEqual(
                    [Path(child.folder_path).name for child in db.added],
                    ["folder1_001_path", "folder1_002_path"],
                )
                self.assertEqual([image.folder_id for image in images], [100, 101, 101])
                self.assertTrue(folder.is_deleted)
                self.assertIsNotNone(folder.deleted_at)
                self.assertIsNone(folder.folder_path)
                self.assertIsNone(folder.thumbnail_path)
                self.assertIsNone(folder.qc_locked_by)
            finally:
                transaction.rollback()


if __name__ == "__main__":
    unittest.main()
