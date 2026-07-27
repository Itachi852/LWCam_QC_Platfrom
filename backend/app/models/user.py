from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


ROLE_SUPER_ADMIN = "SuperAdmin"
ROLE_ADMIN = "Admin"
ROLE_QC = "QC"


def normalize_role(value: str) -> str:
    normalized = value.strip().lower().replace("-", "_")
    if normalized in {"superadmin", "super_admin"}:
        return "super_admin"
    if normalized == "admin":
        return "admin"
    if normalized == "qc":
        return "qc"
    return normalized


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, server_default=text("nextval('users_id_seq'::regclass)")
    )
    user_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password: Mapped[str] = mapped_column(String(255), nullable=False)
    roles: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    must_change_password: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("clock_timestamp()")
    )
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL", onupdate="CASCADE"))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("clock_timestamp()")
    )
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL", onupdate="CASCADE"))
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    projects = relationship(
        "Project", secondary="user_projects", back_populates="users", lazy="selectin", viewonly=True
    )

    @property
    def role(self) -> str:
        raw_roles = self.roles or ""
        for marker in ("{", "}", "[", "]", '"', "'"):
            raw_roles = raw_roles.replace(marker, "")
        normalized = [
            normalize_role(role)
            for role in raw_roles.replace(";", ",").replace("|", ",").split(",")
            if role.strip()
        ]
        for candidate in ("super_admin", "admin", "qc"):
            if candidate in normalized:
                return candidate
        return normalized[0] if normalized else ""

    @property
    def status(self) -> str:
        return "active" if self.active and not self.is_deleted else "disabled"
