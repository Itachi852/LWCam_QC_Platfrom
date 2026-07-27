# LWCam Platform

LWCam Platform 是一个面向 Lifewood Folder QC 流程的前后端项目，包含管理员统计、用户管理、QC 任务领取、图片审核、图片处理、Metadata 编辑、通过和按图片打回等功能。

## 技术栈

- 前端：Vue 3、Vite、TypeScript、Element Plus、Pinia、Vue Router、Vue I18n、ECharts
- 后端：Python、FastAPI、SQLAlchemy、PostgreSQL
- 数据库：PostgreSQL

## 项目结构

```text
backend/      后端服务
frontend/     前端应用
scripts/      本地辅助脚本，部分文件已忽略
shared-images/ 本地测试图片目录，已忽略
database/     本地数据库脚本目录，已忽略
docs/         本地文档目录，已忽略
```

## 本地启动

后端：

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8080
```

前端：

```powershell
cd frontend
npm install
npm run dev
```

前端默认通过 Vite 启动。后端默认监听 `8080`。

## 构建验证

```powershell
cd frontend
npm run build
```

```powershell
cd backend
python -m compileall app
```

## GitHub 上传说明

以下内容已通过 `.gitignore` 排除，不建议上传到公开仓库：

- `.env`、`.env.local`
- `.idea/`、`.vscode/`
- `.claude/settings.local.json`
- `frontend/node_modules/`
- `frontend/dist/`
- `backend/.venv/`
- `backend/**/__pycache__/`
- `backend/scripts/`
- `database/`
- `docs/`
- `shared-images/`
- `tecdocs/`
- `scripts/serve_frontend.py`
- `LWCam_database_*.sql`

如果某些文件已经被 Git 跟踪，仅加入 `.gitignore` 不会自动取消跟踪，需要使用：

```powershell
git rm --cached -r <path>
```

## 推送到其他 GitHub 仓库

查看当前远程仓库：

```powershell
git remote -v
```

当前项目已有远程仓库：

```text
origin  https://github.com/Itachi852/LWCam_Platfrom.git
github  https://github.com/Itachi852/LWCam_QC_Platfrom.git
```

如果要推送到新的仓库，可以新增一个远程名，例如 `newrepo`：

```powershell
git remote add newrepo https://github.com/<username>/<repo>.git
git push -u newrepo master
```

如果要把现有 `origin` 改成另一个仓库：

```powershell
git remote set-url origin https://github.com/<username>/<repo>.git
git push -u origin master
```

推送前建议先确认状态并提交：

```powershell
git status
git add .
git commit -m "Update project"
git push
```
