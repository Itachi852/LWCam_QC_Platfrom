# LWCam Platform

LWCam Platform 是一个面向 Lifewood Folder QC 流程的前后端项目，提供管理员统计、用户管理、QC 任务领取、图片审核、图片处理、Metadata 编辑、通过审核和按图片打回等功能。

## 技术栈

- 前端：Vue 3、Vite、TypeScript、Element Plus、Pinia、Vue Router、Vue I18n、ECharts
- 后端：Python、FastAPI、SQLAlchemy、PostgreSQL
- 数据库：PostgreSQL

## 项目结构

```text
backend/       后端服务
database/      数据库结构与迁移脚本
frontend/      前端应用
shared-images/ Docker 默认挂载的采集图片目录
docker-compose.yml
```

## 使用 Docker 启动

当前 Docker Compose 只启动前端和后端，**不会启动 PostgreSQL，也不会自动创建或迁移数据库**。后端直接连接已有的外部 PostgreSQL 数据库。

### 1. 启动前准备

请先确认：

- 已安装 Docker Desktop，或 Docker Engine 与 Docker Compose。
- 执行 `docker compose version` 能正常显示版本。
- 外部 PostgreSQL 已创建 LWCam 数据库，并且表结构与当前后端模型匹配。
- PostgreSQL 已允许 Docker 容器所在机器访问，数据库端口已在防火墙中放行。
- 采集图片目录已准备好，并且 Docker 有权读取和修改该目录。



### 2. 创建环境变量文件

在项目根目录复制示例文件：

Windows PowerShell：

```powershell
Copy-Item .env.example .env
```

Linux/macOS：

```bash
cp .env.example .env
```

编辑 `.env`，至少检查以下配置：

```dotenv
# 外部 PostgreSQL
DB_HOST=host.docker.internal
DB_PORT=5432
DB_NAME=lwcam
DB_USER=lwcam
DB_PASSWORD=请替换为实际密码

# 生产环境必须替换，长度不能少于 32 个字符
JWT_SECRET=请替换为至少32字符的随机字符串
JWT_EXPIRE_MINUTES=480

# 采集图片在宿主机上的目录
CAPTURE_IMAGE_HOST_PATH=./shared-images

# 上述目录挂载到后端容器后的路径
CAPTURE_IMAGE_CONTAINER_PATH=/data/shared-images

# 对外端口
FRONTEND_PORT=5174
BACKEND_PORT=8080
```

数据库地址按部署位置填写：

| 数据库位置 | `DB_HOST` 示例 |
| --- | --- |
| 数据库运行在 Docker 宿主机 | `host.docker.internal` |
| 数据库运行在局域网其他服务器 | `192.168.1.20` |
| 数据库有可解析的域名 | `postgres.example.internal` |

不要将 `DB_HOST` 写成 `localhost` 或 `127.0.0.1`，除非 PostgreSQL 与后端运行在同一个容器中。对后端容器来说，这两个地址指向容器自身，不是宿主机。

如果密码包含 `#`、空格或 `$` 等字符，建议在 `.env` 中用单引号包裹，例如：

```dotenv
DB_PASSWORD='实际数据库密码'
```

### 3. 配置采集图片目录

Compose 默认将宿主机的 `./shared-images` 挂载为容器内的
`/data/shared-images`。也可以在 `.env` 中配置绝对路径：

Windows：

```dotenv
CAPTURE_IMAGE_HOST_PATH=E:/LWCam/shared-images
CAPTURE_IMAGE_CONTAINER_PATH=/data/shared-images
```

Linux：

```dotenv
CAPTURE_IMAGE_HOST_PATH=/srv/lwcam/shared-images
CAPTURE_IMAGE_CONTAINER_PATH=/data/shared-images
```

数据库中 `capture_folders.folder_path` 和 `capture_folders.thumbnail_path`
保存的路径必须能在后端容器内访问。例如：

```text
/data/shared-images/BOX001/FOLDER001
/data/shared-images/BOX001/FOLDER001_thumbnail
```

数据库中不能保存 `E:\LWCam\...` 这类 Windows 宿主机路径，因为 Linux
容器无法直接识别该路径。宿主机路径只写在
`CAPTURE_IMAGE_HOST_PATH`，数据库记录应使用对应的容器路径。

### 4. 构建并启动

在项目根目录执行：

```powershell
docker compose up -d --build
```

首次启动需要下载 Python、Node.js 基础镜像并安装依赖，耗时取决于网络环境。

查看服务状态：

```powershell
docker compose ps
```

正常情况下，`backend` 和 `frontend` 最终都应显示为 `Up`/`healthy`。
前端会等待后端健康检查通过后再启动。

### 5. 访问服务

- 前端页面：<http://localhost:5174>
- 后端接口文档：<http://localhost:8080/docs>
- 后端 OpenAPI：<http://localhost:8080/api/openapi.json>

如果修改了 `FRONTEND_PORT` 或 `BACKEND_PORT`，请使用 `.env` 中配置的新端口。

### 6. 查看日志

查看全部日志：

```powershell
docker compose logs -f
```

只查看后端：

```powershell
docker compose logs -f backend
```

只查看前端：

```powershell
docker compose logs -f frontend
```

按 `Ctrl+C` 退出日志查看不会停止容器。

### 7. 验证外部数据库连接

服务启动后，可以在后端容器中执行一次简单查询：

```powershell
docker compose exec backend python -c "from sqlalchemy import text; from app.db.session import engine; connection = engine.connect(); print(connection.execute(text('SELECT 1')).scalar()); connection.close()"
```

输出 `1` 表示后端容器能够连接数据库。连接失败时，优先检查
`DB_HOST`、`DB_PORT`、数据库监听地址、用户权限和服务器防火墙。

### 8. 更新与重建

代码或依赖发生变化后重新构建：

```powershell
docker compose up -d --build
```

只重建后端：

```powershell
docker compose up -d --build backend
```

只重建前端：

```powershell
docker compose up -d --build frontend
```

修改 `.env` 后重新创建容器：

```powershell
docker compose up -d --force-recreate
```

### 9. 停止与删除容器

停止服务但保留容器：

```powershell
docker compose stop
```

重新启动已停止的服务：

```powershell
docker compose start
```

停止并删除本项目容器和网络：

```powershell
docker compose down
```

后端预览、QC 工作文件和审计文件保存在 Docker 卷
`lwcam_py_backend_cache` 中，普通 `docker compose down` 不会删除该卷。
如确认这些缓存不再需要，可执行：

```powershell
docker compose down -v
```

`down -v` 会永久删除该 Docker 缓存卷，但不会删除外部 PostgreSQL 数据库，
也不会删除宿主机上通过 `CAPTURE_IMAGE_HOST_PATH` 挂载的采集图片。

### 10. 常见问题

#### 后端日志显示数据库连接被拒绝

- 数据库在宿主机时，使用 `DB_HOST=host.docker.internal`。
- 数据库在其他服务器时，填写服务器真实 IP 或域名。
- 确认 PostgreSQL 的 `listen_addresses`、`pg_hba.conf` 和防火墙允许连接。
- 确认填写的是数据库容器或服务器实际监听端口。

#### 后端显示 `password authentication failed`

检查 `DB_USER`、`DB_PASSWORD` 和 `DB_NAME`。修改 `.env` 后执行：

```powershell
docker compose up -d --force-recreate backend
```

#### 前端一直没有启动

前端依赖后端健康检查。先查看：

```powershell
docker compose ps
docker compose logs --tail=200 backend
```

#### 页面能打开，但图片显示不存在

这通常不是前端问题。检查：

- `CAPTURE_IMAGE_HOST_PATH` 指向的宿主机目录是否存在。
- Docker Desktop 是否有权访问该磁盘或目录。
- 数据库中的 `folder_path`、`thumbnail_path` 是否使用容器路径。
- 容器路径是否与 `CAPTURE_IMAGE_CONTAINER_PATH` 一致。

可以进入后端容器检查挂载内容：

```powershell
docker compose exec backend sh
ls -la /data/shared-images
```

#### 修改端口后无法访问

检查端口是否被其他程序占用，并运行：

```powershell
docker compose ps
```

实际访问的是 `FRONTEND_PORT` 和 `BACKEND_PORT` 对外映射的端口。

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

前端默认通过 Vite 启动，后端默认监听 `8080`。

## 构建验证

前端：

```powershell
cd frontend
npm run build
```

后端：

```powershell
cd backend
python -m compileall app
```

## 主要功能

- 管理员统计看板
- 用户管理
- QC 任务领取与释放
- 单人单任务审核控制
- 图片列表与大图预览
- 图片替换、前插、删除、裁剪、旋转、移动、撤销、重做
- Metadata 右侧栏直接编辑与保存
- Folder 通过
- 按图片打回并填写驳回原因
- 中英文切换
