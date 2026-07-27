from __future__ import annotations

import json
import os
import shutil
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.config import settings


BACKEND_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_NAME = "manifest.json"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_part(value: str) -> str:
    return "".join(char if char.isalnum() or char in {"-", "_", "."} else "_" for char in value)


def qc_work_root() -> Path:
    root = Path(settings.qc_work_dir).expanduser()
    if not root.is_absolute():
        root = BACKEND_ROOT / root
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def draft_dir(folder_id: int, user_id: str) -> Path:
    path = (qc_work_root() / safe_part(user_id) / str(folder_id)).resolve()
    path.relative_to(qc_work_root())
    return path


def manifest_path(folder_id: int, user_id: str) -> Path:
    return draft_dir(folder_id, user_id) / MANIFEST_NAME


def image_key(image_id: int) -> str:
    return str(int(image_id))


def empty_manifest(folder_id: int, user_id: str) -> dict:
    now = utc_now_iso()
    return {
        "folder_id": folder_id,
        "user_id": user_id,
        "created_at": now,
        "updated_at": now,
        "images": {},
        "metadata": {"dirty": False, "values": {}},
        "order": [],
        "separation_markers": [],
        "next_temp_id": -1,
        "operations": [],
        "undo_stack": [],
        "redo_stack": [],
    }


def normalize_manifest(manifest: dict | None, folder_id: int | None = None, user_id: str | None = None) -> dict | None:
    if manifest is None:
        return None
    if folder_id is not None:
        manifest.setdefault("folder_id", folder_id)
    if user_id is not None:
        manifest.setdefault("user_id", user_id)
    manifest.setdefault("images", {})
    manifest.setdefault("metadata", {"dirty": False, "values": {}})
    manifest.setdefault("order", [])
    manifest.setdefault("separation_markers", [])
    manifest.setdefault("next_temp_id", -1)
    manifest.setdefault("operations", [])
    manifest.setdefault("undo_stack", [])
    manifest.setdefault("redo_stack", [])
    return manifest


def read_manifest(folder_id: int, user_id: str) -> dict | None:
    path = manifest_path(folder_id, user_id)
    if not path.is_file():
        return None
    return normalize_manifest(json.loads(path.read_text(encoding="utf-8")), folder_id, user_id)


def write_manifest(folder_id: int, user_id: str, manifest: dict) -> None:
    directory = draft_dir(folder_id, user_id)
    directory.mkdir(parents=True, exist_ok=True)
    normalize_manifest(manifest, folder_id, user_id)
    manifest["updated_at"] = utc_now_iso()
    path = directory / MANIFEST_NAME
    temp_path = directory / f".{MANIFEST_NAME}.tmp"
    temp_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp_path, path)


def manifest_has_changes(manifest: dict | None) -> bool:
    if not manifest:
        return False
    return bool(
        dirty_image_ids_from_manifest(manifest)
        or metadata_dirty_from_manifest(manifest)
        or manifest.get("separation_markers")
        or any((item or {}).get("status") in {"inserted", "deleted"} for item in manifest.get("images", {}).values())
        or manifest.get("order")
    )


def has_draft(folder_id: int, user_id: str) -> bool:
    return manifest_has_changes(read_manifest(folder_id, user_id))


def _copy_file_into_history(source: str | None, target_dir: Path, key: str) -> str | None:
    if not source:
        return None
    source_path = Path(source)
    if not source_path.is_file():
        return None
    target = target_dir / f"{safe_part(key)}{source_path.suffix}"
    shutil.copy2(source_path, target)
    return str(target.resolve())


def push_history(manifest: dict, folder_id: int, user_id: str) -> None:
    normalize_manifest(manifest, folder_id, user_id)
    history_dir = draft_dir(folder_id, user_id) / "history" / str(len(manifest["undo_stack"]) + 1)
    history_dir.mkdir(parents=True, exist_ok=True)
    snapshot = {
        "images": deepcopy(manifest.get("images", {})),
        "metadata": deepcopy(manifest.get("metadata", {})),
        "order": deepcopy(manifest.get("order", [])),
        "separation_markers": deepcopy(manifest.get("separation_markers", [])),
        "next_temp_id": manifest.get("next_temp_id", -1),
        "files": {},
    }
    for key, item in snapshot["images"].items():
        copied = _copy_file_into_history(item.get("work_path"), history_dir, key)
        if copied:
            snapshot["files"][key] = copied
    manifest["undo_stack"].append(snapshot)
    manifest["redo_stack"] = []


def _restore_snapshot_files(folder_id: int, user_id: str, snapshot: dict) -> None:
    base = draft_dir(folder_id, user_id).resolve()
    images = snapshot.get("images") or {}
    for key, item in images.items():
        work_path_value = item.get("work_path")
        if not work_path_value:
            continue
        work_path = Path(work_path_value).resolve()
        work_path.relative_to(base)
        history_file = snapshot.get("files", {}).get(str(key))
        if history_file and Path(history_file).is_file():
            work_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(history_file, work_path)


def _state_snapshot(manifest: dict) -> dict:
    snapshot = {
        "images": deepcopy(manifest.get("images", {})),
        "metadata": deepcopy(manifest.get("metadata", {})),
        "order": deepcopy(manifest.get("order", [])),
        "separation_markers": deepcopy(manifest.get("separation_markers", [])),
        "next_temp_id": manifest.get("next_temp_id", -1),
        "files": {},
    }
    return snapshot


def undo_manifest(folder_id: int, user_id: str) -> bool:
    manifest = read_manifest(folder_id, user_id)
    if not manifest or not manifest.get("undo_stack"):
        return False
    redo = _state_snapshot(manifest)
    redo_dir = draft_dir(folder_id, user_id) / "history" / f"redo_{len(manifest['redo_stack']) + 1}"
    redo_dir.mkdir(parents=True, exist_ok=True)
    for key, item in redo["images"].items():
        copied = _copy_file_into_history(item.get("work_path"), redo_dir, key)
        if copied:
            redo["files"][key] = copied
    snapshot = manifest["undo_stack"].pop()
    manifest["redo_stack"].append(redo)
    manifest["images"] = deepcopy(snapshot.get("images", {}))
    manifest["metadata"] = deepcopy(snapshot.get("metadata", {}))
    manifest["order"] = deepcopy(snapshot.get("order", []))
    manifest["separation_markers"] = deepcopy(snapshot.get("separation_markers", []))
    manifest["next_temp_id"] = snapshot.get("next_temp_id", -1)
    _restore_snapshot_files(folder_id, user_id, snapshot)
    manifest.setdefault("operations", []).append({"operation": "undo", "at": utc_now_iso()})
    write_manifest(folder_id, user_id, manifest)
    return True


def redo_manifest(folder_id: int, user_id: str) -> bool:
    manifest = read_manifest(folder_id, user_id)
    if not manifest or not manifest.get("redo_stack"):
        return False
    snapshot = manifest["redo_stack"].pop()
    undo = _state_snapshot(manifest)
    undo_dir = draft_dir(folder_id, user_id) / "history" / f"redo_undo_{len(manifest['undo_stack']) + 1}"
    undo_dir.mkdir(parents=True, exist_ok=True)
    for key, item in undo["images"].items():
        copied = _copy_file_into_history(item.get("work_path"), undo_dir, key)
        if copied:
            undo["files"][key] = copied
    manifest["undo_stack"].append(undo)
    manifest["images"] = deepcopy(snapshot.get("images", {}))
    manifest["metadata"] = deepcopy(snapshot.get("metadata", {}))
    manifest["order"] = deepcopy(snapshot.get("order", []))
    manifest["separation_markers"] = deepcopy(snapshot.get("separation_markers", []))
    manifest["next_temp_id"] = snapshot.get("next_temp_id", -1)
    _restore_snapshot_files(folder_id, user_id, snapshot)
    manifest.setdefault("operations", []).append({"operation": "redo", "at": utc_now_iso()})
    write_manifest(folder_id, user_id, manifest)
    return True


def metadata_dirty_from_manifest(manifest: dict | None) -> bool:
    if not manifest:
        return False
    metadata = manifest.get("metadata") or {}
    return bool(metadata.get("dirty"))


def metadata_values_from_manifest(manifest: dict | None) -> dict[str, Any]:
    if not manifest:
        return {}
    metadata = manifest.get("metadata") or {}
    if not metadata.get("dirty"):
        return {}
    values = metadata.get("values")
    return values if isinstance(values, dict) else {}


def dirty_image_ids_from_manifest(manifest: dict | None) -> list[int]:
    if not manifest:
        return []
    result: list[int] = []
    for raw_id, item in manifest.get("images", {}).items():
        if item.get("dirty") or item.get("status") in {"inserted", "deleted", "replaced"}:
            result.append(int(raw_id))
    return sorted(result)


def draft_summary(manifest: dict | None) -> dict[str, Any]:
    return {
        "dirty_image_ids": dirty_image_ids_from_manifest(manifest),
        "metadata_dirty": metadata_dirty_from_manifest(manifest),
        "operations": len((manifest or {}).get("operations", [])),
        "separation_markers": list((manifest or {}).get("separation_markers", [])),
    }


def draft_version(folder_id: int, user_id: str) -> int | None:
    manifest = read_manifest(folder_id, user_id)
    if not manifest:
        return None
    try:
        return int(datetime.fromisoformat(manifest["updated_at"]).timestamp() * 1000)
    except Exception:
        return None


def draft_image_item(manifest: dict | None, image_id: int) -> dict | None:
    if not manifest:
        return None
    item = manifest.get("images", {}).get(image_key(image_id))
    return item if isinstance(item, dict) else None


def draft_image_path(folder_id: int, user_id: str, image_id: int) -> Path | None:
    manifest = read_manifest(folder_id, user_id)
    item = draft_image_item(manifest, image_id)
    if not item or item.get("status") == "deleted":
        return None
    path_value = item.get("work_path")
    if not path_value:
        return None
    path = Path(path_value).resolve()
    try:
        path.relative_to(draft_dir(folder_id, user_id).resolve())
    except ValueError:
        return None
    return path if path.is_file() else None


def ensure_order(manifest: dict, official_ids: list[int]) -> list[int]:
    order = [int(item) for item in manifest.get("order") or []]
    seen = set(order)
    for image_id in official_ids:
        if image_id not in seen:
            order.append(image_id)
    valid_ids = set(official_ids) | {int(raw_id) for raw_id in manifest.get("images", {}) if int(raw_id) < 0}
    order = [image_id for image_id in order if image_id in valid_ids]
    manifest["order"] = order
    return order


def visible_order(manifest: dict | None, official_ids: list[int]) -> list[int]:
    if not manifest:
        return official_ids
    order = ensure_order(manifest, official_ids)
    deleted = {int(raw_id) for raw_id, item in manifest.get("images", {}).items() if item.get("status") == "deleted"}
    return [image_id for image_id in order if image_id not in deleted]


def ensure_work_copy(
    folder_id: int,
    user_id: str,
    image_id: int,
    image_name: str,
    source_path: Path,
    *,
    official_ids: list[int] | None = None,
) -> Path:
    manifest = read_manifest(folder_id, user_id) or empty_manifest(folder_id, user_id)
    if official_ids is not None:
        ensure_order(manifest, official_ids)
    images = manifest.setdefault("images", {})
    key = image_key(image_id)
    item = images.get(key)
    if item and item.get("work_path") and Path(item["work_path"]).is_file():
        return Path(item["work_path"]).resolve()

    images_dir = draft_dir(folder_id, user_id) / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    work_path = (images_dir / f"{image_id}_{safe_part(image_name)}").resolve()
    work_path.relative_to(draft_dir(folder_id, user_id).resolve())
    shutil.copy2(source_path, work_path)
    images[key] = {
        "image_name": image_name,
        "official_path": str(source_path.resolve()),
        "work_path": str(work_path),
        "dirty": False,
        "status": item.get("status", "existing") if item else "existing",
    }
    write_manifest(folder_id, user_id, manifest)
    return work_path


def mark_dirty(folder_id: int, user_id: str, image_id: int, operation: str) -> None:
    manifest = read_manifest(folder_id, user_id) or empty_manifest(folder_id, user_id)
    push_history(manifest, folder_id, user_id)
    item = manifest.setdefault("images", {}).setdefault(image_key(image_id), {})
    item["dirty"] = True
    if item.get("status") == "existing":
        item["status"] = "edited"
    manifest.setdefault("operations", []).append({"image_id": image_id, "operation": operation, "at": utc_now_iso()})
    write_manifest(folder_id, user_id, manifest)


def mark_dirty_no_history(folder_id: int, user_id: str, image_id: int, operation: str) -> None:
    manifest = read_manifest(folder_id, user_id) or empty_manifest(folder_id, user_id)
    item = manifest.setdefault("images", {}).setdefault(image_key(image_id), {})
    item["dirty"] = True
    if item.get("status") == "existing":
        item["status"] = "edited"
    manifest.setdefault("operations", []).append({"image_id": image_id, "operation": operation, "at": utc_now_iso()})
    write_manifest(folder_id, user_id, manifest)


def create_inserted_image(folder_id: int, user_id: str, image_name: str, source_path: Path, before_image_id: int, official_ids: list[int]) -> int:
    manifest = read_manifest(folder_id, user_id) or empty_manifest(folder_id, user_id)
    push_history(manifest, folder_id, user_id)
    order = ensure_order(manifest, official_ids)
    temp_id = int(manifest.get("next_temp_id", -1))
    manifest["next_temp_id"] = temp_id - 1
    images_dir = draft_dir(folder_id, user_id) / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    work_path = (images_dir / f"{temp_id}_{safe_part(image_name)}").resolve()
    shutil.copy2(source_path, work_path)
    manifest["images"][image_key(temp_id)] = {
        "image_name": image_name,
        "official_path": None,
        "work_path": str(work_path),
        "dirty": True,
        "status": "inserted",
    }
    try:
        index = order.index(before_image_id)
    except ValueError:
        index = len(order)
    order.insert(index, temp_id)
    manifest["order"] = order
    manifest["operations"].append({"image_id": temp_id, "operation": "insert_before", "at": utc_now_iso()})
    write_manifest(folder_id, user_id, manifest)
    return temp_id


def replace_image(folder_id: int, user_id: str, image_id: int, image_name: str, source_path: Path, official_ids: list[int]) -> Path:
    manifest = read_manifest(folder_id, user_id) or empty_manifest(folder_id, user_id)
    push_history(manifest, folder_id, user_id)
    ensure_order(manifest, official_ids)
    images_dir = draft_dir(folder_id, user_id) / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    item = manifest.setdefault("images", {}).setdefault(image_key(image_id), {})
    work_path = Path(item.get("work_path") or images_dir / f"{image_id}_{safe_part(image_name)}").resolve()
    shutil.copy2(source_path, work_path)
    item.update({
        "image_name": image_name,
        "work_path": str(work_path),
        "dirty": True,
        "status": "inserted" if image_id < 0 else "replaced",
    })
    manifest["operations"].append({"image_id": image_id, "operation": "replace", "at": utc_now_iso()})
    write_manifest(folder_id, user_id, manifest)
    return work_path


def delete_image(folder_id: int, user_id: str, image_id: int, official_ids: list[int]) -> None:
    manifest = read_manifest(folder_id, user_id) or empty_manifest(folder_id, user_id)
    push_history(manifest, folder_id, user_id)
    order = ensure_order(manifest, official_ids)
    if image_id < 0:
        manifest["images"].pop(image_key(image_id), None)
    else:
        item = manifest.setdefault("images", {}).setdefault(image_key(image_id), {})
        item["dirty"] = True
        item["status"] = "deleted"
    manifest["order"] = [item for item in order if item != image_id]
    manifest["separation_markers"] = [item for item in manifest.get("separation_markers", []) if item != image_id]
    manifest["operations"].append({"image_id": image_id, "operation": "delete", "at": utc_now_iso()})
    write_manifest(folder_id, user_id, manifest)


def set_order(folder_id: int, user_id: str, image_ids: list[int], official_ids: list[int]) -> None:
    manifest = read_manifest(folder_id, user_id) or empty_manifest(folder_id, user_id)
    push_history(manifest, folder_id, user_id)
    ensure_order(manifest, official_ids)
    manifest["order"] = list(image_ids)
    manifest["operations"].append({"image_ids": image_ids, "operation": "reorder", "at": utc_now_iso()})
    write_manifest(folder_id, user_id, manifest)


def set_separation_markers(folder_id: int, user_id: str, first_page_image_ids: list[int], official_ids: list[int]) -> None:
    manifest = read_manifest(folder_id, user_id) or empty_manifest(folder_id, user_id)
    push_history(manifest, folder_id, user_id)
    ensure_order(manifest, official_ids)
    manifest["separation_markers"] = list(dict.fromkeys(first_page_image_ids))
    manifest["operations"].append({"image_ids": first_page_image_ids, "operation": "separation_markers", "at": utc_now_iso()})
    write_manifest(folder_id, user_id, manifest)


def save_metadata_draft(folder_id: int, user_id: str, values: dict[str, Any], operation: str = "metadata") -> None:
    def serialize(value: Any) -> Any:
        if isinstance(value, datetime):
            return value.isoformat()
        return value

    manifest = read_manifest(folder_id, user_id) or empty_manifest(folder_id, user_id)
    push_history(manifest, folder_id, user_id)
    manifest["metadata"] = {
        "dirty": True,
        "values": {key: serialize(value) for key, value in values.items()},
    }
    manifest.setdefault("operations", []).append({"operation": operation, "at": utc_now_iso()})
    write_manifest(folder_id, user_id, manifest)


def restore_original(folder_id: int, user_id: str, image_id: int, official_ids: list[int]) -> None:
    manifest = read_manifest(folder_id, user_id)
    if not manifest:
        return
    push_history(manifest, folder_id, user_id)
    if image_id < 0:
        manifest["images"].pop(image_key(image_id), None)
        manifest["order"] = [item for item in manifest.get("order", []) if item != image_id]
    else:
        manifest["images"].pop(image_key(image_id), None)
        ensure_order(manifest, official_ids)
    manifest["separation_markers"] = [item for item in manifest.get("separation_markers", []) if item != image_id]
    manifest["operations"].append({"image_id": image_id, "operation": "restore_original", "at": utc_now_iso()})
    write_manifest(folder_id, user_id, manifest)


def discard_draft(folder_id: int, user_id: str) -> None:
    path = draft_dir(folder_id, user_id)
    if path.exists():
        shutil.rmtree(path)
