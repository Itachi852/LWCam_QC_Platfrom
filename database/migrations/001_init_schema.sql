BEGIN;

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TABLE roles (
    id              BIGSERIAL PRIMARY KEY,
    rolecode        VARCHAR(50) NOT NULL UNIQUE,
    rolename        VARCHAR(100) NOT NULL UNIQUE,
    rolepermission  JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE users (
    id          BIGSERIAL PRIMARY KEY,
    userid      VARCHAR(50) NOT NULL UNIQUE,
    username    VARCHAR(100) NOT NULL,
    password    VARCHAR(255) NOT NULL,
    isactive    BOOLEAN NOT NULL DEFAULT TRUE,
    roleid      BIGINT NOT NULL REFERENCES roles(id),
    createtime  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_users_roleid ON users(roleid);
CREATE INDEX idx_users_isactive ON users(isactive);
CREATE TRIGGER trg_users_updated_at
BEFORE UPDATE ON users
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE batch_metadata (
    id               BIGSERIAL PRIMARY KEY,
    box_details      TEXT NOT NULL UNIQUE,
    cover_tag        TEXT,
    image_tags       TEXT,
    title            TEXT,
    volume           TEXT,
    start_date       INTEGER,
    end_date         INTEGER,
    archival_ref_no  TEXT,
    is_complete      BOOLEAN NOT NULL DEFAULT FALSE,
    device_id        TEXT,
    scanning_opr     TEXT,
    created_at       TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at       TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TRIGGER trg_batch_metadata_updated_at
BEFORE UPDATE ON batch_metadata
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE capture_boxes (
    id                     BIGSERIAL PRIMARY KEY,
    device_id              TEXT NOT NULL,
    box_details            TEXT NOT NULL,
    status                 VARCHAR(20) NOT NULL DEFAULT 'open',
    scanning_opr           TEXT,
    created_at             TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    transferred_at         TIMESTAMP,
    last_active_folder_id  BIGINT
);

CREATE TABLE capture_folders (
    id               BIGSERIAL PRIMARY KEY,
    box_id           BIGINT NOT NULL REFERENCES capture_boxes(id) ON DELETE CASCADE,
    folder_seq       INTEGER NOT NULL,
    cover_tag        TEXT,
    image_tags       TEXT,
    title            TEXT,
    volume           TEXT,
    start_date       INTEGER,
    end_date         INTEGER,
    archival_ref_no  TEXT,
    is_complete      BOOLEAN NOT NULL DEFAULT FALSE,
    folder_name      TEXT,
    created_at       TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at       TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_capture_folders_box_seq UNIQUE(box_id, folder_seq)
);

CREATE TRIGGER trg_capture_folders_updated_at
BEFORE UPDATE ON capture_folders
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE capture_folder_images (
    id               BIGSERIAL PRIMARY KEY,
    box_id           BIGINT NOT NULL REFERENCES capture_boxes(id) ON DELETE CASCADE,
    folder_id        BIGINT NOT NULL REFERENCES capture_folders(id) ON DELETE CASCADE,
    device_filename  TEXT NOT NULL UNIQUE,
    assigned_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_cfi_folder ON capture_folder_images(folder_id);

CREATE TABLE daily_summary (
    id            BIGSERIAL PRIMARY KEY,
    scanning_opr  TEXT,
    device_id     TEXT,
    date          DATE NOT NULL,
    total_count   INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE replacement_records (
    id                      BIGSERIAL PRIMARY KEY,
    device_id               TEXT NOT NULL,
    scanning_opr            TEXT,
    box_details             TEXT,
    sequence_index          INTEGER NOT NULL,
    date_key                DATE,
    original_filename       TEXT NOT NULL,
    replacement_filename    TEXT NOT NULL,
    replacement_local_path  TEXT,
    replacement_type        VARCHAR(50) NOT NULL,
    confirmed_at            TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    transferred_at          TIMESTAMP,
    superseded_at           TIMESTAMP,
    created_at              TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE upload_records (
    id               BIGSERIAL PRIMARY KEY,
    folder_id        BIGINT NOT NULL REFERENCES capture_folders(id) ON DELETE CASCADE,
    scanning_opr     TEXT,
    device_id        TEXT,
    box_details      TEXT,
    filename         TEXT NOT NULL,
    format           VARCHAR(50),
    created_at       TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at       TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    cover_tag        TEXT,
    image_tags       TEXT,
    title            TEXT,
    volume           TEXT,
    start_date       INTEGER,
    end_date         INTEGER,
    archival_ref_no  TEXT,
    record_type      VARCHAR(50)
);

CREATE INDEX idx_upload_records_created_at ON upload_records(created_at DESC);
CREATE INDEX idx_upload_records_box_details ON upload_records(box_details);
CREATE INDEX idx_upload_records_folder ON upload_records(folder_id, filename);
CREATE TRIGGER trg_upload_records_updated_at
BEFORE UPDATE ON upload_records
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE OR REPLACE FUNCTION bind_upload_record_folder()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.folder_id IS NULL THEN
        SELECT image.folder_id
        INTO NEW.folder_id
        FROM capture_folder_images image
        WHERE image.device_filename = NEW.filename;
        IF NEW.folder_id IS NULL THEN
            RAISE EXCEPTION 'No capture_folder_images mapping for filename: %', NEW.filename;
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_upload_records_bind_folder
BEFORE INSERT OR UPDATE OF filename, folder_id ON upload_records
FOR EACH ROW EXECUTE FUNCTION bind_upload_record_folder();

CREATE TABLE metadata_qc_tasks (
    id                 BIGSERIAL PRIMARY KEY,
    folder_id          BIGINT NOT NULL UNIQUE REFERENCES capture_folders(id) ON DELETE CASCADE,
    status             VARCHAR(20) NOT NULL DEFAULT 'pending',
    current_version    INTEGER NOT NULL DEFAULT 1 CHECK(current_version > 0),
    assigned_to        BIGINT REFERENCES users(id),
    claimed_at         TIMESTAMP,
    last_heartbeat_at  TIMESTAMP,
    lock_expires_at    TIMESTAMP,
    submitted_at       TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    reviewed_at        TIMESTAMP,
    created_at         TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at         TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT chk_metadata_qc_task_status
        CHECK(status IN ('pending', 'reviewing', 'approved', 'rejected', 'resubmitted'))
);

CREATE INDEX idx_metadata_qc_tasks_queue
    ON metadata_qc_tasks(status, submitted_at, id);
CREATE INDEX idx_metadata_qc_tasks_assigned
    ON metadata_qc_tasks(assigned_to, status);
CREATE TRIGGER trg_metadata_qc_tasks_updated_at
BEFORE UPDATE ON metadata_qc_tasks
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE metadata_qc_reviews (
    id                 BIGSERIAL PRIMARY KEY,
    task_id            BIGINT NOT NULL REFERENCES metadata_qc_tasks(id) ON DELETE CASCADE,
    folder_id          BIGINT NOT NULL REFERENCES capture_folders(id) ON DELETE CASCADE,
    reviewer_id        BIGINT NOT NULL REFERENCES users(id),
    review_version     INTEGER NOT NULL CHECK(review_version > 0),
    result             VARCHAR(20) NOT NULL,
    reject_reason      TEXT,
    comment            TEXT,
    metadata_snapshot  JSONB NOT NULL,
    created_at         TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT chk_metadata_qc_review_result CHECK(result IN ('approved', 'rejected')),
    CONSTRAINT chk_metadata_qc_review_reject_reason CHECK(
        result = 'approved'
        OR (reject_reason IS NOT NULL AND length(trim(reject_reason)) > 0)
    )
);

CREATE INDEX idx_metadata_qc_reviews_task
    ON metadata_qc_reviews(task_id, created_at DESC);
CREATE INDEX idx_metadata_qc_reviews_reviewer
    ON metadata_qc_reviews(reviewer_id, created_at DESC);
CREATE INDEX idx_metadata_qc_reviews_result
    ON metadata_qc_reviews(result, created_at DESC);

CREATE TABLE system_settings (
    id             BIGSERIAL PRIMARY KEY,
    setting_key    VARCHAR(100) NOT NULL UNIQUE,
    setting_value  TEXT NOT NULL DEFAULT '',
    updated_at     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_by     BIGINT REFERENCES users(id)
);

CREATE TRIGGER trg_system_settings_updated_at
BEFORE UPDATE ON system_settings
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE OR REPLACE FUNCTION metadata_qc_folder_ready(target_folder_id BIGINT)
RETURNS BOOLEAN AS $$
    SELECT EXISTS (
        SELECT 1
        FROM capture_folders folder
        WHERE folder.id = target_folder_id
          AND folder.is_complete = TRUE
          AND EXISTS (
              SELECT 1 FROM capture_folder_images image
              WHERE image.folder_id = folder.id
          )
          AND NOT EXISTS (
              SELECT 1
              FROM capture_folder_images image
              WHERE image.folder_id = folder.id
                AND NOT EXISTS (
                    SELECT 1
                    FROM upload_records upload
                    WHERE upload.folder_id = folder.id
                      AND upload.filename = image.device_filename
                )
          )
    );
$$ LANGUAGE sql STABLE;

CREATE OR REPLACE FUNCTION queue_metadata_qc_folder(target_folder_id BIGINT, source_changed BOOLEAN)
RETURNS VOID AS $$
BEGIN
    IF target_folder_id IS NULL OR NOT metadata_qc_folder_ready(target_folder_id) THEN
        RETURN;
    END IF;

    INSERT INTO metadata_qc_tasks(folder_id, status, submitted_at)
    VALUES(target_folder_id, 'pending', CURRENT_TIMESTAMP)
    ON CONFLICT(folder_id) DO UPDATE SET
        status = CASE
            WHEN source_changed AND metadata_qc_tasks.status NOT IN ('pending', 'resubmitted') THEN 'resubmitted'
            ELSE metadata_qc_tasks.status
        END,
        current_version = CASE
            WHEN source_changed AND metadata_qc_tasks.status NOT IN ('pending', 'resubmitted')
                THEN metadata_qc_tasks.current_version + 1
            ELSE metadata_qc_tasks.current_version
        END,
        assigned_to = CASE
            WHEN source_changed AND metadata_qc_tasks.status NOT IN ('pending', 'resubmitted') THEN NULL
            ELSE metadata_qc_tasks.assigned_to
        END,
        claimed_at = CASE
            WHEN source_changed AND metadata_qc_tasks.status NOT IN ('pending', 'resubmitted') THEN NULL
            ELSE metadata_qc_tasks.claimed_at
        END,
        last_heartbeat_at = CASE
            WHEN source_changed AND metadata_qc_tasks.status NOT IN ('pending', 'resubmitted') THEN NULL
            ELSE metadata_qc_tasks.last_heartbeat_at
        END,
        lock_expires_at = CASE
            WHEN source_changed AND metadata_qc_tasks.status NOT IN ('pending', 'resubmitted') THEN NULL
            ELSE metadata_qc_tasks.lock_expires_at
        END,
        submitted_at = CASE
            WHEN source_changed AND metadata_qc_tasks.status NOT IN ('pending', 'resubmitted') THEN CURRENT_TIMESTAMP
            ELSE metadata_qc_tasks.submitted_at
        END,
        reviewed_at = CASE
            WHEN source_changed AND metadata_qc_tasks.status NOT IN ('pending', 'resubmitted') THEN NULL
            ELSE metadata_qc_tasks.reviewed_at
        END;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION sync_qc_task_from_upload()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'UPDATE' AND OLD.folder_id IS DISTINCT FROM NEW.folder_id THEN
        PERFORM queue_metadata_qc_folder(OLD.folder_id, TRUE);
    END IF;
    PERFORM queue_metadata_qc_folder(NEW.folder_id, TRUE);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_upload_records_sync_qc_task
AFTER INSERT OR UPDATE OF folder_id, filename, format, cover_tag, image_tags, title, volume,
    start_date, end_date, archival_ref_no, record_type
ON upload_records
FOR EACH ROW EXECUTE FUNCTION sync_qc_task_from_upload();

CREATE OR REPLACE FUNCTION sync_qc_task_from_folder()
RETURNS TRIGGER AS $$
DECLARE
    source_changed BOOLEAN;
BEGIN
    source_changed := ROW(
        OLD.box_id, OLD.folder_seq, OLD.cover_tag, OLD.image_tags, OLD.title,
        OLD.volume, OLD.start_date, OLD.end_date, OLD.archival_ref_no, OLD.folder_name
    ) IS DISTINCT FROM ROW(
        NEW.box_id, NEW.folder_seq, NEW.cover_tag, NEW.image_tags, NEW.title,
        NEW.volume, NEW.start_date, NEW.end_date, NEW.archival_ref_no, NEW.folder_name
    );
    PERFORM queue_metadata_qc_folder(NEW.id, source_changed);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_capture_folders_sync_qc_task
AFTER UPDATE OF box_id, folder_seq, cover_tag, image_tags, title, volume, start_date,
    end_date, archival_ref_no, is_complete, folder_name
ON capture_folders
FOR EACH ROW EXECUTE FUNCTION sync_qc_task_from_folder();

CREATE OR REPLACE FUNCTION sync_qc_task_from_folder_image()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        PERFORM queue_metadata_qc_folder(OLD.folder_id, TRUE);
        RETURN OLD;
    END IF;
    IF TG_OP = 'UPDATE' AND OLD.folder_id IS DISTINCT FROM NEW.folder_id THEN
        PERFORM queue_metadata_qc_folder(OLD.folder_id, TRUE);
    END IF;
    PERFORM queue_metadata_qc_folder(NEW.folder_id, TRUE);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_capture_folder_images_sync_qc_task
AFTER INSERT OR UPDATE OR DELETE ON capture_folder_images
FOR EACH ROW EXECUTE FUNCTION sync_qc_task_from_folder_image();

INSERT INTO metadata_qc_tasks(folder_id, status, submitted_at)
SELECT folder.id, 'pending', folder.updated_at
FROM capture_folders folder
WHERE metadata_qc_folder_ready(folder.id)
ON CONFLICT(folder_id) DO NOTHING;

COMMIT;
