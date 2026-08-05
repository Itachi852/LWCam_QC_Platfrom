from __future__ import annotations

import hashlib
import json
import logging
import os
import queue
import re
import shutil
import threading
import time
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import mysql.connector
from sqlalchemy import select
from sqlalchemy.orm import joinedload, lazyload
from watchdog.events import FileMovedEvent, FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from app.core.config import Settings, settings
from app.db.session import SessionLocal
from app.models.capture import CaptureBox, CaptureFolder
from app.services.ingest_client import IngestClient, IngestError, UploadResult

logger = logging.getLogger(__name__)
SAFE_GROUP_ID = re.compile(r"^[A-Za-z0-9_-]+$")


class UploadConfigurationError(RuntimeError):
    pass


class UploadStopped(RuntimeError):
    pass


class UploadZipEventHandler(FileSystemEventHandler):
    """Translate top-level final ZIP events into lightweight queue notifications."""

    def __init__(self, root: Path, enqueue: Callable[[Path], bool]):
        super().__init__()
        self.root = root.resolve()
        self.enqueue = enqueue

    def _notify(self, raw_path: str | bytes) -> None:
        path = Path(os.fsdecode(raw_path)).resolve()
        if path.parent != self.root:
            return
        if path.suffix.lower() != ".zip" or not SAFE_GROUP_ID.fullmatch(path.stem):
            return
        self.enqueue(path)

    def on_created(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self._notify(event.src_path)

    def on_moved(self, event: FileMovedEvent) -> None:
        if not event.is_directory:
            self._notify(event.dest_path)


@dataclass(frozen=True)
class UploadRuntimeConfig:
    output_dir: Path
    success_dir: Path
    failed_dir: Path
    duplicates_dir: Path
    report_dir: Path


@dataclass(frozen=True)
class UploadCandidate:
    folder_id: int
    group_id: str
    project_id: str
    site_id: str
    region: str
    title: str


def utc_now() -> datetime:
    return datetime.now(UTC)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(2 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def count_zip_images(path: Path) -> int:
    image_extensions = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp"}
    with zipfile.ZipFile(path) as archive:
        return sum(
            1
            for name in archive.namelist()
            if not name.endswith("/") and Path(name).suffix.lower() in image_extensions
        )


def _required_text(value: str, name: str) -> str:
    result = value.strip()
    if not result:
        raise UploadConfigurationError(f"{name} is required when upload is enabled")
    return result


def _valid_http_url(value: str, name: str) -> str:
    result = _required_text(value, name)
    parsed = urlsplit(result)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise UploadConfigurationError(f"{name} must be an absolute HTTP(S) URL")
    return result


def runtime_config(config: Settings) -> UploadRuntimeConfig:
    _valid_http_url(config.ingest_api_base_url, "INGEST_API_BASE_URL")
    _required_text(config.ingest_api_authorization, "INGEST_API_AUTHORIZATION")
    _valid_http_url(config.hfs_upload_url, "HFS_UPLOAD_URL")
    _required_text(config.hfs_username, "HFS_USERNAME")
    _required_text(config.hfs_password, "HFS_PASSWORD")
    _required_text(config.ingest_db_host, "INGEST_DB_HOST")
    _required_text(config.ingest_db_name, "INGEST_DB_NAME")
    _required_text(config.ingest_db_user, "INGEST_DB_USER")
    _required_text(config.ingest_db_password, "INGEST_DB_PASSWORD")

    output_dir = Path(_required_text(config.export_output_dir, "EXPORT_OUTPUT_DIR"))
    if not output_dir.is_dir():
        raise UploadConfigurationError(f"EXPORT_OUTPUT_DIR does not exist: {output_dir}")

    result = UploadRuntimeConfig(
        output_dir=output_dir,
        success_dir=Path(_required_text(config.upload_success_dir, "UPLOAD_SUCCESS_DIR")),
        failed_dir=Path(_required_text(config.upload_failed_dir, "UPLOAD_FAILED_DIR")),
        duplicates_dir=Path(
            _required_text(config.upload_duplicates_dir, "UPLOAD_DUPLICATES_DIR")
        ),
        report_dir=Path(_required_text(config.upload_report_dir, "UPLOAD_REPORT_DIR")),
    )
    for directory in (
        result.success_dir,
        result.failed_dir,
        result.duplicates_dir,
        result.report_dir,
    ):
        directory.mkdir(parents=True, exist_ok=True)
    return result


def candidate_from_folder(folder: CaptureFolder) -> UploadCandidate | None:
    project = folder.box.project if folder.box else None
    if project is None or project.is_deleted:
        raise UploadConfigurationError(f"folder {folder.id} has no active project")
    template = project.template if isinstance(project.template, dict) else {}
    ingest = template.get("ingest")
    if not isinstance(ingest, dict):
        raise UploadConfigurationError(
            f"project {project.project_id} is missing template.ingest"
        )
    enabled = ingest.get("enabled", True)
    if enabled is False:
        return None
    if enabled is not True:
        raise UploadConfigurationError(
            f"project {project.project_id} ingest.enabled must be a boolean"
        )
    group_id = str(folder.group_id or "").strip()
    if not SAFE_GROUP_ID.fullmatch(group_id):
        raise UploadConfigurationError(
            f"folder {folder.id} has an invalid group_id"
        )
    project_id = str(ingest.get("project_id") or project.project_id or "").strip()
    site_id = str(ingest.get("site_id") or "").strip()
    region = str(ingest.get("region") or "").strip()
    title = str(
        ingest.get("title") or folder.title or project.project_name or ""
    ).strip()
    missing = [
        name
        for name, value in (
            ("project_id", project_id),
            ("site_id", site_id),
            ("region", region),
            ("title", title),
        )
        if not value
    ]
    if missing:
        raise UploadConfigurationError(
            f"project {project.project_id} ingest config is missing: {', '.join(missing)}"
        )
    return UploadCandidate(
        folder_id=folder.id,
        group_id=group_id,
        project_id=project_id,
        site_id=site_id,
        region=region,
        title=title,
    )


class IngestSummaryWriter:
    def __init__(self, config: Settings):
        self.config = config

    def upsert(
        self,
        candidate: UploadCandidate,
        *,
        image_count: int,
        zip_size_mb: float,
        result: UploadResult | None,
    ) -> None:
        uploaded_at = utc_now()
        connection = mysql.connector.connect(
            host=self.config.ingest_db_host,
            port=self.config.ingest_db_port,
            database=self.config.ingest_db_name,
            user=self.config.ingest_db_user,
            password=self.config.ingest_db_password,
            connection_timeout=max(
                1, int(round(self.config.upload_connect_timeout_seconds))
            ),
        )
        try:
            cursor = connection.cursor()
            try:
                cursor.execute(
                    """
                    INSERT INTO ingest_summary
                      (capture_id, title, image_count, zip_size_mb,
                       upload_speed_mb_s, upload_duration_s, upload_date, upload_time)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                      title = VALUES(title),
                      image_count = VALUES(image_count),
                      zip_size_mb = VALUES(zip_size_mb),
                      upload_speed_mb_s =
                        COALESCE(VALUES(upload_speed_mb_s), upload_speed_mb_s),
                      upload_duration_s =
                        COALESCE(VALUES(upload_duration_s), upload_duration_s),
                      upload_date = VALUES(upload_date),
                      upload_time = VALUES(upload_time),
                      updated_at = CURRENT_TIMESTAMP
                    """,
                    (
                        candidate.group_id,
                        candidate.title,
                        image_count,
                        round(zip_size_mb, 3),
                        result.speed_mb_s if result else None,
                        result.duration_s if result else None,
                        uploaded_at.date(),
                        uploaded_at.time().replace(tzinfo=None),
                    ),
                )
                connection.commit()
            finally:
                cursor.close()
        finally:
            connection.close()


class UploadWorker:
    def __init__(
        self,
        config: Settings,
        *,
        session_factory: Callable[..., Any] = SessionLocal,
        client: IngestClient | None = None,
        summary_writer: IngestSummaryWriter | None = None,
        observer_factory: Callable[[], Any] = Observer,
    ):
        self.settings = config
        self.session_factory = session_factory
        self.client = client
        self.summary_writer = summary_writer
        self.observer_factory = observer_factory
        self._runtime: UploadRuntimeConfig | None = None
        self._thread: threading.Thread | None = None
        self._observer: Any | None = None
        self._queue: queue.Queue[Path | None] = queue.Queue()
        self._queued: set[str] = set()
        self._queue_lock = threading.Lock()
        self._stop = threading.Event()
        self._start_lock = threading.Lock()

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> bool:
        if not self.settings.upload_enabled:
            logger.info("Upload worker is disabled (UPLOAD_ENABLED=false)")
            return False
        with self._start_lock:
            if self.is_running:
                return True
            try:
                self._runtime = runtime_config(self.settings)
                self.client = self.client or IngestClient(
                    api_base_url=self.settings.ingest_api_base_url,
                    api_authorization=self.settings.ingest_api_authorization,
                    hfs_upload_url=self.settings.hfs_upload_url,
                    hfs_username=self.settings.hfs_username,
                    hfs_password=self.settings.hfs_password,
                    connect_timeout=self.settings.upload_connect_timeout_seconds,
                    read_timeout=self.settings.upload_read_timeout_seconds,
                )
                self.summary_writer = self.summary_writer or IngestSummaryWriter(
                    self.settings
                )
                self._recover_uploading_files()
            except Exception:
                logger.exception("Upload worker configuration is invalid; worker not started")
                return False
            self._stop.clear()
            self._queue = queue.Queue()
            with self._queue_lock:
                self._queued.clear()
            self._thread = threading.Thread(
                target=self._run,
                name="lwcam-upload-worker",
                daemon=True,
            )
            self._thread.start()
            self._start_observer()
            self._scan_export_folder()
            logger.info("Upload worker started with watchdog and folder reconciliation")
            return True

    def stop(self) -> None:
        observer = self._observer
        self._observer = None
        if observer is not None:
            try:
                observer.stop()
                observer.join(timeout=self.settings.upload_stop_timeout_seconds)
                if observer.is_alive():
                    logger.warning("Upload watchdog did not stop before timeout")
            except Exception:
                logger.exception("Could not stop upload watchdog cleanly")
        self._stop.set()
        self._queue.put(None)
        thread = self._thread
        if thread is not None:
            thread.join(timeout=self.settings.upload_stop_timeout_seconds)
            if thread.is_alive():
                logger.warning("Upload worker did not stop before timeout")
            elif self.client is not None:
                close = getattr(self.client, "close", None)
                if callable(close):
                    close()
        self._thread = None
        with self._queue_lock:
            self._queued.clear()

    def _run(self) -> None:
        next_reconcile = time.monotonic() + self.settings.upload_reconcile_seconds
        while not self._stop.is_set():
            now = time.monotonic()
            if now >= next_reconcile:
                self._reconcile()
                next_reconcile = time.monotonic() + self.settings.upload_reconcile_seconds
            timeout = max(0.0, next_reconcile - time.monotonic())
            try:
                path = self._queue.get(timeout=timeout)
            except queue.Empty:
                continue
            if path is None:
                self._queue.task_done()
                break
            key = self._queue_key(path)
            try:
                if not self._stop.is_set():
                    self._handle_path(path)
            except UploadConfigurationError:
                logger.exception("Upload worker stopped because of a configuration error")
                self._stop.set()
                if self._observer is not None:
                    self._observer.stop()
                break
            except Exception:
                logger.exception("Unexpected upload worker error")
            finally:
                with self._queue_lock:
                    self._queued.discard(key)
                self._queue.task_done()

    def _start_observer(self) -> None:
        assert self._runtime is not None
        observer = None
        try:
            observer = self.observer_factory()
            handler = UploadZipEventHandler(
                self._runtime.output_dir,
                self._enqueue_path,
            )
            observer.schedule(
                handler,
                str(self._runtime.output_dir),
                recursive=False,
            )
            observer.start()
            self._observer = observer
            logger.info("Watching export directory: %s", self._runtime.output_dir)
        except Exception:
            self._observer = None
            if observer is not None:
                try:
                    observer.stop()
                    observer.join(timeout=self.settings.upload_stop_timeout_seconds)
                except Exception:
                    logger.debug("Could not clean up failed watchdog observer", exc_info=True)
            logger.exception(
                "Upload watchdog could not start; continuing with periodic reconciliation"
            )

    @staticmethod
    def _queue_key(path: Path) -> str:
        return str(path).casefold()

    def _enqueue_path(self, path: Path) -> bool:
        if not self.settings.upload_enabled or self._runtime is None:
            return False
        resolved = path.resolve()
        if resolved.parent != self._runtime.output_dir.resolve():
            return False
        if resolved.suffix.lower() != ".zip":
            return False
        if not SAFE_GROUP_ID.fullmatch(resolved.stem):
            return False
        key = self._queue_key(resolved)
        with self._queue_lock:
            if key in self._queued:
                return False
            self._queued.add(key)
        self._queue.put(resolved)
        return True

    def _scan_export_folder(self) -> int:
        if not self.settings.upload_enabled or self._runtime is None:
            return 0
        queued = 0
        try:
            for path in self._runtime.output_dir.iterdir():
                if path.is_file() and self._enqueue_path(path):
                    queued += 1
        except OSError:
            logger.exception("Could not scan export directory")
        return queued

    def _reconcile(self) -> None:
        if not self.settings.upload_enabled:
            return
        self._recover_uploading_files()
        queued = self._scan_export_folder()
        logger.debug("Upload reconciliation queued %s ZIP file(s)", queued)

    def _load_candidate_state(
        self,
        group_id: str,
    ) -> tuple[str, UploadCandidate | None]:
        with self.session_factory() as db:
            folder = db.scalar(
                select(CaptureFolder)
                .options(
                    joinedload(CaptureFolder.box).joinedload(CaptureBox.project),
                    lazyload(CaptureFolder.images),
                )
                .where(CaptureFolder.group_id == group_id)
            )
        if folder is None:
            return "wait", None
        if folder.is_deleted or folder.is_ingested:
            return "skip", None
        if not folder.is_exported:
            return "wait", None
        try:
            candidate = candidate_from_folder(folder)
        except UploadConfigurationError as error:
            logger.error("%s", error)
            self._write_error(
                group_id,
                stage="project_config",
                error=error,
                attempts=0,
            )
            return "skip", None
        if candidate is None:
            return "skip", None
        return "ready", candidate

    def _wait_for_candidate(self, group_id: str) -> UploadCandidate | None:
        deadline = time.monotonic() + self.settings.upload_gate_max_wait_seconds
        while not self._stop.is_set():
            state, candidate = self._load_candidate_state(group_id)
            if state == "ready":
                return candidate
            if state == "skip":
                return None
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                logger.info(
                    "Upload gate was not ready for %s; leaving ZIP for reconciliation",
                    group_id,
                )
                return None
            if self._stop.wait(
                min(self.settings.upload_gate_retry_seconds, remaining)
            ):
                return None
        return None

    def _handle_path(self, path: Path) -> None:
        if not path.is_file():
            return
        candidate = self._wait_for_candidate(path.stem)
        if candidate is not None:
            self._process(candidate)

    def _process(self, candidate: UploadCandidate) -> None:
        assert self._runtime is not None
        assert self.client is not None
        assert self.summary_writer is not None
        source = self._runtime.output_dir / f"{candidate.group_id}.zip"
        claimed = source.with_name(f"{source.name}.uploading")
        if not source.is_file():
            return
        first = source.stat()
        if first.st_size <= 0:
            self._fail_file(
                source,
                candidate.group_id,
                stage="validate",
                error=RuntimeError("ZIP file is empty"),
                attempts=0,
            )
            return
        if self.settings.upload_stable_seconds:
            if self._stop.wait(self.settings.upload_stable_seconds):
                return
            second = source.stat()
            if (first.st_size, first.st_mtime_ns) != (
                second.st_size,
                second.st_mtime_ns,
            ):
                return
        try:
            source.rename(claimed)
        except (FileNotFoundError, FileExistsError):
            return

        stage = "gate"
        remote_confirmed = False
        upload_result: UploadResult | None = None
        attempts = 0
        try:
            if not self._folder_still_eligible(candidate):
                self._restore_claim(claimed, source)
                return
            stage = "check"
            already_ingested, used = self._retry(
                lambda: self.client.check_zipfilename_ingested(source.name)
            )
            attempts += used
            if not already_ingested:
                stage = "generate"
                zip_id, used = self._retry(
                    lambda: self.client.generate_zip_id(
                        candidate.project_id, candidate.site_id
                    )
                )
                attempts += used
                stage = "upload"
                upload_result, used = self._retry(
                    lambda: self.client.upload_zip(claimed)
                )
                attempts += used
                stage = "confirm"
                zip_hash = sha256_file(claimed)
                _, used = self._retry(
                    lambda: self.client.confirm_zip_uploaded(
                        zip_hash, zip_id, source.name
                    )
                )
                attempts += used
                remote_confirmed = True

            stage = "summary"
            image_count = count_zip_images(claimed)
            zip_size_mb = claimed.stat().st_size / (1024 * 1024)
            self.summary_writer.upsert(
                candidate,
                image_count=image_count,
                zip_size_mb=zip_size_mb,
                result=upload_result,
            )
            stage = "writeback"
            self._mark_ingested(candidate)
            destination = (
                self._runtime.duplicates_dir if already_ingested else self._runtime.success_dir
            )
            stage = "archive"
            self._move_without_overwrite(claimed, destination / source.name)
            self._delete_report(candidate.group_id)
            logger.info("Upload completed for %s", source.name)
        except UploadStopped:
            self._restore_claim(claimed, source)
        except IngestError as error:
            attempts = max(attempts, 1)
            self._write_error(
                candidate.group_id,
                stage=error.stage or stage,
                error=error,
                attempts=attempts,
            )
            if error.configuration:
                self._restore_claim(claimed, source)
                raise UploadConfigurationError(str(error)) from error
            if stage == "confirm" and error.transient:
                self._restore_claim(claimed, source)
            else:
                self._move_failed_claim(claimed, source.name)
        except Exception as error:
            self._write_error(
                candidate.group_id,
                stage=stage,
                error=error,
                attempts=max(attempts, 1),
            )
            if stage == "archive":
                # DB state is already committed. Leave the claim in place;
                # the next recovery pass will archive it without re-uploading.
                pass
            elif remote_confirmed or stage in {"summary", "writeback"}:
                self._restore_claim(claimed, source)
            else:
                self._move_failed_claim(claimed, source.name)

    def _retry(self, operation: Callable[[], Any]) -> tuple[Any, int]:
        last_error: IngestError | None = None
        for attempt in range(1, self.settings.upload_max_retries + 1):
            if self._stop.is_set():
                raise UploadStopped
            try:
                return operation(), attempt
            except IngestError as error:
                if error.configuration or not error.transient:
                    raise
                last_error = error
                if attempt < self.settings.upload_max_retries:
                    if self._stop.wait(min(2 ** (attempt - 1), 60)):
                        raise UploadStopped from error
        assert last_error is not None
        raise last_error

    def _folder_still_eligible(self, candidate: UploadCandidate) -> bool:
        with self.session_factory() as db:
            folder = db.get(CaptureFolder, candidate.folder_id)
            return bool(
                folder
                and not folder.is_deleted
                and folder.is_exported
                and not folder.is_ingested
                and folder.group_id == candidate.group_id
            )

    def _mark_ingested(self, candidate: UploadCandidate) -> None:
        with self.session_factory() as db:
            folder = db.scalar(
                select(CaptureFolder)
                .options(lazyload("*"))
                .where(CaptureFolder.id == candidate.folder_id)
                .with_for_update(of=CaptureFolder)
            )
            if folder is None or folder.is_deleted:
                raise RuntimeError("folder disappeared before ingest write-back")
            if folder.group_id != candidate.group_id or not folder.is_exported:
                raise RuntimeError("folder changed before ingest write-back")
            folder.is_ingested = True
            folder.ingested_time = utc_now()
            db.commit()

    def _recover_uploading_files(self) -> None:
        assert self._runtime is not None
        for claimed in self._runtime.output_dir.glob("*.zip.uploading"):
            group_id = claimed.name[: -len(".zip.uploading")]
            target = self._runtime.output_dir / f"{group_id}.zip"
            with self.session_factory() as db:
                folder = db.scalar(
                    select(CaptureFolder)
                    .options(lazyload("*"))
                    .where(CaptureFolder.group_id == group_id)
                )
                ingested = bool(folder and folder.is_ingested)
            try:
                if ingested:
                    self._move_without_overwrite(
                        claimed, self._runtime.success_dir / target.name
                    )
                    self._delete_report(group_id)
                else:
                    self._restore_claim(claimed, target)
            except OSError:
                logger.exception("Could not recover interrupted upload %s", claimed.name)

    @staticmethod
    def _move_without_overwrite(source: Path, destination: Path) -> None:
        if destination.exists():
            raise FileExistsError(f"destination already exists: {destination}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(destination))

    def _restore_claim(self, claimed: Path, source: Path) -> None:
        if not claimed.exists():
            return
        if source.exists():
            logger.error("Cannot restore %s because %s already exists", claimed, source)
            return
        claimed.rename(source)

    def _move_failed_claim(self, claimed: Path, filename: str) -> None:
        assert self._runtime is not None
        if not claimed.exists():
            return
        try:
            self._move_without_overwrite(claimed, self._runtime.failed_dir / filename)
        except OSError:
            logger.exception("Could not move failed upload %s", filename)

    def _fail_file(
        self,
        source: Path,
        group_id: str,
        *,
        stage: str,
        error: Exception,
        attempts: int,
    ) -> None:
        self._write_error(
            group_id,
            stage=stage,
            error=error,
            attempts=attempts,
        )
        assert self._runtime is not None
        try:
            self._move_without_overwrite(source, self._runtime.failed_dir / source.name)
        except OSError:
            logger.exception("Could not move invalid ZIP %s", source.name)

    def _sanitize(self, message: str) -> str:
        result = message
        for secret in (
            self.settings.ingest_api_authorization,
            self.settings.ingest_api_authorization.partition(" ")[2],
            self.settings.hfs_password,
            self.settings.ingest_db_password,
        ):
            if secret:
                result = result.replace(secret, "***")
        return result

    def _write_error(
        self,
        group_id: str,
        *,
        stage: str,
        error: Exception,
        attempts: int,
    ) -> None:
        if self._runtime is None:
            return
        path = self._runtime.report_dir / f"{group_id}.error.json"
        temporary = path.with_suffix(f"{path.suffix}.tmp")
        payload = {
            "groupId": group_id,
            "stage": stage,
            "attempts": attempts,
            "timestamp": utc_now().isoformat(),
            "errorType": type(error).__name__,
            "error": self._sanitize(str(error)),
            "httpStatus": getattr(error, "status_code", None),
        }
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(path)

    def _delete_report(self, group_id: str) -> None:
        assert self._runtime is not None
        (self._runtime.report_dir / f"{group_id}.error.json").unlink(missing_ok=True)


upload_worker = UploadWorker(settings)


__all__ = [
    "IngestSummaryWriter",
    "UploadCandidate",
    "UploadConfigurationError",
    "UploadRuntimeConfig",
    "UploadStopped",
    "UploadWorker",
    "UploadZipEventHandler",
    "candidate_from_folder",
    "count_zip_images",
    "runtime_config",
    "sha256_file",
    "upload_worker",
]
