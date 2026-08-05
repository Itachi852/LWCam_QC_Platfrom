import io
import logging
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.core.config import Settings, settings
from app.core.logging_config import configure_logging


class LoggingConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self):
        configure_logging(settings)
        self.temporary.cleanup()

    def config(self, **overrides):
        values = {
            "_env_file": None,
            "log_dir": str(self.root / "logs"),
            "log_level": "INFO",
            "log_max_bytes": 50 * 1024 * 1024,
            "log_backup_count": 10,
        }
        values.update(overrides)
        return Settings(**values)

    @staticmethod
    def flush_handlers():
        for logger_name in (
            None,
            "app.services.upload_worker",
            "app.services.ingest_client",
            "uvicorn",
            "uvicorn.error",
            "uvicorn.access",
        ):
            for handler in logging.getLogger(logger_name).handlers:
                handler.flush()

    def read(self, filename):
        self.flush_handlers()
        return (self.root / "logs" / filename).read_text(encoding="utf-8")

    def test_creates_both_log_files_immediately(self):
        lwcam_path, uploader_path = configure_logging(self.config())

        self.assertTrue(lwcam_path.is_file())
        self.assertTrue(uploader_path.is_file())
        self.assertEqual(lwcam_path.parent, self.root / "logs")

    def test_routes_application_uvicorn_and_uploader_logs(self):
        console = io.StringIO()
        with patch("app.core.logging_config.sys.stderr", console):
            configure_logging(self.config())

        logging.getLogger("app.tests.general").info("普通应用日志")
        logging.getLogger("uvicorn.access").info("GET /api/test 200")
        logging.getLogger("uvicorn.error").error("Uvicorn 服务错误")
        logging.getLogger("app.services.upload_worker").info("上传任务日志")
        logging.getLogger("app.services.ingest_client").warning("ingest 警告")

        lwcam = self.read("lwcam.log")
        uploader = self.read("uploader.log")
        console_output = console.getvalue()

        self.assertIn("普通应用日志", lwcam)
        self.assertIn("GET /api/test 200", lwcam)
        self.assertIn("Uvicorn 服务错误", lwcam)
        self.assertNotIn("上传任务日志", lwcam)
        self.assertNotIn("ingest 警告", lwcam)
        self.assertIn("上传任务日志", uploader)
        self.assertIn("ingest 警告", uploader)
        self.assertNotIn("普通应用日志", uploader)
        self.assertIn("普通应用日志", console_output)
        self.assertIn("上传任务日志", console_output)

    def test_records_utf8_exception_traceback(self):
        configure_logging(self.config())

        try:
            raise RuntimeError("上传失败：连接中断")
        except RuntimeError:
            logging.getLogger("app.services.upload_worker").exception("处理 ZIP 失败")

        uploader = self.read("uploader.log")
        self.assertIn("处理 ZIP 失败", uploader)
        self.assertIn("RuntimeError: 上传失败：连接中断", uploader)
        self.assertIn("Traceback", uploader)

    def test_repeated_configuration_does_not_duplicate_messages(self):
        config = self.config()
        configure_logging(config)
        configure_logging(config)

        logging.getLogger("app.tests.general").info("write-exactly-once")

        self.assertEqual(self.read("lwcam.log").count("write-exactly-once"), 1)

    def test_rotates_and_enforces_backup_limit(self):
        configure_logging(
            self.config(
                log_max_bytes=300,
                log_backup_count=2,
            )
        )

        logger = logging.getLogger("app.tests.rotation")
        for index in range(100):
            logger.info("rotation-line-%03d-%s", index, "x" * 80)
        self.flush_handlers()

        files = sorted((self.root / "logs").glob("lwcam.log*"))
        self.assertTrue((self.root / "logs" / "lwcam.log.1").is_file())
        self.assertLessEqual(len(files), 3)

    def test_invalid_log_directory_prevents_configuration(self):
        invalid = self.root / "not-a-directory"
        invalid.write_text("occupied", encoding="utf-8")

        with self.assertRaises(OSError):
            configure_logging(self.config(log_dir=str(invalid)))

    def test_default_rotation_settings_are_50_mb_and_10_backups(self):
        config = Settings(_env_file=None)

        self.assertEqual(config.log_max_bytes, 52_428_800)
        self.assertEqual(config.log_backup_count, 10)
        self.assertEqual(Path(config.log_dir), Path(__file__).resolve().parents[2] / "logs")


if __name__ == "__main__":
    unittest.main()
