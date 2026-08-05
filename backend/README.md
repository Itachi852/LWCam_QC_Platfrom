# LWCam FastAPI Backend

当前后端只注册以下接口域：

- `/api/auth/login`、`/api/auth/me`
- `/api/admin/*`：统计、用户管理、QC 项目分配
- `/api/qc/metadata-tasks/*`：Folder 领取、主动释放、Metadata 编辑、逐图打回、审核和图片预览
- `/api/admin/qc-tasks/*`：管理员查看并释放异常占用的 QC 任务

后端直接使用共享 LWCam PostgreSQL Schema。不要运行历史
`database/migrations/001_init_schema.sql`。上线前先执行
`database/migrations/002_users_id_sequence.sql`，再由数据库管理员手动执行
`database/migrations/007_qc_status.sql`；应用启动时不会自动建表。

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
uvicorn app.main:app --reload --port 8080
```

后端运行日志默认写入项目根目录的 `logs/lwcam.log` 和
`logs/uploader.log`。两个文件按 50 MB 轮转并各保留 10 个备份；本地运行时可通过
`LOG_DIR`、`LOG_LEVEL`、`LOG_MAX_BYTES` 和 `LOG_BACKUP_COUNT` 覆盖默认配置。

Folder 图片目录由数据库中的 `folder_path`/`thumbnail_path` 提供，运行账户必须拥有读取权限。
