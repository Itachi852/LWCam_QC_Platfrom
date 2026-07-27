    # LWCam 管理员与 Folder QC 平台

本项目当前只挂载登录、管理员和 QC 三条业务链，直接连接共享 PostgreSQL 中的
`users/projects/user_projects/devices/capture_boxes/capture_folders/capture_images/qc_status/rework_logs`。
一个 `capture_folders` 记录就是一个 QC 任务。通过仍以整个 Folder 为单位；打回时必须选择具体图片，
每张返工图片分别写入一条 `rework_logs`。Metadata 错误由 QC 在审核会话中直接编辑。

## 业务状态

```text
PENDING --领取会话--> REVIEWING --审核完成--> PASS
                                    \-----> REWORK
```

- 外部采集系统把已准备完成的 Folder 写为 `PENDING`。
- 领取状态保存在 `qc_status.status = REVIEWING`；领取期间 Folder 仍保持 `PENDING`。
- 审核结果把 Folder 写为 `PASS` 或 `REWORK`；QC 可主动释放，异常占用由管理员释放。
- 图片打回时 `rework_logs.image_id` 必须有值；多张图片对应多条返工记录。
- QC 直接编辑 Metadata 后，会重新计算当前会话的 `sourceHash`。
- 外部返工流程修复完成后负责把 `REWORK` 重新写为 `PENDING`。
- 每次领取/审核会话写入 `qc_status`；Folder、用户使用正式外键，审核扩展数据保存在 `details JSONB`。

## 数据库准备

先备份目标数据库，并导入共享 LWCam Schema。不要执行旧的
`database/migrations/001_init_schema.sql` 或旧 seed，它们属于历史版本。

只需执行 `users.id` 序列兼容迁移：

```powershell
copy .env.example .env.local
.\scripts\init-db.ps1
```

该脚本不会创建数据库、不会删除 Schema，只执行
`database/migrations/002_users_id_sequence.sql`。首次部署 QC 平台时，还需由数据库管理员手动执行
`database/migrations/007_qc_status.sql`；应用不会自动修改 Schema。管理员和 QC 密码使用 32 位大写 MD5。

## 启动

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
uvicorn app.main:app --reload --port 8080
```

```powershell
cd frontend
npm install
npm run dev
```

后端运行环境必须能直接访问 `capture_folders.folder_path` 和 `thumbnail_path` 中记录的目录。
Docker/NAS 部署时，需要将对应目录挂载到容器内相同路径。`docker-compose.yml` 不再自动执行任何旧 Schema 或 seed。

## 验证

```powershell
cd backend
python -m compileall app

cd ..\frontend
npx vue-tsc --noEmit
npm.cmd run build
```
