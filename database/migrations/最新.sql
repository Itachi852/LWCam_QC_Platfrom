/*
 Navicat Premium Dump SQL

 Source Server         : mypostgre
 Source Server Type    : PostgreSQL
 Source Server Version : 160014 (160014)
 Source Host           : localhost:5433
 Source Catalog        : testlwcam
 Source Schema         : public

 Target Server Type    : PostgreSQL
 Target Server Version : 160014 (160014)
 File Encoding         : 65001

 Date: 23/07/2026 17:25:17
*/


-- ----------------------------
-- Sequence structure for capture_boxes_box_id_seq
-- ----------------------------
DROP SEQUENCE IF EXISTS "public"."capture_boxes_box_id_seq";
CREATE SEQUENCE "public"."capture_boxes_box_id_seq" 
INCREMENT 1
MINVALUE  1
MAXVALUE 9223372036854775807
START 1
CACHE 1;

-- ----------------------------
-- Sequence structure for capture_boxes_box_id_seq1
-- ----------------------------
DROP SEQUENCE IF EXISTS "public"."capture_boxes_box_id_seq1";
CREATE SEQUENCE "public"."capture_boxes_box_id_seq1" 
INCREMENT 1
MINVALUE  1
MAXVALUE 9223372036854775807
START 1
CACHE 1;

-- ----------------------------
-- Sequence structure for capture_folders_id_seq
-- ----------------------------
DROP SEQUENCE IF EXISTS "public"."capture_folders_id_seq";
CREATE SEQUENCE "public"."capture_folders_id_seq" 
INCREMENT 1
MINVALUE  1
MAXVALUE 9223372036854775807
START 1
CACHE 1;

-- ----------------------------
-- Sequence structure for capture_folders_id_seq1
-- ----------------------------
DROP SEQUENCE IF EXISTS "public"."capture_folders_id_seq1";
CREATE SEQUENCE "public"."capture_folders_id_seq1" 
INCREMENT 1
MINVALUE  1
MAXVALUE 9223372036854775807
START 1
CACHE 1;

-- ----------------------------
-- Sequence structure for capture_images_id_seq
-- ----------------------------
DROP SEQUENCE IF EXISTS "public"."capture_images_id_seq";
CREATE SEQUENCE "public"."capture_images_id_seq" 
INCREMENT 1
MINVALUE  1
MAXVALUE 9223372036854775807
START 1
CACHE 1;

-- ----------------------------
-- Sequence structure for capture_images_id_seq1
-- ----------------------------
DROP SEQUENCE IF EXISTS "public"."capture_images_id_seq1";
CREATE SEQUENCE "public"."capture_images_id_seq1" 
INCREMENT 1
MINVALUE  1
MAXVALUE 9223372036854775807
START 1
CACHE 1;

-- ----------------------------
-- Sequence structure for devices_id_seq
-- ----------------------------
DROP SEQUENCE IF EXISTS "public"."devices_id_seq";
CREATE SEQUENCE "public"."devices_id_seq" 
INCREMENT 1
MINVALUE  1
MAXVALUE 9223372036854775807
START 1
CACHE 1;

-- ----------------------------
-- Sequence structure for devices_id_seq1
-- ----------------------------
DROP SEQUENCE IF EXISTS "public"."devices_id_seq1";
CREATE SEQUENCE "public"."devices_id_seq1" 
INCREMENT 1
MINVALUE  1
MAXVALUE 9223372036854775807
START 1
CACHE 1;

-- ----------------------------
-- Sequence structure for projects_id_seq
-- ----------------------------
DROP SEQUENCE IF EXISTS "public"."projects_id_seq";
CREATE SEQUENCE "public"."projects_id_seq" 
INCREMENT 1
MINVALUE  1
MAXVALUE 9223372036854775807
START 1
CACHE 1;

-- ----------------------------
-- Sequence structure for projects_id_seq1
-- ----------------------------
DROP SEQUENCE IF EXISTS "public"."projects_id_seq1";
CREATE SEQUENCE "public"."projects_id_seq1" 
INCREMENT 1
MINVALUE  1
MAXVALUE 9223372036854775807
START 1
CACHE 1;

-- ----------------------------
-- Sequence structure for rework_logs_id_seq
-- ----------------------------
DROP SEQUENCE IF EXISTS "public"."rework_logs_id_seq";
CREATE SEQUENCE "public"."rework_logs_id_seq" 
INCREMENT 1
MINVALUE  1
MAXVALUE 9223372036854775807
START 1
CACHE 1;

-- ----------------------------
-- Sequence structure for rework_logs_id_seq1
-- ----------------------------
DROP SEQUENCE IF EXISTS "public"."rework_logs_id_seq1";
CREATE SEQUENCE "public"."rework_logs_id_seq1" 
INCREMENT 1
MINVALUE  1
MAXVALUE 9223372036854775807
START 1
CACHE 1;

-- ----------------------------
-- Sequence structure for roles_id_seq
-- ----------------------------
DROP SEQUENCE IF EXISTS "public"."roles_id_seq";
CREATE SEQUENCE "public"."roles_id_seq" 
INCREMENT 1
MINVALUE  1
MAXVALUE 2147483647
START 1
CACHE 1;

-- ----------------------------
-- Sequence structure for roles_id_seq1
-- ----------------------------
DROP SEQUENCE IF EXISTS "public"."roles_id_seq1";
CREATE SEQUENCE "public"."roles_id_seq1" 
INCREMENT 1
MINVALUE  1
MAXVALUE 2147483647
START 1
CACHE 1;

-- ----------------------------
-- Sequence structure for users_id_seq
-- ----------------------------
DROP SEQUENCE IF EXISTS "public"."users_id_seq";
CREATE SEQUENCE "public"."users_id_seq" 
INCREMENT 1
MINVALUE  1
MAXVALUE 9223372036854775807
START 1
CACHE 1;

-- ----------------------------
-- Sequence structure for users_id_seq1
-- ----------------------------
DROP SEQUENCE IF EXISTS "public"."users_id_seq1";
CREATE SEQUENCE "public"."users_id_seq1" 
INCREMENT 1
MINVALUE  1
MAXVALUE 9223372036854775807
START 1
CACHE 1;

-- ----------------------------
-- Table structure for app_settings
-- ----------------------------
DROP TABLE IF EXISTS "public"."app_settings";
CREATE TABLE "public"."app_settings" (
  "key" varchar(255) COLLATE "pg_catalog"."default" NOT NULL,
  "value" varchar(10800) COLLATE "pg_catalog"."default",
  "updated_at" timestamptz(3) NOT NULL DEFAULT clock_timestamp()
)
;

-- ----------------------------
-- Table structure for capture_boxes
-- ----------------------------
DROP TABLE IF EXISTS "public"."capture_boxes";
CREATE TABLE "public"."capture_boxes" (
  "box_id" int8 NOT NULL GENERATED BY DEFAULT AS IDENTITY (
INCREMENT 1
MINVALUE  1
MAXVALUE 9223372036854775807
START 1
CACHE 1
),
  "box_name" varchar(255) COLLATE "pg_catalog"."default" NOT NULL,
  "device_id" int8 NOT NULL,
  "status" varchar(255) COLLATE "pg_catalog"."default" NOT NULL DEFAULT 'OPEN'::character varying,
  "user_id" int8 NOT NULL,
  "project_id" int8 NOT NULL,
  "created_at" timestamptz(3) NOT NULL DEFAULT clock_timestamp(),
  "updated_at" timestamptz(3) NOT NULL DEFAULT clock_timestamp(),
  "transfer_start_at" timestamptz(3),
  "transfer_end_at" timestamptz(3),
  "transferred_to" varchar(255) COLLATE "pg_catalog"."default",
  "is_deleted" bool NOT NULL DEFAULT false,
  "deleted_at" timestamptz(3)
)
;

-- ----------------------------
-- Table structure for capture_folders
-- ----------------------------
DROP TABLE IF EXISTS "public"."capture_folders";
CREATE TABLE "public"."capture_folders" (
  "id" int8 NOT NULL GENERATED BY DEFAULT AS IDENTITY (
INCREMENT 1
MINVALUE  1
MAXVALUE 9223372036854775807
START 1
CACHE 1
),
  "group_id" varchar(255) COLLATE "pg_catalog"."default",
  "folder_name" varchar(255) COLLATE "pg_catalog"."default" NOT NULL,
  "box_id" int8 NOT NULL,
  "device_id" int8 NOT NULL,
  "folder_seq" int4 NOT NULL,
  "cover_tag" varchar(255) COLLATE "pg_catalog"."default",
  "image_tags" varchar(255) COLLATE "pg_catalog"."default",
  "title" varchar(255) COLLATE "pg_catalog"."default",
  "volume" varchar(255) COLLATE "pg_catalog"."default",
  "start_date" timestamptz(3),
  "end_date" timestamptz(3),
  "archival_ref_no" varchar(255) COLLATE "pg_catalog"."default",
  "record_type" varchar(255) COLLATE "pg_catalog"."default",
  "place" varchar(255) COLLATE "pg_catalog"."default",
  "language" varchar(255) COLLATE "pg_catalog"."default",
  "record_custodian" varchar(255) COLLATE "pg_catalog"."default",
  "capture_operator_id" varchar(255) COLLATE "pg_catalog"."default",
  "capture_operator_name" varchar(255) COLLATE "pg_catalog"."default",
  "digitizing_entity" varchar(255) COLLATE "pg_catalog"."default",
  "source_created_at" timestamptz(3),
  "source_updated_at" timestamptz(3),
  "updated_at" timestamptz(3) NOT NULL DEFAULT clock_timestamp(),
  "is_deleted" bool NOT NULL DEFAULT false,
  "deleted_at" timestamptz(3),
  "client_qc_status" varchar(20) COLLATE "pg_catalog"."default",
  "client_rework" bool NOT NULL DEFAULT false,
  "is_deskewed" bool NOT NULL DEFAULT false,
  "is_cropped" bool NOT NULL DEFAULT false,
  "is_created_thumbnail" bool NOT NULL DEFAULT false,
  "folder_path" varchar(10800) COLLATE "pg_catalog"."default",
  "thumbnail_path" varchar(10800) COLLATE "pg_catalog"."default",
  "qc_status" varchar(20) COLLATE "pg_catalog"."default" NOT NULL DEFAULT 'PENDING'::character varying,
  "is_tif_converted" bool NOT NULL DEFAULT false,
  "is_exported" bool NOT NULL DEFAULT false,
  "exported_time" timestamptz(3),
  "is_ingested" bool NOT NULL DEFAULT false,
  "ingested_time" timestamptz(3),
  "qc_locked_by" varchar(255) COLLATE "pg_catalog"."default",
  "qc_locked_at" timestamptz(3)
)
;

-- ----------------------------
-- Table structure for capture_images
-- ----------------------------
DROP TABLE IF EXISTS "public"."capture_images";
CREATE TABLE "public"."capture_images" (
  "id" int8 NOT NULL GENERATED BY DEFAULT AS IDENTITY (
INCREMENT 1
MINVALUE  1
MAXVALUE 9223372036854775807
START 1
CACHE 1
),
  "image_name" varchar(255) COLLATE "pg_catalog"."default" NOT NULL,
  "device_id" int8 NOT NULL,
  "folder_id" int8 NOT NULL,
  "file_format" varchar(10) COLLATE "pg_catalog"."default" NOT NULL,
  "image_created_at" timestamptz(3) NOT NULL DEFAULT clock_timestamp(),
  "image_updated_at" timestamptz(3)
)
;

-- ----------------------------
-- Table structure for devices
-- ----------------------------
DROP TABLE IF EXISTS "public"."devices";
CREATE TABLE "public"."devices" (
  "id" int8 NOT NULL GENERATED BY DEFAULT AS IDENTITY (
INCREMENT 1
MINVALUE  1
MAXVALUE 9223372036854775807
START 1
CACHE 1
),
  "device_id" varchar(255) COLLATE "pg_catalog"."default" NOT NULL,
  "country_location_code" varchar(32) COLLATE "pg_catalog"."default" NOT NULL,
  "user_id" int8,
  "login_at" timestamptz(3) NOT NULL DEFAULT clock_timestamp()
)
;

-- ----------------------------
-- Table structure for projects
-- ----------------------------
DROP TABLE IF EXISTS "public"."projects";
CREATE TABLE "public"."projects" (
  "id" int8 NOT NULL GENERATED BY DEFAULT AS IDENTITY (
INCREMENT 1
MINVALUE  1
MAXVALUE 9223372036854775807
START 1
CACHE 1
),
  "project_id" varchar(255) COLLATE "pg_catalog"."default" NOT NULL,
  "project_key" varchar(64) COLLATE "pg_catalog"."default" NOT NULL,
  "project_name" varchar(255) COLLATE "pg_catalog"."default" NOT NULL,
  "country_location_code" varchar(32) COLLATE "pg_catalog"."default" NOT NULL,
  "start_date" timestamptz(3),
  "has_data" bool NOT NULL DEFAULT false,
  "template" jsonb,
  "created_at" timestamptz(3) NOT NULL DEFAULT clock_timestamp(),
  "created_by" int8,
  "updated_at" timestamptz(3) NOT NULL DEFAULT clock_timestamp(),
  "updated_by" int8,
  "is_deleted" bool NOT NULL DEFAULT false,
  "deleted_at" timestamptz(3)
)
;

-- ----------------------------
-- Table structure for rework_logs
-- ----------------------------
DROP TABLE IF EXISTS "public"."rework_logs";
CREATE TABLE "public"."rework_logs" (
  "id" int8 NOT NULL GENERATED BY DEFAULT AS IDENTITY (
INCREMENT 1
MINVALUE  1
MAXVALUE 9223372036854775807
START 1
CACHE 1
),
  "image_id" int8,
  "assigned_uid" int8 NOT NULL,
  "folder_id" int8 NOT NULL,
  "created_at" timestamptz(3) NOT NULL DEFAULT clock_timestamp(),
  "rework_comments" varchar(10800) COLLATE "pg_catalog"."default" NOT NULL,
  "rework_status" varchar(20) COLLATE "pg_catalog"."default" NOT NULL DEFAULT 'OPEN'::character varying,
  "rework_type" varchar(255) COLLATE "pg_catalog"."default" NOT NULL
)
;

-- ----------------------------
-- Table structure for roles
-- ----------------------------
DROP TABLE IF EXISTS "public"."roles";
CREATE TABLE "public"."roles" (
  "id" int4 NOT NULL GENERATED BY DEFAULT AS IDENTITY (
INCREMENT 1
MINVALUE  1
MAXVALUE 2147483647
START 1
CACHE 1
),
  "role_name" varchar(255) COLLATE "pg_catalog"."default" NOT NULL
)
;

-- ----------------------------
-- Table structure for user_projects
-- ----------------------------
DROP TABLE IF EXISTS "public"."user_projects";
CREATE TABLE "public"."user_projects" (
  "user_id" int8 NOT NULL,
  "project_id" int8 NOT NULL,
  "role_id" int4 NOT NULL
)
;

-- ----------------------------
-- Table structure for users
-- ----------------------------
DROP TABLE IF EXISTS "public"."users";
CREATE TABLE "public"."users" (
  "id" int8 NOT NULL GENERATED BY DEFAULT AS IDENTITY (
INCREMENT 1
MINVALUE  1
MAXVALUE 9223372036854775807
START 1
CACHE 1
),
  "user_id" varchar(255) COLLATE "pg_catalog"."default" NOT NULL,
  "password" varchar(255) COLLATE "pg_catalog"."default" NOT NULL,
  "active" bool NOT NULL DEFAULT true,
  "must_change_password" bool NOT NULL DEFAULT true,
  "created_at" timestamptz(3) NOT NULL DEFAULT clock_timestamp(),
  "created_by" int8,
  "last_login_at" timestamptz(3),
  "device_id" varchar(255) COLLATE "pg_catalog"."default",
  "roles" varchar(255) COLLATE "pg_catalog"."default" NOT NULL DEFAULT ''::character varying,
  "updated_at" timestamptz(3) NOT NULL DEFAULT clock_timestamp(),
  "updated_by" int8,
  "is_deleted" bool NOT NULL DEFAULT false,
  "deleted_at" timestamptz(3)
)
;

-- ----------------------------
-- Function structure for lwcam_set_updated_at
-- ----------------------------
DROP FUNCTION IF EXISTS "public"."lwcam_set_updated_at"();
CREATE FUNCTION "public"."lwcam_set_updated_at"()
  RETURNS "pg_catalog"."trigger" AS $BODY$
BEGIN
    NEW.updated_at := clock_timestamp();
    RETURN NEW;
END;
$BODY$
  LANGUAGE plpgsql VOLATILE
  COST 100;

-- ----------------------------
-- Alter sequences owned by
-- ----------------------------
ALTER SEQUENCE "public"."capture_boxes_box_id_seq"
OWNED BY "public"."capture_boxes"."box_id";
SELECT setval('"public"."capture_boxes_box_id_seq"', 1, false);

-- ----------------------------
-- Alter sequences owned by
-- ----------------------------
ALTER SEQUENCE "public"."capture_boxes_box_id_seq1"
OWNED BY "public"."capture_boxes"."box_id";
SELECT setval('"public"."capture_boxes_box_id_seq1"', 1, false);

-- ----------------------------
-- Alter sequences owned by
-- ----------------------------
ALTER SEQUENCE "public"."capture_folders_id_seq"
OWNED BY "public"."capture_folders"."id";
SELECT setval('"public"."capture_folders_id_seq"', 1, false);

-- ----------------------------
-- Alter sequences owned by
-- ----------------------------
ALTER SEQUENCE "public"."capture_folders_id_seq1"
OWNED BY "public"."capture_folders"."id";
SELECT setval('"public"."capture_folders_id_seq1"', 1, false);

-- ----------------------------
-- Alter sequences owned by
-- ----------------------------
ALTER SEQUENCE "public"."capture_images_id_seq"
OWNED BY "public"."capture_images"."id";
SELECT setval('"public"."capture_images_id_seq"', 1, false);

-- ----------------------------
-- Alter sequences owned by
-- ----------------------------
ALTER SEQUENCE "public"."capture_images_id_seq1"
OWNED BY "public"."capture_images"."id";
SELECT setval('"public"."capture_images_id_seq1"', 1, false);

-- ----------------------------
-- Alter sequences owned by
-- ----------------------------
ALTER SEQUENCE "public"."devices_id_seq"
OWNED BY "public"."devices"."id";
SELECT setval('"public"."devices_id_seq"', 1, false);

-- ----------------------------
-- Alter sequences owned by
-- ----------------------------
ALTER SEQUENCE "public"."devices_id_seq1"
OWNED BY "public"."devices"."id";
SELECT setval('"public"."devices_id_seq1"', 1, false);

-- ----------------------------
-- Alter sequences owned by
-- ----------------------------
ALTER SEQUENCE "public"."projects_id_seq"
OWNED BY "public"."projects"."id";
SELECT setval('"public"."projects_id_seq"', 1, false);

-- ----------------------------
-- Alter sequences owned by
-- ----------------------------
ALTER SEQUENCE "public"."projects_id_seq1"
OWNED BY "public"."projects"."id";
SELECT setval('"public"."projects_id_seq1"', 1, false);

-- ----------------------------
-- Alter sequences owned by
-- ----------------------------
ALTER SEQUENCE "public"."rework_logs_id_seq"
OWNED BY "public"."rework_logs"."id";
SELECT setval('"public"."rework_logs_id_seq"', 1, false);

-- ----------------------------
-- Alter sequences owned by
-- ----------------------------
ALTER SEQUENCE "public"."rework_logs_id_seq1"
OWNED BY "public"."rework_logs"."id";
SELECT setval('"public"."rework_logs_id_seq1"', 1, true);

-- ----------------------------
-- Alter sequences owned by
-- ----------------------------
ALTER SEQUENCE "public"."roles_id_seq"
OWNED BY "public"."roles"."id";
SELECT setval('"public"."roles_id_seq"', 1, false);

-- ----------------------------
-- Alter sequences owned by
-- ----------------------------
ALTER SEQUENCE "public"."roles_id_seq1"
OWNED BY "public"."roles"."id";
SELECT setval('"public"."roles_id_seq1"', 1, false);

-- ----------------------------
-- Alter sequences owned by
-- ----------------------------
ALTER SEQUENCE "public"."users_id_seq"
OWNED BY "public"."users"."id";
SELECT setval('"public"."users_id_seq"', 1, false);

-- ----------------------------
-- Alter sequences owned by
-- ----------------------------
ALTER SEQUENCE "public"."users_id_seq1"
OWNED BY "public"."users"."id";
SELECT setval('"public"."users_id_seq1"', 2, true);

-- ----------------------------
-- Triggers structure for table app_settings
-- ----------------------------
CREATE TRIGGER "trg_app_settings_updated_at" BEFORE UPDATE ON "public"."app_settings"
FOR EACH ROW
EXECUTE PROCEDURE "public"."lwcam_set_updated_at"();

-- ----------------------------
-- Primary Key structure for table app_settings
-- ----------------------------
ALTER TABLE "public"."app_settings" ADD CONSTRAINT "app_settings_pkey" PRIMARY KEY ("key");

-- ----------------------------
-- Indexes structure for table capture_boxes
-- ----------------------------
CREATE INDEX "idx_capture_boxes_device_id" ON "public"."capture_boxes" USING btree (
  "device_id" "pg_catalog"."int8_ops" ASC NULLS LAST
);
CREATE INDEX "idx_capture_boxes_user_id" ON "public"."capture_boxes" USING btree (
  "user_id" "pg_catalog"."int8_ops" ASC NULLS LAST
);

-- ----------------------------
-- Triggers structure for table capture_boxes
-- ----------------------------
CREATE TRIGGER "trg_capture_boxes_updated_at" BEFORE UPDATE ON "public"."capture_boxes"
FOR EACH ROW
EXECUTE PROCEDURE "public"."lwcam_set_updated_at"();

-- ----------------------------
-- Uniques structure for table capture_boxes
-- ----------------------------
ALTER TABLE "public"."capture_boxes" ADD CONSTRAINT "uq_capture_boxes_project_name" UNIQUE ("project_id", "box_name");

-- ----------------------------
-- Primary Key structure for table capture_boxes
-- ----------------------------
ALTER TABLE "public"."capture_boxes" ADD CONSTRAINT "capture_boxes_pkey" PRIMARY KEY ("box_id");

-- ----------------------------
-- Indexes structure for table capture_folders
-- ----------------------------
CREATE INDEX "idx_capture_folders_device_id" ON "public"."capture_folders" USING btree (
  "device_id" "pg_catalog"."int8_ops" ASC NULLS LAST
);
CREATE INDEX "idx_capture_folders_qc_lock" ON "public"."capture_folders" USING btree (
  "qc_locked_by" COLLATE "pg_catalog"."default" "pg_catalog"."text_ops" ASC NULLS LAST
) WHERE qc_locked_by IS NOT NULL;

-- ----------------------------
-- Triggers structure for table capture_folders
-- ----------------------------
CREATE TRIGGER "trg_capture_folders_updated_at" BEFORE UPDATE ON "public"."capture_folders"
FOR EACH ROW
EXECUTE PROCEDURE "public"."lwcam_set_updated_at"();

-- ----------------------------
-- Uniques structure for table capture_folders
-- ----------------------------
ALTER TABLE "public"."capture_folders" ADD CONSTRAINT "capture_folders_group_id_key" UNIQUE ("group_id");
ALTER TABLE "public"."capture_folders" ADD CONSTRAINT "uq_capture_folders_box_sequence" UNIQUE ("box_id", "folder_seq");

-- ----------------------------
-- Checks structure for table capture_folders
-- ----------------------------
ALTER TABLE "public"."capture_folders" ADD CONSTRAINT "chk_capture_folders_qc_status" CHECK (qc_status::text = ANY (ARRAY['PASS'::character varying::text, 'REWORK'::character varying::text, 'PENDING'::character varying::text]));
ALTER TABLE "public"."capture_folders" ADD CONSTRAINT "chk_capture_folders_client_qc_status" CHECK (client_qc_status IS NULL OR (client_qc_status::text = ANY (ARRAY['UNDER REVIEW'::character varying::text, 'APPROVED'::character varying::text, 'REJECTED'::character varying::text])));

-- ----------------------------
-- Primary Key structure for table capture_folders
-- ----------------------------
ALTER TABLE "public"."capture_folders" ADD CONSTRAINT "capture_folders_pkey" PRIMARY KEY ("id");

-- ----------------------------
-- Indexes structure for table capture_images
-- ----------------------------
CREATE INDEX "idx_capture_images_device_id" ON "public"."capture_images" USING btree (
  "device_id" "pg_catalog"."int8_ops" ASC NULLS LAST
);
CREATE INDEX "idx_capture_images_image_name" ON "public"."capture_images" USING btree (
  "image_name" COLLATE "pg_catalog"."default" "pg_catalog"."text_ops" ASC NULLS LAST
);

-- ----------------------------
-- Uniques structure for table capture_images
-- ----------------------------
ALTER TABLE "public"."capture_images" ADD CONSTRAINT "uq_capture_images_folder_image" UNIQUE ("folder_id", "image_name");

-- ----------------------------
-- Checks structure for table capture_images
-- ----------------------------
ALTER TABLE "public"."capture_images" ADD CONSTRAINT "chk_capture_images_file_format" CHECK (lower(file_format::text) = ANY (ARRAY['jpg'::text, 'jpeg'::text, 'tif'::text, 'tiff'::text, 'png'::text]));

-- ----------------------------
-- Primary Key structure for table capture_images
-- ----------------------------
ALTER TABLE "public"."capture_images" ADD CONSTRAINT "capture_images_pkey" PRIMARY KEY ("id");

-- ----------------------------
-- Indexes structure for table devices
-- ----------------------------
CREATE INDEX "idx_devices_country_location_code" ON "public"."devices" USING btree (
  "country_location_code" COLLATE "pg_catalog"."default" "pg_catalog"."text_ops" ASC NULLS LAST
);
CREATE INDEX "idx_devices_user_id" ON "public"."devices" USING btree (
  "user_id" "pg_catalog"."int8_ops" ASC NULLS LAST
);

-- ----------------------------
-- Uniques structure for table devices
-- ----------------------------
ALTER TABLE "public"."devices" ADD CONSTRAINT "devices_device_id_key" UNIQUE ("device_id");

-- ----------------------------
-- Primary Key structure for table devices
-- ----------------------------
ALTER TABLE "public"."devices" ADD CONSTRAINT "devices_pkey" PRIMARY KEY ("id");

-- ----------------------------
-- Indexes structure for table projects
-- ----------------------------
CREATE INDEX "idx_projects_created_by" ON "public"."projects" USING btree (
  "created_by" "pg_catalog"."int8_ops" ASC NULLS LAST
);
CREATE INDEX "idx_projects_updated_by" ON "public"."projects" USING btree (
  "updated_by" "pg_catalog"."int8_ops" ASC NULLS LAST
);
CREATE UNIQUE INDEX "uq_projects_project_id_live" ON "public"."projects" USING btree (
  "project_id" COLLATE "pg_catalog"."default" "pg_catalog"."text_ops" ASC NULLS LAST
) WHERE is_deleted = false;
CREATE UNIQUE INDEX "uq_projects_project_name_live" ON "public"."projects" USING btree (
  "project_name" COLLATE "pg_catalog"."default" "pg_catalog"."text_ops" ASC NULLS LAST
) WHERE is_deleted = false;

-- ----------------------------
-- Triggers structure for table projects
-- ----------------------------
CREATE TRIGGER "trg_projects_updated_at" BEFORE UPDATE ON "public"."projects"
FOR EACH ROW
EXECUTE PROCEDURE "public"."lwcam_set_updated_at"();

-- ----------------------------
-- Uniques structure for table projects
-- ----------------------------
ALTER TABLE "public"."projects" ADD CONSTRAINT "projects_project_key_key" UNIQUE ("project_key");
ALTER TABLE "public"."projects" ADD CONSTRAINT "projects_country_location_code_key" UNIQUE ("country_location_code");

-- ----------------------------
-- Primary Key structure for table projects
-- ----------------------------
ALTER TABLE "public"."projects" ADD CONSTRAINT "projects_pkey" PRIMARY KEY ("id");

-- ----------------------------
-- Indexes structure for table rework_logs
-- ----------------------------
CREATE INDEX "idx_rework_logs_assigned_uid" ON "public"."rework_logs" USING btree (
  "assigned_uid" "pg_catalog"."int8_ops" ASC NULLS LAST
);
CREATE INDEX "idx_rework_logs_folder_id" ON "public"."rework_logs" USING btree (
  "folder_id" "pg_catalog"."int8_ops" ASC NULLS LAST
);
CREATE INDEX "idx_rework_logs_image_id" ON "public"."rework_logs" USING btree (
  "image_id" "pg_catalog"."int8_ops" ASC NULLS LAST
);

-- ----------------------------
-- Primary Key structure for table rework_logs
-- ----------------------------
ALTER TABLE "public"."rework_logs" ADD CONSTRAINT "rework_logs_pkey" PRIMARY KEY ("id");

-- ----------------------------
-- Uniques structure for table roles
-- ----------------------------
ALTER TABLE "public"."roles" ADD CONSTRAINT "roles_role_name_key" UNIQUE ("role_name");

-- ----------------------------
-- Primary Key structure for table roles
-- ----------------------------
ALTER TABLE "public"."roles" ADD CONSTRAINT "roles_pkey" PRIMARY KEY ("id");

-- ----------------------------
-- Indexes structure for table user_projects
-- ----------------------------
CREATE INDEX "idx_user_projects_project_id" ON "public"."user_projects" USING btree (
  "project_id" "pg_catalog"."int8_ops" ASC NULLS LAST
);
CREATE INDEX "idx_user_projects_role_id" ON "public"."user_projects" USING btree (
  "role_id" "pg_catalog"."int4_ops" ASC NULLS LAST
);

-- ----------------------------
-- Primary Key structure for table user_projects
-- ----------------------------
ALTER TABLE "public"."user_projects" ADD CONSTRAINT "pk_user_projects" PRIMARY KEY ("user_id", "project_id", "role_id");

-- ----------------------------
-- Indexes structure for table users
-- ----------------------------
CREATE INDEX "idx_users_created_by" ON "public"."users" USING btree (
  "created_by" "pg_catalog"."int8_ops" ASC NULLS LAST
);
CREATE INDEX "idx_users_updated_by" ON "public"."users" USING btree (
  "updated_by" "pg_catalog"."int8_ops" ASC NULLS LAST
);
CREATE UNIQUE INDEX "uq_users_device_id_live" ON "public"."users" USING btree (
  "device_id" COLLATE "pg_catalog"."default" "pg_catalog"."text_ops" ASC NULLS LAST
) WHERE is_deleted = false AND device_id IS NOT NULL;

-- ----------------------------
-- Triggers structure for table users
-- ----------------------------
CREATE TRIGGER "trg_users_updated_at" BEFORE UPDATE ON "public"."users"
FOR EACH ROW
EXECUTE PROCEDURE "public"."lwcam_set_updated_at"();

-- ----------------------------
-- Uniques structure for table users
-- ----------------------------
ALTER TABLE "public"."users" ADD CONSTRAINT "users_user_id_key" UNIQUE ("user_id");

-- ----------------------------
-- Primary Key structure for table users
-- ----------------------------
ALTER TABLE "public"."users" ADD CONSTRAINT "users_pkey" PRIMARY KEY ("id");

-- ----------------------------
-- Foreign Keys structure for table capture_boxes
-- ----------------------------
ALTER TABLE "public"."capture_boxes" ADD CONSTRAINT "fk_capture_boxes_device" FOREIGN KEY ("device_id") REFERENCES "public"."devices" ("id") ON DELETE RESTRICT ON UPDATE CASCADE;
ALTER TABLE "public"."capture_boxes" ADD CONSTRAINT "fk_capture_boxes_project" FOREIGN KEY ("project_id") REFERENCES "public"."projects" ("id") ON DELETE RESTRICT ON UPDATE CASCADE;
ALTER TABLE "public"."capture_boxes" ADD CONSTRAINT "fk_capture_boxes_user" FOREIGN KEY ("user_id") REFERENCES "public"."users" ("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- ----------------------------
-- Foreign Keys structure for table capture_folders
-- ----------------------------
ALTER TABLE "public"."capture_folders" ADD CONSTRAINT "fk_capture_folders_box" FOREIGN KEY ("box_id") REFERENCES "public"."capture_boxes" ("box_id") ON DELETE RESTRICT ON UPDATE CASCADE;
ALTER TABLE "public"."capture_folders" ADD CONSTRAINT "fk_capture_folders_device" FOREIGN KEY ("device_id") REFERENCES "public"."devices" ("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- ----------------------------
-- Foreign Keys structure for table capture_images
-- ----------------------------
ALTER TABLE "public"."capture_images" ADD CONSTRAINT "fk_capture_images_device" FOREIGN KEY ("device_id") REFERENCES "public"."devices" ("id") ON DELETE RESTRICT ON UPDATE CASCADE;
ALTER TABLE "public"."capture_images" ADD CONSTRAINT "fk_capture_images_folder" FOREIGN KEY ("folder_id") REFERENCES "public"."capture_folders" ("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- ----------------------------
-- Foreign Keys structure for table devices
-- ----------------------------
ALTER TABLE "public"."devices" ADD CONSTRAINT "fk_devices_country_location" FOREIGN KEY ("country_location_code") REFERENCES "public"."projects" ("country_location_code") ON DELETE RESTRICT ON UPDATE CASCADE;
ALTER TABLE "public"."devices" ADD CONSTRAINT "fk_devices_user" FOREIGN KEY ("user_id") REFERENCES "public"."users" ("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- ----------------------------
-- Foreign Keys structure for table projects
-- ----------------------------
ALTER TABLE "public"."projects" ADD CONSTRAINT "fk_projects_created_by" FOREIGN KEY ("created_by") REFERENCES "public"."users" ("id") ON DELETE SET NULL ON UPDATE CASCADE;
ALTER TABLE "public"."projects" ADD CONSTRAINT "fk_projects_updated_by" FOREIGN KEY ("updated_by") REFERENCES "public"."users" ("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- ----------------------------
-- Foreign Keys structure for table rework_logs
-- ----------------------------
ALTER TABLE "public"."rework_logs" ADD CONSTRAINT "fk_rework_logs_assigned_user" FOREIGN KEY ("assigned_uid") REFERENCES "public"."users" ("id") ON DELETE RESTRICT ON UPDATE CASCADE;
ALTER TABLE "public"."rework_logs" ADD CONSTRAINT "fk_rework_logs_folder" FOREIGN KEY ("folder_id") REFERENCES "public"."capture_folders" ("id") ON DELETE RESTRICT ON UPDATE CASCADE;
ALTER TABLE "public"."rework_logs" ADD CONSTRAINT "fk_rework_logs_image" FOREIGN KEY ("image_id") REFERENCES "public"."capture_images" ("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- ----------------------------
-- Foreign Keys structure for table user_projects
-- ----------------------------
ALTER TABLE "public"."user_projects" ADD CONSTRAINT "fk_user_projects_project" FOREIGN KEY ("project_id") REFERENCES "public"."projects" ("id") ON DELETE CASCADE ON UPDATE CASCADE;
ALTER TABLE "public"."user_projects" ADD CONSTRAINT "fk_user_projects_role" FOREIGN KEY ("role_id") REFERENCES "public"."roles" ("id") ON DELETE CASCADE ON UPDATE CASCADE;
ALTER TABLE "public"."user_projects" ADD CONSTRAINT "fk_user_projects_user" FOREIGN KEY ("user_id") REFERENCES "public"."users" ("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- ----------------------------
-- Foreign Keys structure for table users
-- ----------------------------
ALTER TABLE "public"."users" ADD CONSTRAINT "fk_users_created_by" FOREIGN KEY ("created_by") REFERENCES "public"."users" ("id") ON DELETE SET NULL ON UPDATE CASCADE;
ALTER TABLE "public"."users" ADD CONSTRAINT "fk_users_updated_by" FOREIGN KEY ("updated_by") REFERENCES "public"."users" ("id") ON DELETE SET NULL ON UPDATE CASCADE;
