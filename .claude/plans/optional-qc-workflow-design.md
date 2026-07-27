# LWCam 可选 QC 工作流设计方案

## 1. 需求分析

### 1.1 当前状态
根据代码分析，项目已实现：
- ✅ **Workflow 2 步骤 5-6**: Metadata(Indexing) → Metadata(Indexing) QC
  - 标注员领取任务 (`/annotator/tasks/{id}/claim`)
  - 保存标注 (`/annotator/tasks/{id}/annotation`)
  - 提交审核 (`/annotator/tasks/{id}/submit`) → `status=pending_review, workflow_id=qc`
  - QC 审核 (`/qc/index-tasks/{id}/pass|reject`)

### 1.2 需求目标
需要实现以下功能：

**Workflow 1: 传统元数据流程**
```
1. Login (User Management)
2. Scan + Metadata
3. Image Processing
4. Image QC ⭐ [新增]
5. Metadata QC ⭐ [新增]
6. Completed
```

**Workflow 2: AI 辅助标注流程**
```
1. Login (User Management)
2. Scan
3. Image Processing (AI 算法)
4. Image QC ⭐ [新增]
5. Metadata(Indexing)
6. Metadata(Indexing) QC ✅ [已有]
7. Completed
```

**核心需求**:
1. ✅ 让管理员在创建任务时选择 Workflow 1 或 Workflow 2
2. ✅ 新增 Image QC 阶段（图片质量审核）
3. ✅ 新增 Metadata QC 阶段（Workflow 1 专用）
4. ✅ QC 环节可选（管理员可配置跳过 QC）

---

## 2. 架构设计

### 2.1 状态流转设计

#### Workflow 1: 传统元数据流程
```
importing → image_qc → metadata → metadata_qc → completed
              ↓          ↓           ↓
           image_rework metadata_rework
```

#### Workflow 2: AI 辅助标注流程（当前）
```
importing → image_qc → indexing → indexing_qc → completed
              ↓           ↓           ↓
           image_rework  rework
```

#### 可选 QC 模式
当任务配置 `skip_image_qc=true` 或 `skip_metadata_qc=true` 时，自动跳过对应环节：
```
importing → [image_qc?] → indexing/metadata → [metadata_qc?] → completed
```

### 2.2 数据库变更

#### 2.2.1 新增枚举值
```sql
-- 扩展 task_status 枚举
ALTER TYPE task_status ADD VALUE IF NOT EXISTS 'image_qc';
ALTER TYPE task_status ADD VALUE IF NOT EXISTS 'image_rework';
ALTER TYPE task_status ADD VALUE IF NOT EXISTS 'metadata';
ALTER TYPE task_status ADD VALUE IF NOT EXISTS 'metadata_qc';
ALTER TYPE task_status ADD VALUE IF NOT EXISTS 'metadata_rework';
```

#### 2.2.2 tasks 表新增字段
```sql
ALTER TABLE tasks ADD COLUMN workflow_type VARCHAR(32) DEFAULT 'workflow2';
ALTER TABLE tasks ADD COLUMN skip_image_qc BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE tasks ADD COLUMN skip_metadata_qc BOOLEAN NOT NULL DEFAULT false;

COMMENT ON COLUMN tasks.workflow_type IS '工作流类型: workflow1 传统元数据 / workflow2 AI 标注';
COMMENT ON COLUMN tasks.skip_image_qc IS '是否跳过图片 QC';
COMMENT ON COLUMN tasks.skip_metadata_qc IS '是否跳过元数据 QC';
```

#### 2.2.3 新增 image_qc_records 表
```sql
CREATE TABLE IF NOT EXISTS image_qc_records (
    id              BIGSERIAL       PRIMARY KEY,
    image_id        BIGINT          NOT NULL REFERENCES task_images(id) ON DELETE CASCADE,
    qc_user_id      BIGINT          NOT NULL REFERENCES users(id),
    result          qc_result       NOT NULL,
    comment         TEXT,
    reject_reason   TEXT,
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    
    CONSTRAINT ck_image_qc_reject_reason CHECK (
        result != 'rejected' OR (reject_reason IS NOT NULL AND reject_reason != '')
    )
);

CREATE INDEX idx_image_qc_records_image_id ON image_qc_records(image_id, created_at DESC);
CREATE INDEX idx_image_qc_records_qc_user_id ON image_qc_records(qc_user_id, created_at DESC);

COMMENT ON TABLE image_qc_records IS '图片质量 QC 审核记录';
COMMENT ON COLUMN image_qc_records.reject_reason IS '驳回原因（驳回时必填）';
```

#### 2.2.4 workflow 表新增基础数据
```sql
INSERT INTO workflow (id, code, name, sort_order) VALUES
(4, 'image_qc', '图片QC', 4),
(5, 'image_rework', '图片返工', 5),
(6, 'metadata', '元数据录入', 6),
(7, 'metadata_qc', '元数据QC', 7),
(8, 'metadata_rework', '元数据返工', 8)
ON CONFLICT (code) DO NOTHING;
```

---

## 3. API 设计

### 3.1 管理员 - 创建/更新任务

**新增/修改请求字段**:
```json
{
  "name": "任务 A",
  "projectName": "项目 P",
  "workflowType": "workflow2",
  "skipImageQc": false,
  "skipMetadataQc": false,
  "templateJson": {...}
}
```

**字段说明**:
- `workflowType`: `"workflow1"` 或 `"workflow2"`，默认 `"workflow2"`
- `skipImageQc`: 是否跳过图片 QC，默认 `false`
- `skipMetadataQc`: 是否跳过元数据 QC，默认 `false`

### 3.2 Image QC 接口 (新增)

**基础路径**: `/api/qc/image-tasks`

#### 3.2.1 列表接口
```
GET /api/qc/image-tasks
```
查询条件: `status=image_qc, workflow_id=workflow_id('image_qc')`

#### 3.2.2 详情接口
```
GET /api/qc/image-tasks/{task_id}
```

#### 3.2.3 通过接口
```
POST /api/qc/image-tasks/{task_id}/pass
```
Request:
```json
{
  "comment": "图片质量正常"
}
```

逻辑:
```python
# 1. 校验 task.status == 'image_qc'
# 2. 更新所有图片状态为 unannotated
# 3. 写入 image_qc_records (result='passed')
# 4. 根据 workflow_type 决定下一状态
if task.workflow_type == 'workflow1':
    task.status = 'metadata'
    task.workflow_id = workflow_id('metadata')
elif task.workflow_type == 'workflow2':
    task.status = 'indexing'
    task.workflow_id = workflow_id('indexing')
```

#### 3.2.4 驳回接口
```
POST /api/qc/image-tasks/{task_id}/reject
```
Request:
```json
{
  "rejectReason": "图片模糊，需重新扫描",
  "comment": "请重新处理"
}
```

逻辑:
```python
# 1. 校验 task.status == 'image_qc'
# 2. 写入 image_qc_records (result='rejected')
# 3. 更新任务状态
task.status = 'image_rework'
task.workflow_id = workflow_id('image_rework')
```

### 3.3 Metadata (Workflow 1 专用，新增)

**基础路径**: `/api/annotator/metadata-tasks`

类似当前 `/api/annotator/tasks`，但用于 Workflow 1 的元数据录入阶段。

#### 3.3.1 可领取列表
```
GET /api/annotator/metadata-tasks/claimable
```
查询条件: `status=metadata, workflow_type='workflow1', assignee_id IS NULL`

#### 3.3.2 我的任务
```
GET /api/annotator/metadata-tasks/mine
```

#### 3.3.3 领取任务
```
POST /api/annotator/metadata-tasks/{task_id}/claim
```

#### 3.3.4 保存元数据
```
PUT /api/annotator/metadata-tasks/{task_id}/metadata
```
Request:
```json
{
  "data": {
    "name": "张三",
    "id_card": "110101199001011234"
  }
}
```

#### 3.3.5 提交审核
```
POST /api/annotator/metadata-tasks/{task_id}/submit
```

逻辑:
```python
# 1. 校验必填字段
# 2. 更新 task.annotation_json
# 3. 判断是否跳过 Metadata QC
if task.skip_metadata_qc:
    task.status = 'review_completed'
    task.workflow_id = workflow_id('completed')
else:
    task.status = 'metadata_qc'
    task.workflow_id = workflow_id('metadata_qc')
```

### 3.4 Metadata QC (Workflow 1 专用，新增)

**基础路径**: `/api/qc/metadata-tasks`

#### 3.4.1 列表接口
```
GET /api/qc/metadata-tasks
```
查询条件: `status=metadata_qc, workflow_id=workflow_id('metadata_qc')`

#### 3.4.2 通过接口
```
POST /api/qc/metadata-tasks/{task_id}/pass
```
逻辑:
```python
task.status = 'review_completed'
task.workflow_id = workflow_id('completed')
```

#### 3.4.3 驳回接口
```
POST /api/qc/metadata-tasks/{task_id}/reject
```
逻辑:
```python
task.status = 'metadata_rework'
task.workflow_id = workflow_id('metadata_rework')
```

### 3.5 修改现有标注员提交接口

**修改**: `POST /api/annotator/tasks/{task_id}/submit`

```python
# 现有逻辑末尾改为：
if task.skip_metadata_qc:
    # 跳过 QC，直接完成
    for image in task.images:
        image.status = "qc_passed"
    task.status = "review_completed"
    task.workflow_id = require_workflow_id(db, "completed")
else:
    # 进入 QC 流程（现有逻辑）
    for image in task.images:
        image.status = "annotated"
    task.status = "pending_review"
    task.workflow_id = require_workflow_id(db, "qc")
```

---

## 4. 前端修改

### 4.1 管理员 - 任务创建/编辑表单
新增字段：
```vue
<el-form-item label="工作流类型">
  <el-radio-group v-model="form.workflowType">
    <el-radio value="workflow1">Workflow 1 - 传统元数据流程</el-radio>
    <el-radio value="workflow2">Workflow 2 - AI 辅助标注流程</el-radio>
  </el-radio-group>
</el-form-item>

<el-form-item label="QC 配置">
  <el-checkbox v-model="form.skipImageQc">跳过图片 QC</el-checkbox>
  <el-checkbox v-model="form.skipMetadataQc">跳过元数据 QC</el-checkbox>
</el-form-item>
```

### 4.2 QC 工作台 - 新增 Image QC 标签页
```vue
<el-tabs v-model="activeTab">
  <el-tab-pane label="图片 QC" name="image-qc"></el-tab-pane>
  <el-tab-pane label="标注 QC" name="metadata-qc"></el-tab-pane>
</el-tabs>
```

### 4.3 标注员工作台 - 根据 workflow_type 区分
- Workflow 1: 显示"元数据录入"任务
- Workflow 2: 显示"标注"任务

---

## 5. 实现计划

### Phase 1: 数据库迁移 (1-2 hours)
1. ✅ 创建迁移脚本 `002_optional_qc_workflow.sql`
2. ✅ 添加新枚举值
3. ✅ 添加 tasks 表字段
4. ✅ 创建 image_qc_records 表
5. ✅ 插入 workflow 基础数据

### Phase 2: 后端 Models & Schemas (2-3 hours)
1. ✅ 更新 `app/models/enums.py` 添加新状态
2. ✅ 创建 `app/models/image_qc_record.py`
3. ✅ 更新 `app/models/task.py` 添加新字段
4. ✅ 创建 `app/schemas/image_qc.py`
5. ✅ 创建 `app/schemas/metadata.py`
6. ✅ 更新 `app/schemas/admin.py` 添加工作流配置字段

### Phase 3: 后端 API - Image QC (3-4 hours)
1. ✅ 创建 `app/routers/image_qc.py`
2. ✅ 实现列表、详情、通过、驳回接口
3. ✅ 添加状态流转逻辑
4. ✅ 在 `main.py` 注册路由

### Phase 4: 后端 API - Metadata (Workflow 1) (3-4 hours)
1. ✅ 创建 `app/routers/metadata.py`
2. ✅ 实现元数据录入相关接口
3. ✅ 创建 `app/routers/metadata_qc.py`
4. ✅ 实现元数据 QC 接口

### Phase 5: 修改现有逻辑 (2-3 hours)
1. ✅ 修改 `app/routers/admin.py` 创建任务接口
2. ✅ 修改 `app/routers/annotator.py` 提交接口支持跳过 QC
3. ✅ 修改文件夹扫描逻辑支持 workflow_type 配置
4. ✅ 更新状态流转逻辑

### Phase 6: 前端适配 (4-6 hours)
1. ✅ 修改任务创建/编辑表单
2. ✅ 新增 Image QC 页面
3. ✅ 新增 Metadata QC 页面 (Workflow 1)
4. ✅ 修改标注员工作台显示逻辑
5. ✅ 更新路由和权限配置

### Phase 7: 测试 (2-3 hours)
1. ✅ Workflow 1 完整流程测试
2. ✅ Workflow 2 完整流程测试
3. ✅ 跳过 QC 功能测试
4. ✅ 状态流转边界测试
5. ✅ 权限验证测试

---

## 6. 关键决策

### 6.1 状态命名
- `image_qc` vs `pending_image_qc`？ → 选择 `image_qc`（简洁）
- `metadata` vs `metadata_entry`？ → 选择 `metadata`（与 Workflow 2 的 `indexing` 对称）

### 6.2 QC 记录表分离
- Image QC 使用独立的 `image_qc_records` 表
- Metadata QC (Workflow 1) 复用现有 `qc_records` 表
- 理由：Image QC 关注图片质量，语义不同；Metadata QC 与当前 Indexing QC 类似

### 6.3 向后兼容
- 现有任务默认 `workflow_type='workflow2'`
- 现有任务默认 `skip_image_qc=false, skip_metadata_qc=false`
- 现有 API 路径保持不变，新增独立路径

### 6.4 Workflow 选择时机
- **创建任务时选择**：管理员手动创建任务时指定
- **文件夹扫描时配置**：系统设置中配置默认 workflow_type

---

## 7. 风险评估

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| 枚举扩展失败 | 部署失败 | 使用 `ADD VALUE IF NOT EXISTS`，先在测试环境验证 |
| 状态流转错误 | 任务卡死 | 完善单元测试，覆盖所有状态转换路径 |
| 前端路由冲突 | 页面无法访问 | 使用命名空间区分 (image-qc, metadata-qc) |
| 权限验证遗漏 | 安全风险 | 所有新接口必须添加角色依赖注入 |
| 现有流程破坏 | 生产事故 | 保持现有 API 不变，新功能使用新路径 |

---

## 8. 验收标准

### 8.1 功能完整性
- ✅ 管理员可以创建 Workflow 1 和 Workflow 2 任务
- ✅ 管理员可以配置跳过 Image QC 或 Metadata QC
- ✅ Image QC 员可以审核图片质量
- ✅ Metadata QC 员可以审核元数据（Workflow 1）
- ✅ 跳过 QC 时任务自动流转到下一阶段

### 8.2 兼容性
- ✅ 现有 Workflow 2 流程不受影响
- ✅ 现有任务可以正常完成
- ✅ 现有 API 契约保持不变

### 8.3 性能
- ✅ 列表查询响应时间 < 500ms
- ✅ QC 审核操作响应时间 < 200ms

### 8.4 文档
- ✅ API 文档自动生成（FastAPI /docs）
- ✅ 数据库变更记录在迁移脚本注释中
- ✅ 状态流转图更新

---

## 9. 下一步行动

立即开始实现 Phase 1：
1. 创建数据库迁移脚本
2. 在测试环境执行验证
3. 更新 ORM 模型

预计总工时：**20-28 小时**
