import csv
import tempfile
import unittest
import zipfile
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from PIL import Image

from app.services.export import (
    ARTIFACT_CSV_HEADERS,
    GROUP_CSV_HEADERS,
    ExportCoordinator,
    ExportError,
    ExportRuntimeConfig,
    FolderExportSnapshot,
    ImageSource,
    build_export_zip,
    build_group_id,
    list_export_folders,
    load_folder_snapshot,
    parse_source_identity,
)


class ExportContractTests(unittest.TestCase):
    def test_export_error_exposes_stable_localization_payload(self) -> None:
        error = ExportError("imageMissing", {"filename": "page_001.tif"})

        self.assertEqual(
            error.to_dict(),
            {
                "errorKey": "imageMissing",
                "errorParams": {"filename": "page_001.tif"},
            },
        )
        self.assertIn("page_001.tif", str(error))

    @staticmethod
    def _config(root: Path) -> ExportRuntimeConfig:
        return ExportRuntimeConfig(
            temp_dir=root / "temp",
            output_dir=root / "output",
            encoding="utf-8",
            line_ending_name="CRLF",
            line_ending="\r\n",
        )

    @staticmethod
    def _run_state(item: dict[str, object]) -> dict[str, object]:
        return {
            "runId": "test-run",
            "status": "QUEUED",
            "createdAt": "2026-01-01T00:00:00+00:00",
            "succeeded": 0,
            "failed": 0,
            "skipped": 0,
            "items": [item],
        }

    def test_source_identity_comes_from_source_filename(self) -> None:
        user_id, capture_date = parse_source_identity(
            "SAX10_IMG_20251124_130152_001.tif"
        )
        self.assertEqual(user_id, "SAX10")
        self.assertEqual(capture_date, date(2025, 11, 24))

    def test_group_id_uses_six_digit_sequence(self) -> None:
        snapshot = FolderExportSnapshot(
            folder_id=1,
            project_id=7,
            ingest_project_id="M92P-8ZS",
            location_code="ZA01",
            metadata={},
            images=[],
            source_user_id="SAX10",
            source_date=date(2025, 11, 24),
        )
        self.assertEqual(
            build_group_id(snapshot, 42),
            "M92P-8ZSZA01SAX10251124000042",
        )

    def test_zip_matches_csv_and_tiff_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_path = root / "SAX10_IMG_20251124_130152_001.png"
            Image.new("RGB", (23, 17), (20, 80, 140)).save(source_path)
            source_stat = source_path.stat()
            snapshot = FolderExportSnapshot(
                folder_id=1,
                project_id=7,
                ingest_project_id="M92P-8ZS",
                location_code="ZA01",
                metadata={
                    "clientRework": False,
                    "title": "Title",
                    "place": "South Africa",
                    "startDate": date(1914, 1, 1),
                    "endDate": date(1918, 12, 31),
                    "recordType": "Military Service Records",
                    "language": "English",
                    "recordCustodian": "Custodian",
                    "archivalRefNo": "REF-1",
                    "captureOperatorName": "lifewoodza01",
                    "captureOperatorId": "cis.user.MM38-RXW3",
                    "volume": "1",
                    "digitizingEntity": "Lifewood",
                },
                images=[
                    ImageSource(
                        id=1,
                        name=source_path.name,
                        path=source_path,
                        size=source_stat.st_size,
                        mtime_ns=source_stat.st_mtime_ns,
                    )
                ],
                source_user_id="SAX10",
                source_date=date(2025, 11, 24),
            )
            config = ExportRuntimeConfig(
                temp_dir=root / "temp",
                output_dir=root / "output",
                encoding="utf-8",
                line_ending_name="CRLF",
                line_ending="\r\n",
            )
            group_id = build_group_id(snapshot, 1)
            exported = build_export_zip(snapshot, group_id, "run-1", config)

            with zipfile.ZipFile(exported.path) as archive:
                artifact_name = f"{group_id}_Image0001.tif"
                self.assertEqual(
                    archive.namelist(),
                    [
                        "GroupMetadataImage.csv",
                        "ArtifactMetadata.csv",
                        f"artifacts/{artifact_name}",
                    ],
                )
                group_bytes = archive.read("GroupMetadataImage.csv")
                artifact_bytes = archive.read("ArtifactMetadata.csv")
                self.assertIn(b"\r\n", group_bytes)
                group_rows = list(csv.DictReader(group_bytes.decode("utf-8").splitlines()))
                artifact_rows = list(
                    csv.DictReader(artifact_bytes.decode("utf-8").splitlines())
                )
                self.assertEqual(list(group_rows[0]), GROUP_CSV_HEADERS)
                self.assertEqual(list(artifact_rows[0]), ARTIFACT_CSV_HEADERS)
                self.assertEqual(group_rows[0]["Capture ID"], group_id)
                self.assertEqual(group_rows[0]["Total Artifacts"], "1")
                self.assertEqual(artifact_rows[0]["Capture ID"], Path(artifact_name).stem)

                extracted = root / artifact_name
                extracted.write_bytes(archive.read(f"artifacts/{artifact_name}"))
                with Image.open(extracted) as image:
                    self.assertEqual(image.size, (23, 17))
                    self.assertIn(image.tag_v2.get(259), {8, 32946})

    def test_snapshot_maps_database_folder_path_before_reading_images(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            local_directory = Path(temporary)
            image_name = "SAX10_IMG_20251124_130152_001.png"
            (local_directory / image_name).write_bytes(b"image")
            project = SimpleNamespace(
                id=7,
                project_id="M92P-8ZS",
                project_name="Project",
                country_location_code="ZA01",
                is_deleted=False,
                template={
                    "fields": [
                        {"key": "place", "value": "South Africa"},
                        {"key": "language", "value": "English"},
                        {"key": "recordCustodian", "value": "Custodian"},
                        {"key": "captureOperatorName", "value": "operator"},
                        {"key": "captureOperatorId", "value": "operator-id"},
                        {"key": "digitizingEntity", "value": "Lifewood"},
                    ],
                    "titleRecordTypeMap": {"Title": "Record Type"},
                },
            )
            folder = SimpleNamespace(
                id=1,
                is_deleted=False,
                qc_status="PASS",
                is_exported=False,
                folder_path=r"\\NAS01\LWCamProcessed\Box01\Folder001",
                images=[
                    SimpleNamespace(
                        id=1,
                        image_name=image_name,
                        image_created_at=None,
                    )
                ],
                box=SimpleNamespace(project=project),
                client_rework=False,
                title="Title",
                start_date="1914",
                end_date="1918",
                archival_ref_no="",
                volume="1",
            )
            db = MagicMock()
            db.scalar.return_value = folder

            with patch("app.services.export.to_local", return_value=local_directory) as mapper:
                snapshot = load_folder_snapshot(db, folder.id)

            mapper.assert_called_once_with(folder.folder_path)
            self.assertEqual(snapshot.images[0].path, local_directory / image_name)

    def test_folder_list_applies_database_pagination(self) -> None:
        db = MagicMock()
        db.scalar.return_value = 25
        db.execute.return_value.all.return_value = [
            SimpleNamespace(
                folder_id=11,
                folder_name="folder-11",
                folder_seq=11,
                qc_status="PASS",
                is_exported=False,
                exported_time=None,
                group_id=None,
                box_name="box-1",
                project_id="PROJECT-1",
                project_name="Project",
                image_count=6,
            )
        ]

        records, total = list_export_folders(
            db,
            "unexported",
            page=2,
            size=10,
        )

        statement = db.execute.call_args.args[0]
        self.assertEqual(statement._offset_clause.value, 10)
        self.assertEqual(statement._limit_clause.value, 10)
        self.assertIn("lower(capture_folders.qc_status) != ", str(statement))
        self.assertEqual(total, 25)
        self.assertEqual([record["folderId"] for record in records], [11])

    def test_busy_folder_is_skipped_not_failed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = self._config(Path(temporary))
            item: dict[str, object] = {"folderId": 1, "status": "PENDING"}
            coordinator = ExportCoordinator()
            coordinator._state = self._run_state(item)

            with patch("app.services.export.engine.connect") as connect:
                connect.return_value.__enter__.return_value.scalar.return_value = False
                coordinator._export_one(1, "test-run", config, item)

            self.assertEqual(item["status"], "SKIPPED_BUSY")
            self.assertEqual(item["errorKey"], "folderBusy")
            self.assertEqual(item["errorParams"], {})
            self.assertEqual(coordinator._state["failed"], 0)
            self.assertEqual(coordinator._state["skipped"], 1)

    def test_run_completes_when_all_items_are_skipped_busy(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = self._config(Path(temporary))
            item: dict[str, object] = {"folderId": 1, "status": "PENDING"}
            coordinator = ExportCoordinator()
            coordinator._state = self._run_state(item)

            def skip_busy(
                folder_id: int,
                run_id: str,
                config: ExportRuntimeConfig,
                item: dict[str, object],
            ) -> None:
                coordinator._set_item(
                    config,
                    item,
                    status="SKIPPED_BUSY",
                    error="Folder 正由另一工作站导出",
                )

            with patch.object(coordinator, "_export_one", side_effect=skip_busy):
                coordinator._run(config)

            self.assertEqual(coordinator._state["status"], "SUCCEEDED")
            self.assertEqual(coordinator._state["failed"], 0)
            self.assertEqual(coordinator._state["skipped"], 1)

    def test_persist_keeps_only_active_run_and_removes_legacy_history(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = self._config(Path(temporary))
            runs_dir = config.temp_dir / ".lwcam-export" / "runs"
            runs_dir.mkdir(parents=True)
            (runs_dir / "old-run.json").write_text("{}", encoding="utf-8")
            coordinator = ExportCoordinator()
            coordinator._state = self._run_state(
                {"folderId": 1, "status": "FAILED", "error": "test"}
            )

            coordinator._persist(config)

            self.assertTrue((config.temp_dir / ".lwcam-export" / "active.json").is_file())
            self.assertFalse(runs_dir.exists())


if __name__ == "__main__":
    unittest.main()
