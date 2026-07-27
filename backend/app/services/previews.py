from hashlib import sha256
from pathlib import Path

from PIL import Image, ImageOps

from app.core.config import settings

BACKEND_ROOT = Path(__file__).resolve().parents[2]
PREVIEW_MAX_EDGE = 1600
PREVIEW_QUALITY = 85
PREVIEW_MIME_TYPE = "image/jpeg"
SUPPORTED_PREVIEW_EXTENSIONS = {"jpg", "jpeg", "png", "webp", "bmp", "tif", "tiff"}


def resolve_preview_cache_dir() -> Path:
    cache_dir = Path(settings.preview_cache_dir).expanduser()
    if not cache_dir.is_absolute():
        cache_dir = BACKEND_ROOT / cache_dir
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def preview_cache_path(source_path: Path) -> Path:
    stat = source_path.stat()
    key = sha256(
        f"{source_path.resolve()}|{stat.st_size}|{stat.st_mtime_ns}".encode("utf-8")
    ).hexdigest()
    return resolve_preview_cache_dir() / f"{key}.jpg"


def normalize_preview_frame(source: Image.Image) -> Image.Image:
    frame = source.copy()
    frame = ImageOps.exif_transpose(frame)
    if frame.mode in {"RGBA", "LA"}:
        background = Image.new("RGB", frame.size, "white")
        alpha = frame.getchannel("A") if frame.mode == "RGBA" else frame.getchannel("A")
        background.paste(frame.convert("RGBA"), mask=alpha)
        return background
    if frame.mode != "RGB":
        return frame.convert("RGB")
    return frame


def generate_preview_image(source_path: Path) -> Path | None:
    source_path = source_path.expanduser().resolve()
    if not source_path.is_file():
        return None
    if source_path.suffix.lower().lstrip(".") not in SUPPORTED_PREVIEW_EXTENSIONS:
        return None

    preview_path = preview_cache_path(source_path)
    if preview_path.is_file():
        return preview_path

    with Image.open(source_path) as source:
        if getattr(source, "n_frames", 1) > 1:
            source.seek(0)
        frame = normalize_preview_frame(source)

    frame.thumbnail((PREVIEW_MAX_EDGE, PREVIEW_MAX_EDGE), Image.Resampling.LANCZOS)
    preview_path.parent.mkdir(parents=True, exist_ok=True)
    frame.save(preview_path, format="JPEG", quality=PREVIEW_QUALITY, optimize=True)
    return preview_path


def generate_thumbnail_file(source_path: Path, target_path: Path) -> Path | None:
    source_path = source_path.expanduser().resolve()
    target_path = target_path.expanduser().resolve()
    if not source_path.is_file():
        return None
    if source_path.suffix.lower().lstrip(".") not in SUPPORTED_PREVIEW_EXTENSIONS:
        return None

    with Image.open(source_path) as source:
        if getattr(source, "n_frames", 1) > 1:
            source.seek(0)
        frame = normalize_preview_frame(source)

    frame.thumbnail((PREVIEW_MAX_EDGE, PREVIEW_MAX_EDGE), Image.Resampling.LANCZOS)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    frame.save(target_path, format="JPEG", quality=PREVIEW_QUALITY, optimize=True)
    return target_path


__all__ = [
    "PREVIEW_MAX_EDGE",
    "PREVIEW_MIME_TYPE",
    "generate_preview_image",
    "generate_thumbnail_file",
]
