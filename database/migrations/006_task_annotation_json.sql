-- LWCam migration 006: task-level annotation (one annotation per folder/task)

ALTER TABLE tasks ADD COLUMN IF NOT EXISTS annotation_json JSONB;
