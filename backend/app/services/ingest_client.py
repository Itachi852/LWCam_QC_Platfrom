from __future__ import annotations

import mimetypes
import time
import uuid
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests
from requests import Response
from requests.auth import HTTPBasicAuth


class IngestError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        stage: str,
        transient: bool = False,
        configuration: bool = False,
        status_code: int | None = None,
    ):
        super().__init__(message)
        self.stage = stage
        self.transient = transient
        self.configuration = configuration
        self.status_code = status_code


@dataclass(frozen=True)
class UploadResult:
    size_mb: float
    speed_mb_s: float
    duration_s: float


def _multipart_stream(
    path: Path,
    *,
    field_name: str = "file",
    filename: str | None = None,
    chunk_size: int = 2 * 1024 * 1024,
) -> tuple[Iterable[bytes], int, str]:
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

    def chunks() -> Iterator[bytes]:
        yield prefix
        with path.open("rb") as source:
            while chunk := source.read(chunk_size):
                yield chunk
        yield suffix

    return chunks(), content_length, boundary


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
        duration = max(time.monotonic() - started, 0.000001)
        size_mb = size / (1024 * 1024)
        return UploadResult(
            size_mb=round(size_mb, 3),
            speed_mb_s=round(size_mb / duration, 3),
            duration_s=max(round(duration, 3), 0.001),
        )

    def confirm_zip_uploaded(self, zip_hash: str, zip_id: str, filename: str) -> None:
        payload = self._request_json(
            "api/file/confirmation",
            stage="confirm",
            data={
                "zip_hash": zip_hash,
                "zip_id": zip_id,
                "zip_filename": filename,
            },
        )
        if payload is True:
            return
        if not isinstance(payload, dict):
            raise IngestError("confirm response is not an object", stage="confirm")
        if payload.get("success") is True or payload.get("result") is True:
            return
        status = payload.get("status")
        if isinstance(status, str) and status.lower() in {"ok", "success", "confirmed"}:
            return
        raise IngestError(
            "confirmation was not explicitly successful",
            stage="confirm",
        )

    def close(self) -> None:
        self.session.close()



