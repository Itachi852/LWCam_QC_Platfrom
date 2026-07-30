"""Prefix translation between LWCAM's Windows paths and container paths.

Getting this wrong serves images from the wrong folder rather than failing, so
the mapping is pinned in both directions plus the pass-through cases.
"""

from pathlib import PurePosixPath

import pytest

from app.core import paths
from app.core.config import settings

WINDOWS_FOLDER = r"E:\LWCam\shared-images\BOX001\FOLDER001"
CONTAINER_FOLDER = "/data/shared-images/BOX001/FOLDER001"


@pytest.fixture
def mounted(monkeypatch):
    """Backend in a Linux container, E:\\LWCam\\shared-images bind-mounted."""
    monkeypatch.setattr(settings, "capture_image_host_path", r"E:\LWCam\shared-images")
    monkeypatch.setattr(settings, "capture_image_container_path", "/data/shared-images")


@pytest.fixture
def native(monkeypatch):
    """Backend on Windows — both prefixes unset."""
    monkeypatch.setattr(settings, "capture_image_host_path", "")
    monkeypatch.setattr(settings, "capture_image_container_path", "")


def test_translates_windows_path_into_the_mount(mounted) -> None:
    assert PurePosixPath(paths.to_local(WINDOWS_FOLDER).as_posix()) == PurePosixPath(CONTAINER_FOLDER)


def test_accepts_forward_slashes_and_drive_case(mounted) -> None:
    # LWCAM writes backslashes, but .env may spell the prefix either way.
    assert paths.to_local("e:/LWCam/shared-images/BOX001").as_posix() == "/data/shared-images/BOX001"


def test_preserves_case_below_the_prefix(mounted) -> None:
    # The prefix is Windows (case-insensitive); everything under it lands on a
    # case-SENSITIVE filesystem and must not be folded.
    assert paths.to_local(r"E:\LWCam\shared-images\MixedCase\Folder_01").as_posix() == (
        "/data/shared-images/MixedCase/Folder_01"
    )


def test_maps_the_mount_root_itself(mounted) -> None:
    assert paths.to_local(r"E:\LWCam\shared-images").as_posix() == "/data/shared-images"


def test_leaves_paths_outside_the_mount_alone(mounted) -> None:
    # Must NOT be silently rewritten — the caller's "directory missing" error is
    # the correct outcome, not a path pointing somewhere unrelated.
    assert paths.to_local(r"D:\Elsewhere\FOLDER001").as_posix().endswith("Elsewhere/FOLDER001")
    # A prefix that only matches as a string, not as a directory boundary.
    assert "data/shared-images" not in paths.to_local(r"E:\LWCam\shared-images-old\X").as_posix()


def test_identity_when_unconfigured(native) -> None:
    assert str(paths.to_local(WINDOWS_FOLDER)) == WINDOWS_FOLDER
    assert paths.to_db(PurePosixPath(CONTAINER_FOLDER)) == CONTAINER_FOLDER


def test_round_trips_back_to_windows_form(mounted) -> None:
    # The value written back must look like one LWCAM/LWIP wrote themselves.
    assert paths.to_db(PurePosixPath(CONTAINER_FOLDER)) == WINDOWS_FOLDER
    assert paths.to_local(paths.to_db(PurePosixPath(CONTAINER_FOLDER))).as_posix() == CONTAINER_FOLDER


def test_to_db_leaves_unmapped_paths_alone(mounted) -> None:
    assert paths.to_db(PurePosixPath("/app/.cache/qc_work/1")) == "/app/.cache/qc_work/1"
