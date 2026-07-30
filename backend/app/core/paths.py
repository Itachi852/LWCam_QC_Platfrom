"""Maps the paths LWCAM stores in `capture_folders` onto paths this process can open.

LWCAM writes an absolute **Windows** path (LWIP's output directory) into
`folder_path`/`thumbnail_path`, and it is the source of truth for those columns —
rewriting them would break LWCAM and LWIP, which read the same values. So the
translation belongs here, at the point of use.

`CAPTURE_IMAGE_HOST_PATH` / `CAPTURE_IMAGE_CONTAINER_PATH` were already declared
in `.env.example` and `docker-compose.yml`, where the host path is bind-mounted
at the container path — but nothing read them. This module is that reader.

Leave both unset (the default) when the backend runs natively on Windows: every
call is then an identity mapping.
"""

from pathlib import Path

from app.core.config import settings


def _prefixes() -> tuple[str, str] | None:
    host = (settings.capture_image_host_path or "").strip()
    container = (settings.capture_image_container_path or "").strip()
    if not host or not container:
        return None
    return host.replace("\\", "/").rstrip("/"), container.replace("\\", "/").rstrip("/")


def to_local(db_value: str) -> Path:
    """`capture_folders.folder_path` as LWCAM wrote it -> a path this process can open.

    A value outside the configured mount is returned unchanged, so the caller's
    existing "directory missing" error surfaces instead of a silently wrong path.
    """
    mapping = _prefixes()
    if mapping is None:
        return Path(db_value).expanduser()
    host, container = mapping
    slashed = db_value.replace("\\", "/")
    # Windows prefix, so match case-insensitively — but slice the ORIGINAL string
    # so the remainder keeps its case for the case-sensitive container filesystem.
    if slashed.lower() == host.lower():
        return Path(container)
    if not slashed.lower().startswith(host.lower() + "/"):
        return Path(db_value).expanduser()
    return Path(container) / slashed[len(host) + 1 :]


def to_db(local: Path) -> str:
    """Reverse of `to_local`, for the one site that writes a new `folder_path`.

    Keeps the host prefix's own separator style so the value LWCAM and LWIP read
    back looks exactly like the ones they write themselves.
    """
    mapping = _prefixes()
    if mapping is None:
        return str(local)
    host, container = mapping
    slashed = str(local).replace("\\", "/")
    if slashed == container:
        remainder = ""
    elif slashed.startswith(container + "/"):
        remainder = slashed[len(container) + 1 :]
    else:
        return str(local)
    original_host = (settings.capture_image_host_path or "").strip()
    if "\\" in original_host:
        base = original_host.replace("/", "\\").rstrip("\\")
        return f"{base}\\{remainder.replace('/', chr(92))}" if remainder else base
    return f"{host}/{remainder}" if remainder else host
