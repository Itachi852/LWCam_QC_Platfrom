"""Separation must give each child folder its own `group_id`.

`capture_folders.group_id` is UNIQUE in the live schema, and the split parent is
only soft-deleted, so its row keeps holding the original value. Every child
therefore needs a distinct one, suffixed the same way `folder_name` already is.
"""

from app.routers.qc import child_group_id


def test_splits_the_parent_value_per_child() -> None:
    assert child_group_id("G-2026-07", 1) == "G-2026-07_001"
    assert child_group_id("G-2026-07", 2) == "G-2026-07_002"


def test_children_never_collide_with_each_other_or_the_parent() -> None:
    parent = "G-2026-07"
    children = [child_group_id(parent, i) for i in range(1, 6)]
    assert len(set(children)) == len(children)
    assert parent not in children


def test_matches_the_folder_name_suffix_so_the_two_columns_agree() -> None:
    # apply_separation_commit builds folder_name as f"{name}_{index:03d}" in the
    # same loop; the group_id suffix must use the identical format.
    for index in (1, 9, 10, 100):
        assert child_group_id("G", index).endswith(f"_{index:03d}")


def test_a_parent_without_a_group_id_yields_none() -> None:
    # Not the empty string: '' would collide on the second child, since a plain
    # UNIQUE treats NULLs as distinct but empty strings as equal.
    assert child_group_id(None, 1) is None
    assert child_group_id("", 1) is None
    assert child_group_id("   ", 2) is None


def test_re_separating_a_child_still_produces_unique_values() -> None:
    child = child_group_id("G", 1)
    grandchildren = [child_group_id(child, i) for i in (1, 2)]
    assert grandchildren == ["G_001_001", "G_001_002"]
    assert child not in grandchildren
