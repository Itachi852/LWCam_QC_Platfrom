# Alembic Migrations

This rewrite initially targets the existing LWCam PostgreSQL schema.

Incremental SQL migrations that must also be applied to an existing local database
are stored in this directory. Module 2 adds only
`010_export_queue_index.sql`; it creates an index and updates a column comment, and
does not create an application table.

When this backend is extracted as an independent project, add Alembic revisions here.

