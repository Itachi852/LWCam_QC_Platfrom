import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from watchdog.events import FileCreatedEvent, FileMovedEvent

from app.core.config import Settings
from app.services.ingest_client import IngestError, UploadResult
from app.services.upload_worker import (
    IngestSummaryWriter,
    UploadCandidate,
    UploadConfigurationError,
    UploadWorker,
    UploadZipEventHandler,
    candidate_from_folder,
    runtime_config,
)


class FakeClient:
    def __init__(self, *, already_ingested=False, confirm_error=None):
        self.already_ingested = already_ingested
        self.confirm_error = confirm_error
        self.calls = []

    def check_zipfilename_ingested(self, filename):
        self.calls.append(("check", filename))
        return self.already_ingested

    def generate_zip_id(self, project_id, site_id):
        self.calls.append(("generate", project_id, site_id))
        return "ZIP-123"

    def upload_zip(self, path):
        self.calls.append(("upload", path.name))
        return UploadResult(size_mb=1.0, speed_mb_s=2.0, duration_s=0.5)

    def confirm_zip_uploaded(self, zip_hash, zip_id, filename):
        self.calls.append(("confirm", zip_hash, zip_id, filename))
        if self.confirm_error:
            raise self.confirm_error


class FakeSummaryWriter:
    def __init__(self):
        self.calls = []

    def upsert(self, candidate, **kwargs):
        self.calls.append((candidate, kwargs))


class RecoveryDb:
    def __init__(self, ingested):
        self.ingested = ingested

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def scalar(self, _):
        return SimpleNamespace(is_ingested=self.ingested)


class FakeObserver:
    def __init__(self, *, start_error=None):
        self.start_error = start_error
        self.handler = None
        self.path = None
        self.recursive = None
        self.started = False
        self.stopped = False
        self.joined = False

    def schedule(self, handler, path, *, recursive):
        self.handler = handler
        self.path = path
        self.recursive = recursive

    def start(self):
        if self.start_error:
            raise self.start_error
        self.started = True

    def stop(self):
        self.stopped = True

    def join(self, timeout=None):
        self.joined = True

    def is_alive(self):
        return self.started and not self.stopped


def enabled_settings(root: Path, **overrides):
    values = {
        "_env_file": None,
        "upload_enabled": "true",
        "export_output_dir": str(root / "export"),
        "upload_success_dir": str(root / "success"),
        "upload_failed_dir": str(root / "failed"),
        "upload_duplicates_dir": str(root / "duplicates"),
        "upload_report_dir": str(root / "reports"),
        "upload_stable_seconds": 0,
        "upload_gate_retry_seconds": 0.001,
        "upload_gate_max_wait_seconds": 0.05,
        "upload_max_retries": 1,
        "ingest_api_base_url": "http://ingest.test",
        "ingest_api_authorization": "Basic api-token",
        "hfs_upload_url": "http://hfs.test/ScanImages",
        "hfs_username": "hfs-user",
        "hfs_password": "hfs-password",
        "ingest_db_host": "mysql.test",
        "ingest_db_name": "LWCam",
        "ingest_db_user": "mysql-user",
        "ingest_db_password": "mysql-password",
    }
    values.update(overrides)
    (root / "export").mkdir(parents=True, exist_ok=True)
    return Settings(**values)


def write_zip(path: Path):
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("artifacts/G1_Image0001.tif", b"image")


class UploadSafetyTests(unittest.TestCase):
    def test_upload_enabled_only_accepts_explicit_true(self):
        for value in (None, "", "false", "0", "yes", "invalid", False):
            config = Settings(_env_file=None, upload_enabled=value)
            self.assertFalse(config.upload_enabled, value)
        self.assertTrue(Settings(_env_file=None, upload_enabled="true").upload_enabled)
        self.assertTrue(Settings(_env_file=None, upload_enabled=True).upload_enabled)

    def test_disabled_worker_has_no_filesystem_or_database_side_effects(self):
        with tempfile.TemporaryDirectory() as temporary:
            missing = Path(temporary) / "must-not-be-created"
            config = Settings(
                _env_file=None,
                upload_enabled=False,
                export_output_dir=str(missing),
            )

            def forbidden_session():
                raise AssertionError("database must not be touched")

            def forbidden_observer():
                raise AssertionError("observer must not be constructed")

            worker = UploadWorker(
                config,
                session_factory=forbidden_session,
                observer_factory=forbidden_observer,
            )
            self.assertFalse(worker.start())
            self.assertFalse(missing.exists())

    def test_project_ingest_config_uses_template_and_legacy_project_id_fallback(self):
        project = SimpleNamespace(
            project_id="LEGACY-PROJECT",
            project_name="Project name",
            is_deleted=False,
            template={
                "ingest": {
                    "site_id": "ZA",
                    "region": "ZA",
                    "title": "Ingest title",
                }
            },
        )
        folder = SimpleNamespace(
            id=1,
            group_id="G1",
            title="Folder title",
            box=SimpleNamespace(project=project),
        )

        candidate = candidate_from_folder(folder)

        self.assertIsNotNone(candidate)
        self.assertEqual(candidate.project_id, "LEGACY-PROJECT")
        self.assertEqual(candidate.site_id, "ZA")
        self.assertEqual(candidate.title, "Ingest title")

    def test_disabled_project_is_not_a_candidate(self):
        project = SimpleNamespace(
            project_id="PROJECT",
            project_name="Project name",
            is_deleted=False,
            template={"ingest": {"enabled": False}},
        )
        folder = SimpleNamespace(
            id=1,
            group_id="G1",
            title=None,
            box=SimpleNamespace(project=project),
        )

        self.assertIsNone(candidate_from_folder(folder))

    def test_string_false_cannot_accidentally_enable_project(self):
        project = SimpleNamespace(
            project_id="PROJECT",
            project_name="Project name",
            is_deleted=False,
            template={"ingest": {"enabled": "false"}},
        )
        folder = SimpleNamespace(
            id=1,
            group_id="G1",
            title=None,
            box=SimpleNamespace(project=project),
        )

        with self.assertRaisesRegex(UploadConfigurationError, "must be a boolean"):
            candidate_from_folder(folder)

    def test_summary_writer_upserts_existing_mysql_table(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = enabled_settings(Path(temporary))
            connection = MagicMock()
            cursor = connection.cursor.return_value
            with patch(
                "app.services.upload_worker.mysql.connector.connect",
                return_value=connection,
            ) as connect:
                IngestSummaryWriter(config).upsert(
                    UploadCandidate(
                        folder_id=1,
                        group_id="G1",
                        project_id="PROJECT",
                        site_id="ZA",
                        region="ZA",
                        title="Title",
                    ),
                    image_count=2,
                    zip_size_mb=3.5,
                    result=UploadResult(
                        size_mb=3.5,
                        speed_mb_s=1.25,
                        duration_s=2.8,
                    ),
                )

        connect.assert_called_once()
        sql, params = cursor.execute.call_args.args
        self.assertIn("INSERT INTO ingest_summary", sql)
        self.assertIn("ON DUPLICATE KEY UPDATE", sql)
        self.assertEqual(params[:6], ("G1", "Title", 2, 3.5, 1.25, 2.8))
        connection.commit.assert_called_once()
        cursor.close.assert_called_once()
        connection.close.assert_called_once()


class UploadFlowTests(unittest.TestCase):
    candidate = UploadCandidate(
        folder_id=1,
        group_id="G1",
        project_id="PROJECT",
        site_id="ZA",
        region="ZA",
        title="Test project",
    )

    def make_worker(self, root, fake_client):
        config = enabled_settings(root)
        summary = FakeSummaryWriter()
        worker = UploadWorker(config, client=fake_client, summary_writer=summary)
        worker._runtime = runtime_config(config)
        worker._folder_still_eligible = lambda candidate: True
        marked = []
        worker._mark_ingested = lambda candidate: marked.append(candidate.group_id)
        return worker, summary, marked

    def test_complete_upload_moves_to_success_and_marks_ingested(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            client = FakeClient()
            worker, summary, marked = self.make_worker(root, client)
            write_zip(root / "export" / "G1.zip")

            worker._process(self.candidate)

            self.assertTrue((root / "success" / "G1.zip").is_file())
            self.assertFalse((root / "export" / "G1.zip").exists())
            self.assertEqual(marked, ["G1"])
            self.assertEqual(len(summary.calls), 1)
            self.assertEqual(
                [call[0] for call in client.calls],
                ["check", "generate", "upload", "confirm"],
            )

    def test_remote_duplicate_skips_upload_and_moves_to_duplicates(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            client = FakeClient(already_ingested=True)
            worker, summary, marked = self.make_worker(root, client)
            write_zip(root / "export" / "G1.zip")

            worker._process(self.candidate)

            self.assertTrue((root / "duplicates" / "G1.zip").is_file())
            self.assertEqual(marked, ["G1"])
            self.assertEqual(len(summary.calls), 1)
            self.assertEqual([call[0] for call in client.calls], ["check"])

    def test_transient_confirmation_error_restores_zip_for_safe_retry(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            client = FakeClient(
                confirm_error=IngestError(
                    "confirmation timed out",
                    stage="confirm",
                    transient=True,
                )
            )
            worker, _, marked = self.make_worker(root, client)
            write_zip(root / "export" / "G1.zip")

            worker._process(self.candidate)

            self.assertTrue((root / "export" / "G1.zip").is_file())
            self.assertFalse((root / "failed" / "G1.zip").exists())
            self.assertEqual(marked, [])
            self.assertTrue((root / "reports" / "G1.error.json").is_file())

    def test_restart_restores_unfinished_claim_to_export(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = enabled_settings(root)
            claimed = root / "export" / "G1.zip.uploading"
            write_zip(claimed)
            worker = UploadWorker(
                config,
                session_factory=lambda: RecoveryDb(False),
                client=FakeClient(),
                summary_writer=FakeSummaryWriter(),
            )
            worker._runtime = runtime_config(config)

            worker._recover_uploading_files()

            self.assertTrue((root / "export" / "G1.zip").is_file())
            self.assertFalse(claimed.exists())

    def test_restart_archives_claim_when_database_is_already_ingested(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = enabled_settings(root)
            claimed = root / "export" / "G1.zip.uploading"
            write_zip(claimed)
            worker = UploadWorker(
                config,
                session_factory=lambda: RecoveryDb(True),
                client=FakeClient(),
                summary_writer=FakeSummaryWriter(),
            )
            worker._runtime = runtime_config(config)

            worker._recover_uploading_files()

            self.assertTrue((root / "success" / "G1.zip").is_file())
            self.assertFalse(claimed.exists())


class UploadDiscoveryTests(unittest.TestCase):
    def test_watchdog_accepts_created_and_moved_top_level_zips_only(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            nested = root / "nested"
            nested.mkdir()
            detected = []
            handler = UploadZipEventHandler(root, lambda path: detected.append(path) or True)

            handler.on_created(FileCreatedEvent(str(root / "G1.zip")))
            handler.on_moved(
                FileMovedEvent(
                    str(root / "G2.zip.partial"),
                    str(root / "G2.zip"),
                )
            )
            handler.on_created(FileCreatedEvent(str(root / "G3.zip.uploading")))
            handler.on_created(FileCreatedEvent(str(root / "notes.txt")))
            handler.on_created(FileCreatedEvent(str(nested / "G4.zip")))

            self.assertEqual(
                [path.name for path in detected],
                ["G1.zip", "G2.zip"],
            )

    def test_queue_deduplicates_repeated_events(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = enabled_settings(root)
            worker = UploadWorker(config)
            worker._runtime = runtime_config(config)
            path = root / "export" / "G1.zip"

            self.assertTrue(worker._enqueue_path(path))
            self.assertFalse(worker._enqueue_path(path))
            self.assertEqual(worker._queue.qsize(), 1)

    def test_folder_scan_only_enqueues_files_and_does_not_query_database(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = enabled_settings(root)
            write_zip(root / "export" / "G1.zip")

            def forbidden_session():
                raise AssertionError("folder scan must not query database")

            worker = UploadWorker(config, session_factory=forbidden_session)
            worker._runtime = runtime_config(config)

            self.assertEqual(worker._scan_export_folder(), 1)
            self.assertEqual(worker._queue.qsize(), 1)

    def test_start_constructs_observer_and_immediately_scans_existing_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = enabled_settings(root)
            observer = FakeObserver()
            worker = UploadWorker(
                config,
                client=FakeClient(),
                summary_writer=FakeSummaryWriter(),
                observer_factory=lambda: observer,
            )
            scan = MagicMock(return_value=0)
            worker._scan_export_folder = scan

            self.assertTrue(worker.start())
            worker.stop()

            self.assertTrue(observer.started)
            self.assertFalse(observer.recursive)
            self.assertIsInstance(observer.handler, UploadZipEventHandler)
            scan.assert_called_once()
            self.assertTrue(observer.stopped)
            self.assertTrue(observer.joined)

    def test_watchdog_failure_keeps_reconciliation_worker_running(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = enabled_settings(root)
            observer = FakeObserver(start_error=OSError("events unsupported"))
            worker = UploadWorker(
                config,
                client=FakeClient(),
                summary_writer=FakeSummaryWriter(),
                observer_factory=lambda: observer,
            )
            worker._scan_export_folder = MagicMock(return_value=0)

            self.assertTrue(worker.start())
            self.assertTrue(worker.is_running)
            self.assertIsNone(worker._observer)
            self.assertTrue(observer.stopped)
            self.assertTrue(observer.joined)
            worker.stop()

    def test_gate_retries_single_group_until_export_writeback_is_ready(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = enabled_settings(root)
            worker = UploadWorker(config)
            candidate = UploadCandidate(
                folder_id=1,
                group_id="G1",
                project_id="PROJECT",
                site_id="ZA",
                region="ZA",
                title="Title",
            )
            states = iter([("wait", None), ("ready", candidate)])
            worker._load_candidate_state = MagicMock(side_effect=lambda _: next(states))

            result = worker._wait_for_candidate("G1")

            self.assertEqual(result, candidate)
            self.assertEqual(worker._load_candidate_state.call_count, 2)

    def test_gate_timeout_leaves_zip_untouched_for_reconciliation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = enabled_settings(
                root,
                upload_gate_max_wait_seconds=0,
            )
            path = root / "export" / "G1.zip"
            write_zip(path)
            worker = UploadWorker(config)
            worker._runtime = runtime_config(config)
            worker._load_candidate_state = MagicMock(return_value=("wait", None))
            worker._process = MagicMock()

            worker._handle_path(path)

            self.assertTrue(path.is_file())
            worker._process.assert_not_called()
            self.assertFalse((root / "reports" / "G1.error.json").exists())


if __name__ == "__main__":
    unittest.main()
