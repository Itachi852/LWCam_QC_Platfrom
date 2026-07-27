# LWCam 数据库设计（PostgreSQL）

## 1. 设计原则

- 数据库：**PostgreSQL 15+**
- 主键：`BIGSERIAL`（自增 bigint）
- 时间字段：`TIMESTAMPTZ`，默认 `NOW()`
- 软删除：首版不做，用 `status` 表达业务状态
- 枚举：使用 PostgreSQL `ENUM`，便于约束与可读性
- 动态标注字段：`JSONB` 存储模板与标注结果

## 2. ER 关系

```text
users ──┬──< tasks (creator_id)
        ├──< tasks (assignee_id)
        ├──< annotations (user_id)
        └──< qc_records (qc_user_id)

tasks ──┬──< task_images
        └── template_json (快照，创建任务时固化)

task_images ──┬──< annotations
              └──< qc_records
```

## 3. 枚举定义

### user_role（用户角色）

| 值 | 说明 |
|----|------|
| `super_admin` | 超级管理员 |
| `project_admin` | 项目管理员 |
| `annotator` | 标注员 |
| `qc` | QC 审核员 |

### user_status（账号状态）

| 值 | 说明 |
|----|------|
| `active` | 启用 |
| `disabled` | 禁用 |

### task_status（任务状态）

| 值 | 说明 | 流转 |
|----|------|------|
| `pending_claim` | 待领取 | 创建后默认 |
| `in_progress` | 标注中 | 标注员领取后 |
| `pending_review` | 待审核 | 标注员提交后 |
| `review_completed` | 审核完成 | 全部图片 QC 通过 |
| `closed` | 已关闭 | 管理员手动关闭 |

### image_status（图片状态）

| 值 | 说明 |
|----|------|
| `unannotated` | 未标注 |
| `annotating` | 标注中 |
| `annotated` | 已标注（待 QC） |
| `qc_passed` | 审核通过 |
| `qc_rejected` | 审核驳回 |

### task_priority（任务优先级）

| 值 | 说明 |
|----|------|
| `low` | 低 |
| `normal` | 普通 |
| `high` | 高 |
| `urgent` | 紧急 |

### qc_result（审核结果）

| 值 | 说明 |
|----|------|
| `passed` | 通过 |
| `rejected` | 驳回 |

## 4. 表结构说明

### 4.1 users（用户表）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | BIGSERIAL | 主键 |
| username | VARCHAR(64) | 登录名，唯一 |
| display_name | VARCHAR(128) | 姓名/显示名 |
| password_hash | VARCHAR(255) | BCrypt 哈希，不存明文 |
| role | user_role | 角色 |
| status | user_status | 账号状态 |
| created_at | TIMESTAMPTZ | 创建时间 |
| updated_at | TIMESTAMPTZ | 更新时间 |

### 4.2 tasks（任务表）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | BIGSERIAL | 主键 |
| name | VARCHAR(200) | 任务名称 |
| project_name | VARCHAR(200) | 项目名称 |
| description | TEXT | 描述 |
| status | task_status | 任务状态 |
| priority | task_priority | 优先级 |
| template_json | JSONB | 标注模板快照 |
| creator_id | BIGINT | 创建人 → users.id |
| assignee_id | BIGINT | 当前领取人（可空） |
| claimed_at | TIMESTAMPTZ | 领取时间 |
| submitted_at | TIMESTAMPTZ | 提交审核时间 |
| image_count | INT | 图片总数（冗余，便于列表查询） |
| annotated_count | INT | 已标注数（冗余） |
| created_at | TIMESTAMPTZ | 创建时间 |
| updated_at | TIMESTAMPTZ | 更新时间 |

**template_json 示例：**

```json
{
  "version": 1,
  "fields": [
    {
      "key": "name",
      "label": "姓名",
      "type": "text",
      "required": true
    },
    {
      "key": "id_card",
      "label": "身份证",
      "type": "text",
      "required": true
    },
    {
      "key": "address",
      "label": "地址",
      "type": "textarea",
      "required": false
    },
    {
      "key": "gender",
      "label": "性别",
      "type": "select",
      "options": ["男", "女"]
    }
  ]
}
```

**支持的 field.type：** `text` | `textarea` | `number` | `date` | `select` | `radio` | `checkbox`

### 4.3 task_images（任务图片表）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | BIGSERIAL | 主键 |
| task_id | BIGINT | 所属任务 |
| image_code | VARCHAR(64) | 图片编号，如 IMG001 |
| original_filename | VARCHAR(500) | 原始文件名 |
| storage_path | VARCHAR(1000) | 对象存储路径（MinIO key） |
| thumbnail_path | VARCHAR(1000) | 缩略图路径（可空） |
| mime_type | VARCHAR(100) | 如 image/jpeg |
| file_size | BIGINT | 字节数 |
| width | INT | 宽度像素（可空） |
| height | INT | 高度像素（可空） |
| status | image_status | 图片状态 |
| sort_order | INT | 排序序号，从 1 开始 |
| created_at | TIMESTAMPTZ | 创建时间 |
| updated_at | TIMESTAMPTZ | 更新时间 |

约束：`UNIQUE(task_id, image_code)`、`UNIQUE(task_id, sort_order)`

### 4.4 annotations（标注结果表）

每张图片保留**当前有效**的一条标注记录；驳回后重新标注时 **UPDATE** 同一条记录（历史版本留待后续扩展）。

| 字段 | 类型 | 说明 |
|------|------|------|
| id | BIGSERIAL | 主键 |
| image_id | BIGINT | 图片 → task_images.id |
| user_id | BIGINT | 标注员 → users.id |
| json_data | JSONB | 标注内容 |
| created_at | TIMESTAMPTZ | 首次保存时间 |
| updated_at | TIMESTAMPTZ | 最后更新时间 |

约束：`UNIQUE(image_id)` — 一图一条当前标注

**json_data 示例：**

```json
{
  "name": "张三",
  "id_card": "110101199001011234",
  "address": "北京市朝阳区..."
}
```

### 4.5 qc_records（QC 审核记录表）

每次审核（通过或驳回）插入一条记录，支持审计与统计。

| 字段 | 类型 | 说明 |
|------|------|------|
| id | BIGSERIAL | 主键 |
| image_id | BIGINT | 图片 |
| qc_user_id | BIGINT | 审核员 |
| result | qc_result | 通过 / 驳回 |
| comment | TEXT | 审核意见 |
| reject_reason | TEXT | 驳回原因（驳回时必填，应用层校验） |
| created_at | TIMESTAMPTZ | 审核时间 |

## 5. 索引策略

| 表 | 索引 | 用途 |
|----|------|------|
| users | username | 登录查询 |
| users | role, status | 用户列表筛选 |
| tasks | status, priority, created_at | 任务列表、领取池 |
| tasks | assignee_id | 我的任务 |
| tasks | creator_id | 按创建人查 |
| task_images | task_id, status | 任务内图片列表 |
| task_images | task_id, image_code | 图片编号搜索 |
| annotations | user_id | 标注员统计 |
| annotations | json_data GIN | 后续按字段搜索（可选） |
| qc_records | image_id, created_at | 审核历史 |
| qc_records | qc_user_id, created_at | QC 员统计 |

## 6. 状态流转

### 任务状态

```text
pending_claim → in_progress → pending_review → review_completed
      ↑              ↑              |
      |              └── qc_rejected 驳回后回退
      └──────────────────────────────┘
任意状态 → closed（管理员关闭）
```

### 图片状态

```text
unannotated → annotating → annotated → qc_passed
                              ↓
                         qc_rejected → annotating（重新标注）
```

## 7. 冗余字段维护

`tasks.image_count`、`tasks.annotated_count` 由应用层在以下时机更新：

- 上传/删除图片 → 更新 `image_count`
- 图片标注完成（status → annotated）→ `annotated_count + 1`
- QC 驳回（status → qc_rejected）→ `annotated_count - 1`（若计为未完成）

也可用数据库触发器维护，首版建议应用层维护，逻辑更清晰。

## 8. 文件说明

```
database/
├── migrations/
│   └── 001_init_schema.sql    # 建库建表、枚举、索引、触发器
└── seed/
    └── 001_init_admin.sql     # 初始化超级管理员（需替换密码哈希）
```

## 9. 本地启动

### 方式一：使用本机已安装的 PostgreSQL（推荐）

1. 复制环境配置：

```powershell
copy .env.example .env.local
# 编辑 .env.local 填写 DB_USER、DB_PASSWORD
```

2. 执行初始化脚本（自动建库、建表、种子数据）：

```powershell
.\scripts\init-db.ps1
```

默认连接串（以 `.env.local` 为准）：

```
postgresql://postgres@localhost:5432/lwcam
```

开发用管理员：`admin` / `admin123`

### 方式二：Docker（可选）

若未安装本机 PostgreSQL，可使用 docker-compose：

```bash
docker compose up -d postgres
```

Docker 模式使用独立账号 `lwcam/lwcam`，与本机配置互不影响。
