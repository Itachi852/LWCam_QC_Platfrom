-- LWCam migration 004: importing for folder scan; indexing = claimable annotation state

ALTER TYPE task_status ADD VALUE IF NOT EXISTS 'importing';

UPDATE tasks SET status = 'indexing' WHERE status::text = 'pending_claim';

CREATE INDEX IF NOT EXISTS idx_tasks_indexing_unclaimed ON tasks (created_at DESC)
    WHERE status = 'indexing' AND assignee_id IS NULL;
