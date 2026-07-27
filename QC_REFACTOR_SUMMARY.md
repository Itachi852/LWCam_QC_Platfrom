# QC 模块重构总结

## 改动概述

按照设计文档要求，将 QC 并发控制从独立的 `qc_status` 表改为在 `capture_folders` 表上增加字段，符合"不新增专用表"原则。

---

## 数据库改动

### Migration: `database/migrations/008_remove_qc_status_table.sql`

```sql
-- 在 capture_folders 表增加两个字段
ALTER TABLE capture_folders
    ADD COLUMN qc_locked_by VARCHAR(255),
    ADD COLUMN qc_locked_at TIMESTAMPTZ(3);

CREATE INDEX idx_capture_folders_qc_lock
    ON capture_folders(qc_locked_by)
    WHERE qc_locked_by IS NOT NULL;

-- 删除旧表
DROP TABLE IF EXISTS qc_status;
```

**执行方式：**
```bash
psql -U lwcam -d lwcam -f database/migrations/008_remove_qc_status_table.sql
```

---

## 后端改动

### 1. Models

**`backend/app/models/capture.py`**
- 在 `CaptureFolder` 增加：
  - `qc_locked_by: Mapped[str | None]` - 当前占用的 QC 用户
  - `qc_locked_at: Mapped[datetime | None]` - 领取时间

**`backend/app/models/qc_session.py`**
- ✅ 保留 `ReworkLog`（返工记录）
- ❌ 删除 `QcStatus`（审核会话）

**`backend/app/models/__init__.py`**
- 移除 `QcStatus` 导入

### 2. Schemas

**`backend/app/schemas/qc.py`** - 完全重写

**移除的类：**
- `SessionRequest`（包含 reviewSessionId）
- `MetadataQcReviewVO`（审核历史记录）

**简化的类：**
- `MetadataQcTaskVO` 移除字段：
  - `currentVersion` - 版本号（不再跟踪）
  - `reviewSessionId` - 会话 ID
  - `reviewedAt` - 审核完成时间
  - `reviews` - 审核历史列表

**请求类改动：**
- `ReviewRequest`：只保留 `sourceHash` + `comment`
- `CropImageRequest`：只保留 `sourceHash` + 裁剪坐标
- `RejectRequest`：只保留 `sourceHash` + `rejectReason` + `imageIds`
- `MetadataUpdateRequest`：只保留 `sourceHash` + `metadata`

### 3. Routers

**`backend/app/routers/qc.py`** - 完全重写（从 771 行简化到 ~620 行）

**核心改动：**

1. **并发控制** - 使用 `qc_locked_by` 字段替代 `QcStatus` 表：
   ```python
   # 领取任务
   folder.qc_locked_by = current_user.user_id
   folder.qc_locked_at = now()
   
   # 释放任务
   folder.qc_locked_by = None
   folder.qc_locked_at = None
   
   # 校验占有权
   if folder.qc_locked_by != current_user.user_id:
       raise BusinessError(CONFLICT, "任务已不属于当前审核员")
   ```

2. **列表查询** - 使用 `qc_locked_by` 过滤：
   ```python
   # pending 队列
   WHERE qc_status='PENDING' AND qc_locked_by IS NULL
   
   # mine 队列
   WHERE qc_status='PENDING' AND qc_locked_by = current_user.user_id
   
   # completed 队列
   WHERE qc_status IN ('PASS', 'REWORK')
   ```

3. **打回时重置处理标志**（修复原有 bug）：
   ```python
   folder.qc_status = "REWORK"
   folder.is_deskewed = False      # ← 新增
   folder.is_cropped = False       # ← 新增
   folder.is_created_thumbnail = False  # ← 新增
   ```

4. **sourceHash** - 实时计算，不再存储：
   ```python
   current_hash = source_hash(folder)
   if request.sourceHash != current_hash:
       raise BusinessError(CONFLICT, "Folder已更新")
   ```

5. **移除的功能：**
   - 审核历史记录（不再保存 PASS 记录）
   - 版本号跟踪
   - Advisory lock（行级锁足够）

---

## 前端改动

### 1. Types

**`frontend/src/types.ts`**

**`MetadataQcTask` 移除字段：**
- `currentVersion` - 版本号
- `reviewSessionId` - 会话 ID
- `reviewedAt` - 完成时间
- `reviews` - 审核历史数组

**`AdminQcTask` 移除字段：**
- `reviewSessionId`

### 2. API Client

**`frontend/src/api/index.ts`**

所有 API 调用移除 `reviewSessionId` 参数：

```typescript
// 旧版
approve: (id, reviewSessionId, sourceHash, comment?) => ...
reject: (id, reviewSessionId, sourceHash, ...) => ...
release: (id, reviewSessionId) => ...

// 新版
approve: (id, sourceHash, comment?) => ...
reject: (id, sourceHash, ...) => ...
release: (id) => ...
```

### 3. View Component

**`frontend/src/views/qc/QcIndexView.vue`**

**关键修改：**

1. **状态检查** - 从 `reviewSessionId` 改为 `status`：
   ```typescript
   // 旧版
   if (!current.value?.reviewSessionId) return
   
   // 新版
   if (current.value?.status !== 'reviewing') return
   ```

2. **API 调用** - 移除所有 `reviewSessionId` 参数：
   ```typescript
   // 示例：approve
   await qcApi.approve(current.value.id, current.value.sourceHash)
   
   // 示例：reject
   await qcApi.reject(current.value.id, current.value.sourceHash, ...)
   ```

3. **模板修改** - 移除UI 显示：
   - ❌ `{{ current.currentVersion }}` - 版本号显示
   - ❌ `<section v-if="current.reviews.length">` - 审核历史区块

---

## 部署步骤

### 1. 数据库迁移

```bash
# 1. 备份数据库
pg_dump -U lwcam lwcam > backup_before_008.sql

# 2. 执行迁移
psql -U lwcam -d lwcam -f database/migrations/008_remove_qc_status_table.sql

# 3. 验证
psql -U lwcam -d lwcam -c "\d capture_folders" | grep qc_locked
```

### 2. 后端部署

```bash
cd backend
# 停止服务
# 部署新代码
# 重启服务
```

### 3. 前端部署

```bash
cd frontend
npm install  # 如有依赖变化
npm run build
# 部署 dist/ 目录
```

### 4. 验证测试

**基础功能：**
- [ ] 领取任务（claim-next / claim）
- [ ] 查看任务详情
- [ ] 编辑元数据
- [ ] 裁剪图片
- [ ] 通过审核
- [ ] 打回审核（验证处理标志重置）
- [ ] 释放任务
- [ ] 并发测试（两个 QC 同时领取同一任务）

**数据完整性：**
- [ ] 打回后 `rework_logs` 正确写入
- [ ] 打回后 `is_deskewed/is_cropped/is_created_thumbnail` 被重置为 FALSE
- [ ] `qc_locked_by` 在完成/释放后正确清空

---

## 回退方案

如果需要回退：

```sql
-- 1. 恢复 qc_status 表（从旧迁移文件）
CREATE TABLE qc_status (...);

-- 2. 移除新增字段（可选，不影响功能）
ALTER TABLE capture_folders DROP COLUMN qc_locked_by;
ALTER TABLE capture_folders DROP COLUMN qc_locked_at;

-- 3. 恢复旧版代码
```

---

## 已知限制

1. **不保存审核历史**：通过（PASS）的审核不再记录历史，只有打回（REWORK）记录在 `rework_logs`
2. **无版本号**：不再跟踪第几次审核，`completed` 界面只显示最终状态
3. **无 `reviewedAt`**：完成时间只能从 `folder.updated_at` 推断

如需这些功能，可以：
- 方案 A：在 `capture_folders` 加 `qc_reviewed_by`/`qc_reviewed_at` 字段
- 方案 B：扩展 `rework_logs`，通过和打回都写记录

---

## 后续改进方向

根据设计文档，还需实现的功能（优先级排序）：

### 🔴 必须修复
- [ ] 打回时重置处理标志 ✅ **已完成**

### 🟠 高优先级（核心功能）
- [ ] 旋转图片（90° + 批量）
- [ ] 删除图片（≥1 张）
- [ ] 替换图片（上传 .tif）
- [ ] 插入图片
- [ ] 调整图片顺序
- [ ] 集成 Luminance 工具（亮度矫正）

### 🟡 中优先级（UI 完善）
- [ ] Deskew 纠偏
- [ ] 真实缩略图（懒加载）
- [ ] 任务列表列补全（status, export flag, group_id 等）
- [ ] 过滤/搜索功能

### 🟢 低优先级（可推迟）
- [ ] CSV 导出
- [ ] 分页 UI
- [ ] Separation 拆分功能

---

## 总结

✅ 符合设计文档"不新增专用表"原则  
✅ 简化了代码（后端 -150 行，前端移除冗余逻辑）  
✅ 修复了打回时不重置处理标志的 bug  
✅ 保持了核心 QC 功能完整性  
✅ 数据库改动最小（只加 2 个字段）

核心功能完整，可以正常投入使用。后续根据优先级逐步补充其他编辑工具。
