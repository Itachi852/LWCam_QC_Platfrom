-- LWCam migration 002: settings, folder import, indexing QC workflow

ALTER TYPE task_status ADD VALUE IF NOT EXISTS 'pending_index_qc';
ALTER TYPE task_status ADD VALUE IF NOT EXISTS 'rework';

DO $$ BEGIN
    CREATE TYPE index_qc_result AS ENUM ('passed', 'rejected');
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

CREATE TABLE IF NOT EXISTS system_settings (
    id              BIGSERIAL       PRIMARY KEY,
    setting_key     VARCHAR(100)    NOT NULL,
    setting_value   TEXT            NOT NULL DEFAULT '',
    updated_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_by      BIGINT          REFERENCES users (id),

    CONSTRAINT uq_system_settings_key UNIQUE (setting_key)
);

COMMENT ON TABLE system_settings IS '系统配置（键值对）';

DROP TRIGGER IF EXISTS trg_system_settings_updated_at ON system_settings;
CREATE TRIGGER trg_system_settings_updated_at
    BEFORE UPDATE ON system_settings
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

ALTER TABLE tasks ADD COLUMN IF NOT EXISTS source_folder_path VARCHAR(1000);

COMMENT ON COLUMN tasks.source_folder_path IS '导入来源文件夹绝对路径，用于去重';

CREATE UNIQUE INDEX IF NOT EXISTS uq_tasks_source_folder_path
    ON tasks (source_folder_path)
    WHERE source_folder_path IS NOT NULL;

CREATE TABLE IF NOT EXISTS task_index_qc_records (
    id              BIGSERIAL       PRIMARY KEY,
    task_id         BIGINT          NOT NULL REFERENCES tasks (id) ON DELETE CASCADE,
    qc_user_id      BIGINT          NOT NULL REFERENCES users (id),
    result          index_qc_result NOT NULL,
    comment         TEXT,
    reject_reason   TEXT,
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_task_index_qc_reject_reason
        CHECK (
            result = 'passed'
            OR (result = 'rejected' AND reject_reason IS NOT NULL AND LENGTH(TRIM(reject_reason)) > 0)
        )
);

COMMENT ON TABLE task_index_qc_records IS '任务索引 QC 审核记录（文件夹导入后）';

CREATE INDEX IF NOT EXISTS idx_task_index_qc_task ON task_index_qc_records (task_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_tasks_pending_index_qc ON tasks (created_at DESC)
    WHERE status = 'pending_index_qc';
