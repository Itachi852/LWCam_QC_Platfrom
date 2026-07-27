-- LWCam migration 003: rename workflow statuses to indexing / qc / rework

ALTER TYPE task_status ADD VALUE IF NOT EXISTS 'indexing';
ALTER TYPE task_status ADD VALUE IF NOT EXISTS 'qc';

UPDATE tasks SET status = 'qc' WHERE status::text = 'pending_index_qc';

DROP INDEX IF EXISTS idx_tasks_pending_index_qc;
CREATE INDEX IF NOT EXISTS idx_tasks_qc ON tasks (created_at DESC)
    WHERE status = 'qc';
