-- LWCam migration 005: workflow stages for annotation lifecycle

CREATE TABLE IF NOT EXISTS workflow (
    id          SMALLSERIAL     PRIMARY KEY,
    code        VARCHAR(32)     NOT NULL,
    name        VARCHAR(64)     NOT NULL,
    sort_order  SMALLINT        NOT NULL DEFAULT 0,
    CONSTRAINT uq_workflow_code UNIQUE (code)
);

COMMENT ON TABLE workflow IS '标注流程阶段定义';
COMMENT ON COLUMN workflow.code IS '阶段编码：indexing / qc / rework / completed';

INSERT INTO workflow (code, name, sort_order) VALUES
    ('indexing', '标注', 1),
    ('qc', 'QC', 2),
    ('rework', '返工', 3),
    ('completed', '完成', 4)
ON CONFLICT (code) DO NOTHING;

ALTER TABLE tasks ADD COLUMN IF NOT EXISTS workflow_id SMALLINT REFERENCES workflow (id);

CREATE INDEX IF NOT EXISTS idx_tasks_workflow ON tasks (workflow_id);
CREATE INDEX IF NOT EXISTS idx_tasks_workflow_assignee ON tasks (workflow_id, assignee_id)
    WHERE assignee_id IS NOT NULL;

UPDATE tasks SET workflow_id = w.id
FROM workflow w
WHERE w.code = 'indexing'
  AND tasks.status::text IN ('indexing', 'in_progress', 'pending_claim')
  AND tasks.workflow_id IS NULL;

UPDATE tasks SET status = 'indexing'
WHERE status::text = 'in_progress';

UPDATE tasks SET workflow_id = w.id
FROM workflow w
WHERE w.code = 'rework'
  AND tasks.status::text = 'rework'
  AND tasks.assignee_id IS NOT NULL
  AND tasks.workflow_id IS NULL;

UPDATE tasks SET workflow_id = w.id
FROM workflow w
WHERE w.code = 'qc'
  AND tasks.status::text = 'pending_review'
  AND tasks.workflow_id IS NULL;

UPDATE tasks SET workflow_id = w.id
FROM workflow w
WHERE w.code = 'completed'
  AND tasks.status::text IN ('review_completed', 'closed')
  AND tasks.workflow_id IS NULL;
