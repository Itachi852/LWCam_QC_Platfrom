"""Replace / Insert-before accept the formats capture actually produces.

Capture output is .jpg and only becomes .tif at export, so the old .tif-only
gate made both actions unusable on every pre-export folder.
"""

import io

import pytest
from PIL import Image

from app.core.errors import BusinessError
from app.routers.qc import (
    UPLOAD_IMAGE_EXTENSIONS,
    replacement_image_name,
    validate_upload_filename,
)


def accepted(name: str) -> bool:
    try:
        validate_upload_filename(name)
        return True
    except BusinessError:
        return False


@pytest.mark.parametrize(
    "name",
    ["page.jpg", "page.jpeg", "page.png", "page.tif", "page.tiff", "PAGE.JPG", "a.TIFF"],
)
def test_accepts_every_format_capture_and_export_produce(name: str) -> None:
    assert accepted(name)


@pytest.mark.parametrize("name", ["page.pdf", "page.gif", "page.txt", "page", "page.jpg.exe"])
def test_still_rejects_non_images(name: str) -> None:
    assert not accepted(name)


def test_path_traversal_is_still_blocked() -> None:
    # safe_filename runs first; widening the extension set must not weaken it.
    for name in ("../page.jpg", "sub/page.jpg", r"sub\page.jpg", ".", ".."):
        assert not accepted(name)


def test_error_message_lists_the_allowed_extensions() -> None:
    with pytest.raises(BusinessError) as caught:
        validate_upload_filename("page.pdf")
    for ext in UPLOAD_IMAGE_EXTENSIONS:
        assert ext in str(caught.value.message)


class TestReplacementName:
    """A replaced page keeps its identity; the extension follows the new bytes."""

    def test_same_extension_keeps_the_name_exactly(self) -> None:
        assert replacement_image_name("SAX04_IMG_1_001.jpg", "anything.jpg") == "SAX04_IMG_1_001.jpg"
        assert replacement_image_name("page.tif", "other.TIF") == "page.tif"

    def test_different_extension_keeps_the_stem(self) -> None:
        # Identity (and therefore page order) is the stem, so it survives; the
        # suffix must not claim .tif for PNG bytes.
        assert replacement_image_name("SAX04_IMG_1_001.jpg", "new.png") == "SAX04_IMG_1_001.png"
        assert replacement_image_name("page.tif", "new.jpg") == "page.jpg"

    def test_jpg_and_jpeg_are_not_treated_as_equal(self) -> None:
        # Distinct extensions on disk, so the filename must reflect what landed.
        assert replacement_image_name("page.jpg", "new.jpeg") == "page.jpeg"


def test_a_renamed_non_image_is_rejected_by_content_check() -> None:
    # The extension is caller-supplied. Prove Pillow rejects bytes that lie,
    # which is what save_upload_to_temp relies on.
    with pytest.raises(Exception):
        Image.open(io.BytesIO(b"not an image at all")).verify()


def test_a_real_image_passes_the_content_check() -> None:
    buffer = io.BytesIO()
    Image.new("RGB", (4, 4), "white").save(buffer, format="PNG")
    buffer.seek(0)
    Image.open(buffer).verify()  # must not raise
