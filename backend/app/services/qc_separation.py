from __future__ import annotations

import logging
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from app.services.previews import generate_thumbnail_file


logger = logging.getLogger(__name__)


class SeparationFileError(RuntimeError):
    pass


def child_directory_path(parent: Path, index: int, *, thumbnail: bool = False) -> Path:
    suffix = "_thumbnail_path" if thumbnail else "_path"
    name = parent.name
    if name.endswith(suffix):
        stem = name[: -len(suffix)]
        child_name = f"{stem}_{index:03d}{suffix}"
    else:
        child_name = f"{name}_{index:03d}"
    return parent.with_name(child_name)


@dataclass(frozen=True)
class SeparationGroup:
    index: int
    image_names: tuple[str, ...]
    final_image_dir: Path
    final_thumbnail_dir: Path | None
    temporary_image_dir: Path
    temporary_thumbnail_dir: Path | None


class SeparationFileTransaction:
    """Request-scoped physical split with compensating rollback."""

    def __init__(
        self,
        parent_image_dir: Path,
        parent_thumbnail_dir: Path | None,
        grouped_image_names: list[list[str]],
    ) -> None:
        self.parent_image_dir = parent_image_dir.expanduser().resolve()
        self.parent_thumbnail_dir = (
            parent_thumbnail_dir.expanduser().resolve() if parent_thumbnail_dir else None
        )
        token = uuid4().hex
        self.groups: list[SeparationGroup] = []
        for index, names in enumerate(grouped_image_names, start=1):
            final_image_dir = child_directory_path(self.parent_image_dir, index)
            final_thumbnail_dir = (
                child_directory_path(self.parent_thumbnail_dir, index, thumbnail=True)
                if self.parent_thumbnail_dir
                else None
            )
            self.groups.append(
                SeparationGroup(
                    index=index,
                    image_names=tuple(names),
                    final_image_dir=final_image_dir,
                    final_thumbnail_dir=final_thumbnail_dir,
                    temporary_image_dir=final_image_dir.with_name(
                        f".{final_image_dir.name}.qc_split_{token}.tmp"
                    ),
                    temporary_thumbnail_dir=(
                        final_thumbnail_dir.with_name(
                            f".{final_thumbnail_dir.name}.qc_split_{token}.tmp"
                        )
                        if final_thumbnail_dir
                        else None
                    ),
                )
            )
        self._source_thumbnails: set[str] = set()
        self._applied = False

    def preflight(self) -> None:
        if not self.parent_image_dir.is_dir():
            raise SeparationFileError(f"原图目录不存在: {self.parent_image_dir}")
        if not os.access(self.parent_image_dir, os.W_OK) or not os.access(
            self.parent_image_dir.parent, os.W_OK
        ):
            raise SeparationFileError(f"原图目录不可写: {self.parent_image_dir}")
        if self.parent_thumbnail_dir:
            if not self.parent_thumbnail_dir.is_dir():
                raise SeparationFileError(f"缩略图目录不存在: {self.parent_thumbnail_dir}")
            if not os.access(self.parent_thumbnail_dir, os.W_OK) or not os.access(
                self.parent_thumbnail_dir.parent, os.W_OK
            ):
                raise SeparationFileError(f"缩略图目录不可写: {self.parent_thumbnail_dir}")

        seen: set[str] = set()
        for group in self.groups:
            for target in (
                group.final_image_dir,
                group.final_thumbnail_dir,
                group.temporary_image_dir,
                group.temporary_thumbnail_dir,
            ):
                if target is not None and target.exists():
                    raise SeparationFileError(f"分离目标目录已存在: {target}")
            if not group.image_names:
                raise SeparationFileError("分离后的子Folder不能为空")
            for image_name in group.image_names:
                if Path(image_name).name != image_name or image_name in {"", ".", ".."}:
                    raise SeparationFileError(f"图片文件名无效: {image_name}")
                if image_name in seen:
                    raise SeparationFileError(f"图片被重复分组: {image_name}")
                seen.add(image_name)
                source = self.parent_image_dir / image_name
                if not source.is_file():
                    raise SeparationFileError(f"原图文件不存在: {source}")
                if self.parent_thumbnail_dir:
                    thumbnail = self.parent_thumbnail_dir / image_name
                    if thumbnail.is_file():
                        self._source_thumbnails.add(image_name)

    def apply(self) -> None:
        self.preflight()
        try:
            for group in self.groups:
                group.temporary_image_dir.mkdir()
                if group.temporary_thumbnail_dir:
                    group.temporary_thumbnail_dir.mkdir()

                for image_name in group.image_names:
                    source = self.parent_image_dir / image_name
                    shutil.move(str(source), str(group.temporary_image_dir / image_name))

                    if not group.temporary_thumbnail_dir or not self.parent_thumbnail_dir:
                        continue
                    source_thumbnail = self.parent_thumbnail_dir / image_name
                    target_thumbnail = group.temporary_thumbnail_dir / image_name
                    if image_name in self._source_thumbnails:
                        shutil.move(str(source_thumbnail), str(target_thumbnail))
                    elif (
                        generate_thumbnail_file(
                            group.temporary_image_dir / image_name,
                            target_thumbnail,
                        )
                        is None
                    ):
                        raise SeparationFileError(f"缩略图生成失败: {image_name}")

            for group in self.groups:
                os.replace(group.temporary_image_dir, group.final_image_dir)
                if group.temporary_thumbnail_dir and group.final_thumbnail_dir:
                    os.replace(group.temporary_thumbnail_dir, group.final_thumbnail_dir)
            self._applied = True
        except Exception as error:
            try:
                self.rollback()
            except Exception as rollback_error:
                logger.exception(
                    "QC separation rollback failed after apply error; parent=%s groups=%s",
                    self.parent_image_dir,
                    [group.image_names for group in self.groups],
                )
                raise SeparationFileError(
                    f"分离失败且文件回滚失败: {rollback_error}"
                ) from error
            if isinstance(error, SeparationFileError):
                raise
            raise SeparationFileError(f"物理文件分离失败: {error}") from error

    def rollback(self) -> None:
        errors: list[str] = []
        self.parent_image_dir.mkdir(parents=True, exist_ok=True)
        if self.parent_thumbnail_dir:
            self.parent_thumbnail_dir.mkdir(parents=True, exist_ok=True)

        for group in reversed(self.groups):
            image_dir = (
                group.final_image_dir
                if group.final_image_dir.exists()
                else group.temporary_image_dir
            )
            thumbnail_dir = None
            if group.final_thumbnail_dir and group.final_thumbnail_dir.exists():
                thumbnail_dir = group.final_thumbnail_dir
            elif group.temporary_thumbnail_dir and group.temporary_thumbnail_dir.exists():
                thumbnail_dir = group.temporary_thumbnail_dir

            for image_name in reversed(group.image_names):
                source = image_dir / image_name
                target = self.parent_image_dir / image_name
                if source.is_file():
                    try:
                        if target.exists():
                            raise FileExistsError(f"回滚目标文件已存在: {target}")
                        shutil.move(str(source), str(target))
                    except Exception as error:
                        errors.append(f"{source} -> {target}: {error}")

                if thumbnail_dir is None or self.parent_thumbnail_dir is None:
                    continue
                thumbnail = thumbnail_dir / image_name
                if not thumbnail.is_file():
                    continue
                try:
                    if image_name in self._source_thumbnails:
                        target_thumbnail = self.parent_thumbnail_dir / image_name
                        if target_thumbnail.exists():
                            raise FileExistsError(f"回滚目标缩略图已存在: {target_thumbnail}")
                        shutil.move(str(thumbnail), str(target_thumbnail))
                    else:
                        thumbnail.unlink()
                except Exception as error:
                    errors.append(f"缩略图 {thumbnail}: {error}")

            self._remove_if_empty(image_dir)
            if thumbnail_dir:
                self._remove_if_empty(thumbnail_dir)

        self._applied = False
        if errors:
            raise SeparationFileError("; ".join(errors))

    def cleanup_empty_parent_directories(self) -> None:
        self._remove_if_empty(self.parent_image_dir)
        if self.parent_thumbnail_dir:
            self._remove_if_empty(self.parent_thumbnail_dir)

    @staticmethod
    def _remove_if_empty(path: Path) -> None:
        try:
            path.rmdir()
        except FileNotFoundError:
            return
        except OSError:
            logger.warning("QC separation retained non-empty directory: %s", path)
