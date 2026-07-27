# Python QC Outbox / PgSyncSink Implementation Plan

## Summary

Do not modify the Dart reference files under `docs/ExternalResources`. Implement the same outbox/sink pattern in the current FastAPI/Python project.

QC final writes for `Folder passed`, `image rejected`, and later recapture completion should first be written transactionally to a local SQLite mirror/outbox. A Python `PgSyncSink` then drains those outbox rows to PostgreSQL using the same natural-key resolution pattern as the reference `capture_folder_processing` entity.

## Key Changes

- Add a local SQLite store, default path: `backend/.local/qc_outbox.sqlite3`.
- Allow override via env var: `QC_OUTBOX_DB_PATH`.
- Add SQLite table `qc_folder_mirror`:
  - `project_key`
  - `box_name`
  - `renamed_from`
  - `folder_seq`
  - `qc_status`
  - `is_deskewed`
  - `is_cropped`
  - `is_created_thumbnail`
  - `updated_at`
- Add SQLite table `sync_outbox`:
  - `id`
  - `entity`
  - `entity_key`
  - `op`
  - `payload_json`
  - `attempts`
  - `last_error`
  - `next_attempt_at`
  - `created_at`
  - `updated_at`

## Outbox Entities

- `qc_verdict`
  - PASS syncs PostgreSQL `capture_folders.qc_status='PASS'` and releases the QC lock.
  - REWORK syncs PostgreSQL `capture_folders.qc_status='REWORK'`, releases the QC lock, and resets `is_deskewed`, `is_cropped`, `is_created_thumbnail` to `false`.
- `rework_log`
  - REJECT inserts `rework_logs` rows with `rework_status='OPEN'`.
  - Recapture completion inserts `rework_logs` rows with `rework_status='CLOSED'`.
  - Duplicate rows are allowed. Business logic should use latest `created_at`.

## Natural-Key Resolution

Use the same resolution pattern as the reference `capture_folder_processing` sink case:

1. `project_key -> projects.id`
2. `project_id + box_name/renamed_from -> capture_boxes.box_id`
3. `box_id + folder_seq -> capture_folders.id`
4. `folder_id + image_name -> capture_images.id`

Required payload fields:

- `qc_verdict`: `project_key`, `project_id`, `box_name`, `renamed_from`, `folder_seq`, `qc_status`, `reviewer_user_id`, `comment`, `verdict_at`
- `rework_log`: `project_key`, `project_id`, `box_name`, `renamed_from`, `folder_seq`, `image_name`, `rework_status`, `rework_comments`, `rework_type`, `created_at`

## Python Modules

- `app/services/qc_outbox_db.py`
  - Initialize SQLite schema.
  - Provide transactional local mirror updates.
  - Enqueue outbox rows.
  - Ack rows after successful sink apply.
  - Apply retry/backoff metadata after failures.
- `app/services/pg_sync_sink.py`
  - Python sink using SQLAlchemy sessions against the existing PostgreSQL database.
  - Implement `qc_verdict` and `rework_log` cases.
  - Reuse helper methods for project, box, folder, and image resolution.
- `app/services/qc_write_path.py`
  - Expose:
    - `enqueue_pass_verdict(...)`
    - `enqueue_reject_verdict(...)`
    - `enqueue_rework_closed(...)`
  - Hide payload construction from the router.

## Router Behavior

- Update `backend/app/routers/qc.py`.
- `approve_task` keeps current validation, draft commit, and image existence checks.
- After validation succeeds:
  - Do not directly update PostgreSQL `folder.qc_status`.
  - Write local SQLite `qc_verdict PASS`.
  - Best-effort trigger one drain.
- `reject_task` keeps current reject reason and image ownership validation.
- After validation succeeds:
  - Write local SQLite `qc_verdict REWORK`.
  - Write one `rework_log OPEN` outbox row per rejected image.
  - Best-effort trigger one drain.

For UI consistency while offline:

- API list/detail reads PostgreSQL as today, then overlays pending local SQLite mirror state.
- A folder locally marked PASS or REWORK should not remain visible in pending/my-task lists even if PostgreSQL has not synced yet.
- If drain succeeds, ack the outbox rows.
- If drain fails, API still returns success and outbox remains pending for retry.

## Sync Behavior

- Drain order: `qc_verdict` before `rework_log`.
- Each outbox row applies inside a PostgreSQL transaction.
- If PostgreSQL is unreachable or target folder/image cannot be resolved:
  - Increment `attempts`.
  - Store `last_error`.
  - Set exponential backoff with a 15-minute max delay.
  - Keep the outbox row.
- Do not auto-drop unresolved `qc_verdict` or `rework_log` rows; preserve QC decisions and rework audit records.

## Test Plan

- SQLite outbox tests:
  - PASS writes `qc_folder_mirror.qc_status='PASS'` and one `sync_outbox(qc_verdict)` row in the same transaction.
  - REJECT writes `qc_status='REWORK'`, resets the three processing flags to false, and creates one `rework_log OPEN` row per rejected image.
  - Repeated REJECT creates additional rework log outbox rows.
- PgSyncSink tests:
  - `qc_verdict PASS` updates only `qc_status` and lock fields.
  - `qc_verdict REWORK` updates `qc_status`, lock fields, and resets the three processing flags.
  - `rework_log OPEN/CLOSED` resolves image by `image_name` and inserts into `rework_logs`.
- API tests:
  - Approve/reject returns success when sink fails, with outbox rows retained.
  - Pending/my-task lists hide locally completed/reworked folders via SQLite overlay.
  - Successful drain removes/acks outbox rows.

## Assumptions

- Use local SQLite for the Python outbox.
- Do not modify Dart reference files.
- Do not add or change PostgreSQL business table structure.
- Current Python backend keeps PostgreSQL as the main read source.
- SQLite stores only QC write-path mirror/outbox state and UI overlay state.
- `rework_logs` may contain duplicates; latest `created_at` is authoritative.
