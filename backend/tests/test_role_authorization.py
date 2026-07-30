"""Authorization must consider every role an account holds.

`User.role` reports the highest-precedence role only (super_admin > admin > qc),
which is right for the sidebar and landing page but wrong as a permission check:
a 'qc,admin' reviewer reports 'admin' and was denied every QC endpoint.
"""

import pytest

from app.core.errors import BusinessError
from app.dependencies import require_roles
from app.models.user import User


def user(roles: str) -> User:
    return User(user_id="ronald", password="x", roles=roles, active=True)


def allowed(roles: str, *required: str) -> bool:
    try:
        require_roles(*required)(user(roles))
        return True
    except BusinessError:
        return False


def test_role_set_reports_everything_held() -> None:
    assert user("qc,admin").role_set == {"qc", "admin"}
    assert user("admin,capture").role_set == {"admin", "capture"}
    assert user("  QC , Admin ").role_set == {"qc", "admin"}
    assert user("").role_set == set()


def test_display_role_still_uses_precedence() -> None:
    # Unchanged behaviour — the sidebar reads 'Administrator' for Ronald.
    assert user("qc,admin").role == "admin"
    assert user("qc").role == "qc"
    assert user("super_admin,qc").role == "super_admin"


def test_a_qc_admin_account_reaches_both_areas() -> None:
    # The exact regression: this returned False for the QC gate before the fix.
    assert allowed("qc,admin", "qc")
    assert allowed("qc,admin", "admin", "super_admin")


def test_single_role_accounts_are_unaffected() -> None:
    assert allowed("qc", "qc")
    assert not allowed("qc", "admin", "super_admin")
    assert allowed("admin", "admin", "super_admin")
    assert not allowed("admin", "qc")


def test_a_capture_only_operator_gets_nothing() -> None:
    # LWCAM capture staff have no business in the QC platform.
    assert not allowed("capture", "qc")
    assert not allowed("capture", "admin", "super_admin")


def test_no_roles_is_denied() -> None:
    assert not allowed("", "qc")
    assert not allowed("", "admin", "super_admin")


def test_capture_alongside_qc_does_not_grant_admin() -> None:
    # Preserving unmanaged roles must not widen access.
    assert allowed("qc,capture", "qc")
    assert not allowed("qc,capture", "admin", "super_admin")


@pytest.mark.parametrize("roles", ["QC,ADMIN", "qc|admin", "{qc,admin}", '"qc","admin"'])
def test_tolerates_the_formats_seen_in_this_column(roles: str) -> None:
    # users.roles is written by three apps; the parser has always been lenient.
    assert allowed(roles, "qc")
