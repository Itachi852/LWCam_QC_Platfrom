# LWCam Python 前后端分离重构技术方案

版本：v1.0  
日期：2026-07-07  
范围：将现有 Spring Boot 后端重构为 Python 后端，保留并强化 Vue 前端的前后端分离架构。

## 1. 项目现状理解

LWCam 是一个图片/文件夹标注系统，当前代码已经按前后端分离组织：

- `frontend/`：Vue 3 + TypeScript + Vite + Element Plus，负责登录、管理员后台、标注员工作台、QC 工作台。
- `backend/`：Spring Boot 3 + Spring Security + MyBatis Plus，提供 REST API、JWT 鉴权、任务导入、标注、QC、统计等能力。
- `database/`：PostgreSQL 迁移脚本，使用 ENUM、JSONB、触发器和索引。
- `docs/`：已有数据库设计文档。

当前核心业务不是逐张上传标注，而是以文件夹导入为主：

1. 管理员配置任务导入根路径。
2. 系统扫描根路径下的子文件夹，每个子文件夹生成一个任务。
3. 图片文件被索引为 `task_images`，任务进入 `qc`。
4. QC 进行索引审核，通过后进入 `indexing`。
5. 标注员领取 `indexing` 任务，保存整任务级 `annotation_json`，并同步写入每张图片的 `annotations`。
6. QC 驳回索引时任务进入 `rework`，管理员可重新索引。

## 2. 重构目标

- 后端从 Java/Spring Boot 迁移到 Python，保持前端调用契约尽量不变，降低迁移风险。
- 明确前后端边界：前端只通过 HTTP API 和静态文件/图片预览接口访问后端。
- 将接口契约标准化为 OpenAPI，并从 Pydantic 模型生成接口文档。
- 保留 PostgreSQL 作为主数据库，复用现有表结构和迁移成果。
- 支持渐进式替换：Python 后端先兼容现有 `/api` 路径，再逐步优化领域模型和接口。

## 3. 推荐技术栈

### 3.1 后端

| 类型 | 选择 | 说明 |
|---|---|---|
| Web 框架 | FastAPI | 基于 Python 类型提示，天然生成 OpenAPI，适合前后端分离 API。官方文档说明其面向高性能 API，并基于 OpenAPI/JSON Schema。参考：[FastAPI](https://fastapi.tiangolo.com/) |
| ASGI 服务 | Uvicorn + Gunicorn | 本地用 Uvicorn，生产用 Gunicorn 管理多 worker。 |
| 数据校验 | Pydantic v2 | 请求、响应、配置模型统一校验。参考：[Pydantic](https://docs.pydantic.dev/latest/) |
| ORM | SQLAlchemy 2.x | 支持同步/异步 ORM、事务和 PostgreSQL 方言。参考：[SQLAlchemy 2.0](https://docs.sqlalchemy.org/en/20/) |
| 数据库驱动 | psycopg 3 | PostgreSQL 原生驱动，适合 SQLAlchemy 2.x。 |
| 迁移工具 | Alembic | SQLAlchemy 生态标准迁移工具。参考：[Alembic](https://alembic.sqlalchemy.org/en/latest/) |
| 鉴权 | JWT + passlib/bcrypt | 兼容当前 Bearer Token 模式。 |
| 定时任务 | APScheduler | 替代当前 `TaskFolderAutoScanScheduler`。 |
| 图片处理 | Pillow + pillow-heif/可选 tifffile | 生成预览、处理常见图片格式，TIFF 可按实际样本补充。 |
| 测试 | pytest + httpx + pytest-asyncio | API、服务、数据库事务测试。 |
| 代码质量 | ruff + mypy + pyright 可选 | 格式化、lint、类型检查。 |

### 3.2 前端

保留现有栈：

| 类型 | 选择 |
|---|---|
| 框架 | Vue 3 |
| 语言 | TypeScript |
| 构建 | Vite |
| UI | Element Plus |
| 状态 | Pinia |
| 路由 | Vue Router |
| HTTP | Axios |
| 图表 | ECharts |

前端短期不重写，只调整 API 类型和少量路径差异。长期可由后端 OpenAPI 生成 TypeScript client，减少手写接口漂移。

### 3.3 数据库和部署

| 类型 | 选择 |
|---|---|
| 数据库 | PostgreSQL 16，兼容现有 PostgreSQL 15+ 设计 |
| JSON 字段 | JSONB |
| 枚举 | PostgreSQL ENUM，Python 使用 `enum.StrEnum` 映射 |
| 本地编排 | Docker Compose |
| 生产入口 | Nginx 反向代理 `/api` 到 Python，前端静态文件独立部署 |

## 4. 目标架构

```text
浏览器
  |
  | HTTPS
  v
Nginx / 网关
  |-- /            -> frontend dist
  |-- /api/*       -> FastAPI backend
  |-- /api/files/* -> FastAPI 文件流/预览
  v
FastAPI
  |-- routers      API 路由
  |-- services     业务编排和事务
  |-- repositories 数据访问
  |-- schemas      Pydantic 请求/响应模型
  |-- models       SQLAlchemy ORM
  |-- jobs         定时扫描
  v
PostgreSQL + 本地/共享文件系统
```

建议目录：

```text
backend_py/
  app/
    main.py
    core/
      config.py
      security.py
      errors.py
      responses.py
    db/
      session.py
      base.py
      migrations/
    models/
    schemas/
    repositories/
    services/
    routers/
      auth.py
      admin_users.py
      admin_tasks.py
      admin_settings.py
      admin_stats.py
      annotator_tasks.py
      qc_index_tasks.py
      files.py
    jobs/
      folder_scan.py
    utils/
      images.py
      paths.py
  tests/
  pyproject.toml
  alembic.ini
```

## 5. 统一 API 规范

### 5.1 基础路径

- 后端基础路径：`/api`
- 前端 Axios `baseURL` 继续保持 `/api`
- 所有 JSON API 使用 `application/json`
- 图片接口返回二进制流，不包裹统一响应

### 5.2 认证

```http
Authorization: Bearer <jwt>
```

公开接口：

- `POST /api/auth/login`
- `POST /api/auth/register`

其他接口默认需要登录，并根据角色授权。

### 5.3 统一响应

兼容当前前端：

```json
{
  "code": 0,
  "message": "success",
  "data": {}
}
```

分页响应：

```json
{
  "records": [],
  "total": 0,
  "page": 1,
  "size": 10
}
```

错误码：

| code | HTTP | 含义 |
|---:|---:|---|
| 0 | 200 | 成功 |
| 400 | 400 | 请求参数或业务状态错误 |
| 401 | 401 | 未登录或 token 无效 |
| 403 | 403 | 无权限 |
| 404 | 404 | 资源不存在 |
| 409 | 409 | 唯一冲突 |
| 500 | 500 | 服务端错误 |

## 6. 角色和权限

| 角色 | 值 | 权限 |
|---|---|---|
| 超级管理员 | `super_admin` | 用户、任务、设置、统计、导入扫描 |
| 项目管理员 | `project_admin` | 当前实现中与超级管理员同级，后续可按项目隔离 |
| 标注员 | `annotator` | 领取任务、查看本人任务、保存标注 |
| QC | `qc` | 查看 QC 队列、通过/驳回索引任务 |

## 7. 核心数据模型

### 7.1 枚举

| 枚举 | 值 |
|---|---|
| `user_role` | `super_admin`, `project_admin`, `annotator`, `qc` |
| `user_status` | `active`, `disabled` |
| `task_status` | `pending_claim`, `in_progress`, `pending_review`, `review_completed`, `closed`, `pending_index_qc`, `rework`, `indexing`, `qc`, `importing` |
| `task_priority` | `low`, `normal`, `high`, `urgent` |
| `image_status` | `unannotated`, `annotating`, `annotated`, `qc_passed`, `qc_rejected` |
| `qc_result` | `passed`, `rejected` |
| `index_qc_result` | `passed`, `rejected` |

说明：部分旧状态仍在数据库 ENUM 中保留，用于兼容历史数据；新流程主要使用 `importing -> qc -> indexing -> rework/completed`。

### 7.2 表

| 表 | 用途 | 关键字段 |
|---|---|---|
| `users` | 系统用户 | `username`, `display_name`, `password_hash`, `role`, `status` |
| `tasks` | 标注任务/文件夹任务 | `name`, `project_name`, `status`, `priority`, `template_json`, `annotation_json`, `creator_id`, `assignee_id`, `source_folder_path`, `workflow_id` |
| `task_images` | 任务下图片索引 | `task_id`, `image_code`, `original_filename`, `storage_path`, `mime_type`, `file_size`, `status`, `sort_order` |
| `annotations` | 图片标注结果 | `image_id`, `user_id`, `json_data` |
| `qc_records` | 图片级 QC 历史 | `image_id`, `qc_user_id`, `result`, `comment`, `reject_reason` |
| `task_index_qc_records` | 任务索引 QC 历史 | `task_id`, `qc_user_id`, `result`, `comment`, `reject_reason` |
| `system_settings` | 系统配置 | `setting_key`, `setting_value`, `updated_by` |
| `workflow` | 流程阶段 | `code`, `name`, `sort_order` |

### 7.3 关键约束

- `users.username` 唯一。
- `tasks.source_folder_path` 非空时唯一，用于避免重复导入同一文件夹。
- `task_images(task_id, image_code)` 唯一。
- `task_images(task_id, sort_order)` 唯一。
- `annotations.image_id` 唯一，即每张图保留一条当前有效标注。
- 驳回类 QC 记录必须有 `reject_reason`。

## 8. 业务状态流

### 8.1 文件夹导入

```text
scan folder
  -> create task(status=importing)
  -> index images
  -> task(status=qc)
```

### 8.2 索引 QC

```text
qc pass:
  qc -> indexing

qc reject:
  qc -> rework

admin reindex:
  rework -> importing -> qc
```

### 8.3 标注

```text
indexing 且 assignee_id is null
  -> annotator claim
  -> indexing 且 assignee_id = current_user
  -> save annotation_json
  -> task_images.status = annotated
  -> annotations upsert
```

当前代码中没有“提交到标注结果 QC”的独立接口，保存标注仅写入数据和图片状态。Python 重构应先兼容该行为；如要完善闭环，建议新增 `POST /api/annotator/tasks/{id}/submit`，将任务推进到后续 QC 阶段。

## 9. 接口文档

### 9.1 Auth

#### 登录

`POST /api/auth/login`

请求：

```json
{
  "username": "admin",
  "password": "admin123"
}
```

响应 `data`：

```json
{
  "token": "jwt-token",
  "user": {
    "id": 1,
    "username": "admin",
    "displayName": "管理员",
    "role": "super_admin",
    "status": "active",
    "homePath": "/admin/stats"
  }
}
```

#### 注册

`POST /api/auth/register`

请求：

```json
{
  "username": "worker01",
  "displayName": "张三",
  "password": "123456"
}
```

说明：自助注册默认创建 `annotator`。

#### 当前用户

`GET /api/auth/me`

响应 `data`：`UserVO`。

### 9.2 管理员 - 用户

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| GET | `/api/admin/users` | admin | 用户分页 |
| POST | `/api/admin/users` | admin | 新增用户 |
| PUT | `/api/admin/users/{id}` | admin | 更新用户 |
| DELETE | `/api/admin/users/{id}` | admin | 删除用户 |
| PUT | `/api/admin/users/{id}/password` | admin | 重置密码 |

查询参数：

| 参数 | 类型 | 说明 |
|---|---|---|
| `page` | int | 默认 1 |
| `size` | int | 默认 10 |
| `keyword` | string | 用户名/姓名搜索 |
| `role` | string | 角色 |
| `status` | string | 状态 |

新增用户请求：

```json
{
  "username": "qc01",
  "displayName": "QC 一号",
  "password": "123456",
  "role": "qc"
}
```

更新用户请求：

```json
{
  "displayName": "QC 一号",
  "role": "qc",
  "status": "active"
}
```

用户响应 `UserAdminVO`：

```json
{
  "id": 1,
  "username": "qc01",
  "displayName": "QC 一号",
  "role": "qc",
  "status": "active",
  "createdAt": "2026-07-07T09:00:00+08:00"
}
```

### 9.3 管理员 - 任务

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| GET | `/api/admin/tasks` | admin | 任务分页 |
| GET | `/api/admin/tasks/{id}` | admin | 任务详情 |
| POST | `/api/admin/tasks` | admin | 创建任务 |
| PUT | `/api/admin/tasks/{id}` | admin | 更新任务 |
| PUT | `/api/admin/tasks/{id}/close` | admin | 关闭任务 |
| POST | `/api/admin/tasks/{id}/reindex` | admin | rework 任务重新索引 |

任务分页参数：

| 参数 | 类型 | 说明 |
|---|---|---|
| `page` | int | 默认 1 |
| `size` | int | 默认 10 |
| `keyword` | string | 任务名/项目名 |
| `status` | string | 任务状态 |
| `startDate` | date | 创建开始日期 |
| `endDate` | date | 创建结束日期 |

创建/更新任务请求：

```json
{
  "name": "任务 A",
  "projectName": "项目 P",
  "description": "说明",
  "priority": "normal",
  "templateJson": "{\"version\":1,\"fields\":[]}"
}
```

任务响应 `TaskVO`：

```json
{
  "id": 1,
  "name": "任务 A",
  "projectName": "项目 P",
  "description": "说明",
  "status": "indexing",
  "priority": "normal",
  "templateJson": "{\"version\":1,\"fields\":[]}",
  "creatorId": 1,
  "creatorName": "管理员",
  "assigneeId": 2,
  "assigneeName": "标注员",
  "imageCount": 10,
  "annotatedCount": 10,
  "claimedAt": "2026-07-07T09:00:00+08:00",
  "submittedAt": null,
  "createdAt": "2026-07-07T09:00:00+08:00",
  "sourceFolderPath": "D:\\data\\task-a"
}
```

### 9.4 管理员 - 系统设置

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| GET | `/api/admin/settings` | admin | 获取设置 |
| PUT | `/api/admin/settings` | admin | 更新设置 |
| POST | `/api/admin/settings/scan` | admin | 扫描并导入文件夹 |

更新设置请求：

```json
{
  "taskImportRootPath": "D:\\data\\lwcam",
  "autoScanEnabled": true,
  "autoScanIntervalMinutes": 30
}
```

扫描响应 `FolderScanResultVO`：

```json
{
  "scannedFolders": 5,
  "createdTasks": 3,
  "skippedDuplicates": 2,
  "createdTaskNames": ["A", "B", "C"],
  "skippedFolders": ["D", "E"],
  "errors": []
}
```

### 9.5 管理员 - 统计

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| GET | `/api/admin/stats/overview` | admin | 首页统计 |

响应 `StatsOverviewVO`：

```json
{
  "todayNewTasks": 0,
  "todayCompletedTasks": 0,
  "todayQcPassRate": 0.0,
  "totalUsers": 0,
  "totalTasks": 0,
  "pendingClaimTasks": 0,
  "taskTrend": [],
  "taskStatusDistribution": []
}
```

### 9.6 标注员任务

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| GET | `/api/annotator/tasks/indexing` | annotator | 可领取任务 |
| GET | `/api/annotator/tasks/mine` | annotator | 我的 indexing 任务 |
| GET | `/api/annotator/tasks/rework` | annotator | 我的返工任务 |
| GET | `/api/annotator/tasks/{id}` | annotator | 任务详情 |
| POST | `/api/annotator/tasks/{id}/claim` | annotator | 领取任务 |
| PUT | `/api/annotator/tasks/{taskId}/annotation` | annotator | 保存任务级标注 |

保存标注请求：

```json
{
  "data": {
    "name": "张三",
    "id_card": "110101199001011234",
    "address": "北京市..."
  }
}
```

任务详情响应核心字段：

```json
{
  "id": 1,
  "name": "任务 A",
  "projectName": "项目 P",
  "status": "indexing",
  "priority": "normal",
  "templateJson": "{\"version\":1,\"fields\":[]}",
  "annotationJson": "{\"name\":\"张三\"}",
  "imageCount": 2,
  "annotatedCount": 2,
  "sourceFolderPath": "D:\\data\\task-a",
  "workflowCode": "indexing",
  "workflowName": "标注",
  "claimedAt": "2026-07-07T09:00:00+08:00",
  "images": [
    {
      "id": 1,
      "imageCode": "IMG001",
      "originalFilename": "001.jpg",
      "previewUrl": "/api/files/task-images/1/preview",
      "fileSize": 1024,
      "status": "annotated",
      "annotationJson": null
    }
  ]
}
```

### 9.7 QC 索引任务

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| GET | `/api/qc/index-tasks` | qc | 待 QC 任务 |
| GET | `/api/qc/index-tasks/rework` | qc | 返工任务列表 |
| GET | `/api/qc/index-tasks/{id}` | qc | QC 详情 |
| POST | `/api/qc/index-tasks/{id}/pass` | qc | 通过 |
| POST | `/api/qc/index-tasks/{id}/reject` | qc | 驳回 |

通过请求：

```json
{
  "comment": "索引正常"
}
```

驳回请求：

```json
{
  "rejectReason": "图片数量不完整",
  "comment": "请重新检查文件夹"
}
```

QC 任务响应：

```json
{
  "id": 1,
  "name": "任务 A",
  "projectName": "项目 P",
  "status": "qc",
  "sourceFolderPath": "D:\\data\\task-a",
  "imageCount": 2,
  "createdAt": "2026-07-07T09:00:00+08:00",
  "images": [
    {
      "id": 1,
      "imageCode": "IMG001",
      "originalFilename": "001.jpg",
      "previewUrl": "/api/files/task-images/1",
      "fileSize": 1024
    }
  ],
  "lastRejectReason": null
}
```

注意：当前 Java 服务中 QC 图片 `previewUrl` 返回 `"/files/task-images/{id}"`，前端 Axios 基础路径为 `/api` 时可能产生路径不一致。Python 重构建议统一为 `"/api/files/task-images/{id}/preview"` 或前端统一拼接。

### 9.8 文件接口

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| GET | `/api/files/task-images/{id}` | 登录用户 | 返回原图 |
| GET | `/api/files/task-images/{id}/preview` | 登录用户 | 返回预览图 |

响应：二进制流，设置 `Content-Type` 为实际图片 MIME，`Content-Disposition: inline`。

## 10. Python 实现要点

### 10.1 Pydantic 响应模型

```python
from typing import Generic, TypeVar
from pydantic import BaseModel

T = TypeVar("T")

class ApiResponse(BaseModel, Generic[T]):
    code: int = 0
    message: str = "success"
    data: T | None = None

class PageResult(BaseModel, Generic[T]):
    records: list[T]
    total: int
    page: int
    size: int
```

### 10.2 SQLAlchemy 模型策略

- PostgreSQL ENUM 用 `Enum(..., native_enum=True)` 映射，枚举名保持数据库原名。
- JSONB 字段使用 `sqlalchemy.dialects.postgresql.JSONB`，服务层使用 `dict`，响应时按现有前端兼容需求可输出字符串。
- 时间统一使用 timezone-aware `datetime`，默认按数据库 `TIMESTAMPTZ` 存储。
- 事务边界放在 service 层，repository 不自行提交。

### 10.3 鉴权和授权

- 登录校验用户名、密码、账号状态。
- JWT payload 至少包含：`sub=user_id`, `username`, `role`, `exp`。
- FastAPI 依赖：
  - `get_current_user`
  - `require_roles("super_admin", "project_admin")`
  - `require_roles("annotator")`
  - `require_roles("qc")`

### 10.4 文件安全

- `source_folder_path` 必须存规范化绝对路径。
- 读取图片时只从 `task_images.storage_path` 获取，不能接受前端传任意路径。
- 预览接口要校验文件存在、是普通文件、MIME 在白名单中。
- 大图返回使用流式响应，避免一次性读入内存。

### 10.5 定时扫描

- 配置项沿用：
  - `task_import_root_path`
  - `auto_scan_enabled`
  - `auto_scan_interval_minutes`
  - `auto_scan_last_run_at`
- APScheduler job 定期检查配置，启用且到达间隔时执行扫描。
- 扫描过程应加应用级锁，避免手动扫描和定时扫描并发重复导入。

## 11. 迁移计划

### 阶段 1：接口兼容重建

- 搭建 `backend_py/`。
- 建立 FastAPI、SQLAlchemy、Alembic、JWT 基础框架。
- 复刻统一响应、错误码、角色权限。
- 先连接现有 PostgreSQL，不改变表结构。

### 阶段 2：核心接口迁移

迁移顺序：

1. Auth：登录、注册、当前用户。
2. Admin users：用户管理。
3. Admin tasks/settings：任务、设置、扫描、重新索引。
4. Files：图片原图/预览。
5. Annotator tasks：领取、详情、保存标注。
6. QC index tasks：列表、详情、通过、驳回。
7. Stats：统计聚合。

### 阶段 3：前端切换

- 保持 `/api` 前缀不变。
- 本地 Vite 代理从 Java 后端切到 Python 后端。
- 修复图片 `previewUrl` 路径差异。
- 增加基于 OpenAPI 的类型生成或契约测试。

### 阶段 4：业务完善

建议新增但不影响首版兼容：

- `POST /api/annotator/tasks/{id}/submit`：标注完成后显式提交。
- 标注结果 QC 流程：区分索引 QC 和标注 QC。
- annotation 历史版本表，支持驳回后追溯。
- 操作审计日志。
- 导出 JSON/CSV/Excel。

## 12. 测试策略

| 类型 | 工具 | 覆盖 |
|---|---|---|
| 单元测试 | pytest | service 状态流、权限判断、路径规范化 |
| API 测试 | httpx AsyncClient | 登录、用户管理、任务领取、QC 通过/驳回 |
| 数据库测试 | pytest + PostgreSQL test container | ENUM、JSONB、唯一约束、事务回滚 |
| 前端契约 | OpenAPI generated client 或快照 | 字段名、响应包裹、分页 |
| 文件测试 | 临时目录 + Pillow | 扫描导入、预览生成、非法路径拒绝 |

重点用例：

- 重复文件夹不会重复创建任务。
- 仅 `qc` 状态可索引 QC。
- `qc pass` 后任务进入 `indexing`。
- `qc reject` 后任务进入 `rework`。
- 仅 `indexing` 且未领取任务可被领取。
- 标注员不能访问他人任务。
- 禁用用户不能登录。

## 13. 风险和决策

| 风险 | 影响 | 应对 |
|---|---|---|
| Java 与 Python JSON 字段序列化差异 | 前端解析失败 | 首版保持 `templateJson`/`annotationJson` 为字符串，后续再升级为对象 |
| 当前流程缺少标注提交接口 | 标注闭环不完整 | 首版兼容保存逻辑，二期新增 submit |
| 当前 QC 驳回只设置 `tasks.status = rework`，没有同步 `workflow_id = rework` | 返工列表或后续流程可能查不到任务 | Python 重构时将状态和 workflow 作为同一事务更新 |
| 当前标注详情校验只允许 `workflow = indexing`，但前端存在返工任务入口 | 返工任务可能无法进入详情继续处理 | Python 重构时明确返工是否可标注；若可标注，详情和保存接口允许 `indexing/rework` |
| 文件路径依赖 Windows 本地盘 | 部署受限 | 抽象 storage service，后续可换 MinIO |
| PostgreSQL ENUM 扩展不可轻易删除 | 状态清理成本高 | 保留历史枚举，应用层限制有效状态 |
| 定时扫描并发 | 重复任务或状态错乱 | 应用锁 + 数据库唯一约束双保险 |

## 14. 验收标准

- 前端无需大规模改造即可登录并完成管理员、标注员、QC 核心流程。
- `/docs` 或 `/openapi.json` 自动生成完整 API 文档。
- 所有现有 API 路径保持兼容，除已标注的图片 `previewUrl` 差异需要统一。
- Python 后端通过核心 API 测试和数据库状态流测试。
- Docker Compose 可一键启动 PostgreSQL、Python 后端和前端开发环境。
