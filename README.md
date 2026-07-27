# LWCam Platform

LWCam Platform 是一个面向 Lifewood Folder QC 流程的前后端项目，提供管理员统计、用户管理、QC 任务领取、图片审核、图片处理、Metadata 编辑、通过审核和按图片打回等功能。

## 技术栈

- 前端：Vue 3、Vite、TypeScript、Element Plus、Pinia、Vue Router、Vue I18n、ECharts
- 后端：Python、FastAPI、SQLAlchemy、PostgreSQL
- 数据库：PostgreSQL

## 项目结构

```text
backend/       后端服务
frontend/      前端应用
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
