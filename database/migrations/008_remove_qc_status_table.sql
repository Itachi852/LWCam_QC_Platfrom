-- ============================================================================
-- Migration 008: Remove qc_status table and use capture_folders fields
-- ============================================================================

-- Add concurrency lock fields to capture_folders
ALTER TABLE capture_folders
    ADD COLUMN qc_locked_by VARCHAR(255),
    ADD COLUMN qc_locked_at TIMESTAMPTZ(3);

CREATE INDEX idx_capture_folders_qc_lock
    ON capture_folders(qc_locked_by)
    WHERE qc_locked_by IS NOT NULL;

-- Drop qc_status table (no longer needed)
DROP TABLE IF EXISTS qc_status;
