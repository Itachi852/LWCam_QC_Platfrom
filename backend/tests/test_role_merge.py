"""`users.roles` is shared with LWCAM and LWCamAdmin.

This platform grants only 'admin' and 'qc'. Anything else in the column belongs
to a capture app, and an edit here must not touch it — collapsing 'admin,capture'
to a single value used to lock the operator out of capture entirely.
"""

from app.models.user import ROLE_ADMIN, ROLE_QC, User
from app.routers.admin import merge_roles


def test_writes_lowercase_matching_the_dart_enum_names() -> None:
    # LWCAM's UserRole.fromJson is an exact lowercase match — 'Admin' parses to
    # null there and silently revokes the role.
    assert ROLE_ADMIN == "admin"
    assert ROLE_QC == "qc"


def test_preserves_a_capture_grant() -> None:
    assert merge_roles("admin,capture", ROLE_QC) == "qc,capture"
    assert merge_roles("capture", ROLE_ADMIN) == "admin,capture"


def test_replaces_the_managed_role_without_duplicating_it() -> None:
    assert merge_roles("admin", ROLE_ADMIN) == "admin"
    assert merge_roles("admin,capture", ROLE_ADMIN) == "admin,capture"
    assert merge_roles("qc", ROLE_ADMIN) == "admin"


def test_handles_rows_written_by_earlier_builds() -> None:
    # Legacy capitalised values must be recognised as managed, not preserved as
    # foreign — otherwise an edit yields 'qc,QC'.
    assert merge_roles("QC", ROLE_QC) == "qc"
    assert merge_roles("Admin,capture", ROLE_QC) == "qc,capture"


def test_tolerates_empty_and_messy_input() -> None:
    assert merge_roles(None, ROLE_QC) == "qc"
    assert merge_roles("", ROLE_QC) == "qc"
    assert merge_roles("  admin ,  capture ", ROLE_QC) == "qc,capture"


def test_preserves_an_unknown_future_role() -> None:
    assert merge_roles("exporter", ROLE_QC) == "qc,exporter"


def test_does_not_demote_a_super_admin_row() -> None:
    # This platform refuses to edit SuperAdmin accounts, but if one is ever
    # reached the token must survive rather than be swapped out.
    merged = merge_roles("SuperAdmin", ROLE_ADMIN)
    assert "SuperAdmin" in merged
    user = User(user_id="x", password="x", roles=merged)
    assert user.role == "super_admin"


def test_merged_value_still_reads_back_as_the_intended_role() -> None:
    user = User(user_id="x", password="x", roles=merge_roles("capture", ROLE_QC))
    assert user.role == "qc"
