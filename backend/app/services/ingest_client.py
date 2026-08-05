from __future__ import annotations

import mimetypes
import logging
import time
import uuid
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests
from requests import Response
from requests.auth import HTTPBasicAuth


logger = logging.getLogger(__name__)


_SENSITIVE_RESPONSE_KEYS = {
    "authorization",
    "cookie",
    "password",
    "secret",
    "token",
}


def _safe_response_payload(value: Any, *, depth: int = 0) -> Any:
    """Return a bounded JSON-safe response summary without common secrets."""
    if depth >= 5:
        return "<truncated>"
    if isinstance(value, dict):
        return {
            str(key): (
                "<redacted>"
                if str(key).casefold() in _SENSITIVE_RESPONSE_KEYS
                else _safe_response_payload(item, depth=depth + 1)
            )
            for key, item in list(value.items())[:50]
        }
    if isinstance(value, (list, tuple)):
        return [_safe_response_payload(item, depth=depth + 1) for item in value[:50]]
    if isinstance(value, str):
        return value[:2000]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return repr(value)[:2000]


class IngestError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        stage: str,
        transient: bool = False,
        configuration: bool = False,
        status_code: int | None = None,
        response_payload: Any = None,
    ):
        super().__init__(message)
        self.stage = stage
        self.transient = transient
        self.configuration = configuration
        self.status_code = status_code
        self.response_payload = response_payload


@dataclass(frozen=True)
class UploadResult:
    size_mb: float
    speed_mb_s: float
    duration_s: float


class _MultipartBody(Iterable[bytes]):
    def __init__(
        self,
        path: Path,
        prefix: bytes,
        suffix: bytes,
        chunk_size: int,
        content_length: int,
    ):
        self.path = path
        self.prefix = prefix
        self.suffix = suffix
        self.chunk_size = chunk_size
        self.content_length = content_length
        self._iterator: Iterator[bytes] | None = None
        self.closed = False

    def __len__(self) -> int:
        return self.content_length

    def __iter__(self) -> Iterator[bytes]:
        if self._iterator is None:
            self._iterator = self._chunks()
        return self._iterator

    def _chunks(self) -> Iterator[bytes]:
        yield self.prefix
        with self.path.open("rb") as source:
            while chunk := source.read(self.chunk_size):
                yield chunk
        yield self.suffix

    def close(self) -> None:
        iterator = self._iterator
        if iterator is not None:
            close = getattr(iterator, "close", None)
            if callable(close):
                close()
        self.closed = True


def _multipart_stream(
    path: Path,
    *,
    field_name: str = "file",
    filename: str | None = None,
    chunk_size: int = 2 * 1024 * 1024,
) -> tuple[_MultipartBody, int, str]:
    boundary = uuid.uuid4().hex
    upload_name = filename or path.name
    mime_type = mimetypes.guess_type(upload_name)[0] or "application/octet-stream"
    prefix = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="{field_name}"; filename="{upload_name}"\r\n'
        f"Content-Type: {mime_type}\r\n\r\n"
    ).encode()
    suffix = f"\r\n--{boundary}--\r\n".encode()
    content_length = len(prefix) + path.stat().st_size + len(suffix)

    body = _MultipartBody(path, prefix, suffix, chunk_size, content_length)
    return body, content_length, boundary


class IngestClient:
    def __init__(
        self,
        *,
        api_base_url: str,
        api_authorization: str,
        hfs_upload_url: str,
        hfs_username: str,
        hfs_password: str,
        connect_timeout: float,
        read_timeout: float,
        session: requests.Session | None = None,
    ):
        self.api_base_url = api_base_url.rstrip("/")
        self.api_authorization = api_authorization.strip()
        self.hfs_upload_url = hfs_upload_url
        self.hfs_auth = HTTPBasicAuth(hfs_username, hfs_password)
        self.timeout = (connect_timeout, read_timeout)
        self.session = session or requests.Session()
        if session is None:
            # Upload endpoints must not silently inherit a desktop/system proxy.
            # Operators can still inject a deliberately configured Session.
            self.session.trust_env = False

    def _api_url(self, path: str) -> str:
        return f"{self.api_base_url}/{path.lstrip('/')}"

    @staticmethod
    def _raise_http_error(response: Response, stage: str) -> None:
        if response.status_code < 400:
            return
        status = response.status_code
        raise IngestError(
            f"{stage} returned HTTP {status}",
            stage=stage,
            transient=status >= 500 or status in {408, 429},
            configuration=status in {401, 403},
            status_code=status,
        )

    def _request(
        self,
        method: str,
        url: str,
        *,
        stage: str,
        authorization: str | None = None,
        auth: HTTPBasicAuth | None = None,
        **kwargs: Any,
    ) -> Response:
        if authorization is not None:
            headers = dict(kwargs.pop("headers", {}) or {})
            headers["Authorization"] = authorization
            kwargs["headers"] = headers
        if auth is not None:
            kwargs["auth"] = auth
        try:
            response = self.session.request(
                method,
                url,
                timeout=self.timeout,
                **kwargs,
            )
        except (requests.exceptions.InvalidURL, requests.exceptions.MissingSchema) as error:
            raise IngestError(
                f"{stage} has an invalid URL",
                stage=stage,
                configuration=True,
            ) from error
        except (requests.Timeout, requests.ConnectionError) as error:
            raise IngestError(
                f"{stage} request failed: {type(error).__name__}",
                stage=stage,
                transient=True,
            ) from error
        except requests.RequestException as error:
            raise IngestError(
                f"{stage} request failed: {type(error).__name__}",
                stage=stage,
            ) from error
        self._raise_http_error(response, stage)
        return response

    def _request_json(self, path: str, *, stage: str, data: dict[str, str]) -> Any:
        response = self._request(
            "POST",
            self._api_url(path),
            stage=stage,
            authorization=self.api_authorization,
            data=data,
        )
        try:
            return response.json()
        except (ValueError, requests.JSONDecodeError) as error:
            raise IngestError(
                f"{stage} returned invalid JSON",
                stage=stage,
            ) from error

    def check_zipfilename_ingested(self, filename: str) -> bool:
        payload = self._request_json(
            "api/stat/check-zip-file-ingested",
            stage="check",
            data={"zip_filename": filename},
        )
        if not isinstance(payload, dict) or not isinstance(payload.get("result"), bool):
            raise IngestError(
                "check response is missing boolean result",
                stage="check",
            )
        return payload["result"]

    def generate_zip_id(self, project_id: str, site_id: str) -> str:
        payload = self._request_json(
            "api/file/generate-zip-id",
            stage="generate",
            data={"site_id": site_id, "project_id": project_id},
        )
        zip_id = payload.get("zip_id") if isinstance(payload, dict) else None
        if not isinstance(zip_id, (str, int)) or not str(zip_id).strip():
            raise IngestError(
                "generate response is missing zip_id",
                stage="generate",
            )
        return str(zip_id).strip()

    def upload_zip(self, path: Path) -> UploadResult:
        if not path.is_file():
            raise IngestError("ZIP file does not exist", stage="upload")
        size = path.stat().st_size
        if size <= 0:
            raise IngestError("ZIP file is empty", stage="upload")
        body, content_length, boundary = _multipart_stream(
            path,
            filename=path.name.removesuffix(".uploading"),
        )
        started = time.monotonic()
        try:
            self._request(
                "POST",
                self.hfs_upload_url,
                stage="upload",
                auth=self.hfs_auth,
                data=body,
                headers={
                    "Content-Type": f"multipart/form-data; boundary={boundary}",
                    "Content-Length": str(content_length),
                },
            )
        finally:
            close = getattr(body, "close", None)
            if callable(close):
                close()
        duration = max(time.monotonic() - started, 0.000001)
        size_mb = size / (1024 * 1024)
        return UploadResult(
            size_mb=round(size_mb, 3),
            speed_mb_s=round(size_mb / duration, 3),
            duration_s=max(round(duration, 3), 0.001),
        )

    def confirm_zip_uploaded(self, zip_hash: str, zip_id: str, filename: str) -> None:
        response = self._request(
            "POST",
            self._api_url("api/file/confirmation"),
            stage="confirm",
            authorization=self.api_authorization,
            data={
                "zip_hash": zip_hash,
                "zip_id": zip_id,
                "zip_filename": filename,
            },
        )
        try:
            payload = response.json()
        except (ValueError, requests.JSONDecodeError) as error:
            raise IngestError(
                "confirm returned invalid JSON",
                stage="confirm",
                status_code=response.status_code,
            ) from error
        safe_payload = _safe_response_payload(payload)
        logger.info(
            "Ingest confirmation response: HTTP %s payload=%r",
            response.status_code,
            safe_payload,
        )
        if payload is True:
            return
        if not isinstance(payload, dict):
            raise IngestError(
                "confirm response is not an object",
                stage="confirm",
                status_code=response.status_code,
                response_payload=safe_payload,
            )
        if (
            payload.get("is_match") is True
            or payload.get("success") is True
            or payload.get("result") is True
        ):
            return
        status = payload.get("status")
        if isinstance(status, str) and status.lower() in {"ok", "success", "confirmed"}:
            return
        raise IngestError(
            "confirmation was not explicitly successful",
            stage="confirm",
            status_code=response.status_code,
            response_payload=safe_payload,
        )

    def close(self) -> None:
        self.session.close()



