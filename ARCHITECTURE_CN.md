# LW Suite - 系统架构

本文说明 `LW Suite` 中各组成部分如何协同工作。请先阅读本文，再阅读各应用的技术文档：

- `LWCAM/TECHNICAL_DOCUMENTATION.md` - 采集、传输与图片处理工位。
- `LWCamAdmin/TECHNICAL_DOCUMENTATION.md` - 管理控制台（用户、项目、设备、工位配置）。

接手团队需要建设 **QC + 图片修复 + 返工**、**导出（TIF/CSV/ZIP）** 和 **上传（Ingestion）** 模块。这些模块已经在以下文档中定义（都位于本文件夹）：

- `MODULE_1_QC_REWORK_DESIGN.txt` - QC 审核、应用内图片修复、返工、拆分。
- `MODULE_2_EXPORT_DESIGN.txt` - TIF（adobe_deflate）、两个 CSV、ZIP、Group ID。
- `MODULE_3_UPLOAD_DESIGN.txt` - 将导出 ZIP 推送到 ingest 后端。
- `METADATA_AND_EXPORT_CONTRACT.txt` - 模块 1 和模块 2 必须实现的权威元数据字段、Group ID 命名、ZIP 结构、CSV 字段契约。
- `Luminance Correction/` - 模块 1 集成的已提取图片修复工具。
- `Uploader/` - 模块 3 参考的现有 Python 上传工具。

这些模块的关键决策已经锁定：它们作为每工位可配置阶段运行在 **LWCAM 内部**（由 `lwcam_node_config.json` 开关控制），复用 **共享云端 schema**（`capture_folders` = task，`capture_images` = page，`rework_logs`），**不新增 QC 专用表**，并且 **由数据库驱动**（不从 NAS 重新导入）。返工模型刻意保持简单：**reject = 页面必须重新拍摄**；其他所有问题都在 QC 内修复，然后 Folder 通过。云端 schema 已经包含这些模块要写入的状态字段和 `rework_logs`。

---

## 1. 系统做什么

这是一个文档数字化流水线。实体文件由 Android 手机拍摄，Windows PC 拉取图片，将图片按 box 和 folder 组织并录入元数据，传输到 NAS/本地目标位置，然后进行图片处理（纠偏、裁剪、缩略图）、质量检查、转换，最终进入下游档案系统。每个阶段都会把结果记录到共享 PostgreSQL 数据库中，因此任意工位都能看到任意 Folder 的状态。

```text
Android phone
  -> ADB pull
  -> LWCAM capture station
  -> copy/verify to NAS or destination folders
  -> LWIP watches marker and performs deskew/crop/thumbnail
  -> PostgreSQL (Aliyun RDS) is the source of truth
  -> future phases: QC -> Export/TIF -> Ingestion

LWCam Admin writes users/projects/devices/settings.
LWCAM stations write capture and pipeline results through outbox rows.
```

## 2. 三个程序

| Program | Package | Role | Platform |
|---|---|---|---|
| **LWCAM** | `lwcam` | 采集、传输，以及可选的图片处理监管。面向操作员的应用。 | Flutter Windows 桌面端 |
| **LWCam Admin** | `lwcam_admin` | 管理用户、项目、设备、元数据模板、应用设置、每工位配置。它是 users/projects/settings 的唯一写入者。 | Flutter Windows 桌面端 |
| **LWIP** | Python 3.13 | 无界面的纠偏/裁剪/缩略图文件夹监听器。打包在 LWCAM 中并由 LWCAM 监管；不会由人工直接启动。 | Python（OpenCV/Pillow） |

LWCAM 和 LWCam Admin 是 **独立 fork 式 Dart 包**，不是共享库。它们有意手工重复少量文件（`node_config.dart`、`super_admin.dart`、`password_hasher.dart`、`pg_client.dart`、theme 文件），并手动保持字节级兼容。当修改共享契约（例如 `NodeConfig` 字段或 PG 语句形状）时，两边都要改。没有构建步骤会强制这一点，这是必须遵守的手工纪律，各应用文档中也会强调。

它们拆成两个应用，是因为受众和信任级别不同：LWCAM 运行在每台采集 PC 上，由采集人员操作；LWCam Admin 只运行在少数主管 PC 上。拆分后，采集工位没有任何代码路径可以编辑用户或项目。

## 3. 流水线阶段（心智模型）

流水线由一系列 **阶段** 组成。阶段是一个工作单元：读取某些 Folder，执行操作，并把结果记录到 Folder 行上。阶段在 `lwcam_node_config.json` 中按工位开启/关闭（见第 6 节），一台物理 PC 可以运行一个或多个阶段。阶段之间只通过数据库协调，不直接互相调用。

| Phase | Runs in | `capture_folders` 上的状态字段 | 当前状态 |
|---|---|---|---|
| Capture + Transfer | LWCAM | box `status` OPEN -> TRANSFERRED；`transferred_to`、`transfer_*_at` | **已建成** |
| Image processing | LWCAM（监管 LWIP） | `is_deskewed`、`is_cropped`、`is_created_thumbnail`、`folder_path`、`thumbnail_path`，并重置 `qc_status='PENDING'` | **已建成** |
| QC + Rework | LWCAM（`qcEnabled`） | `qc_status` PASS/REWORK/PENDING；生成 `group_id`；`rework_logs`；ReCapture 时可重置处理标记（见第 4.1 节） | **已定义** - `MODULE_1` |
| Export / TIF | LWCAM（export worker，`qcEnabled` 工位） | `is_tif_converted`、`is_exported`、`exported_time`；导出时写入 `group_id` | **已定义** - `MODULE_2` |
| Upload (Ingestion) | LWCAM（`uploadEnabled`，监管 Python Uploader） | `is_ingested`、`ingested_time` | **已定义** - `MODULE_3` |

Client-QC 字段（`client_qc_status`、`client_rework`）保留给未来的客户端返工重新导入阶段，目前不在范围内。

**这些模块都应按同一扩展模式实现。** 每个模块新增：`NodeConfig` 和 Station Setup 中的工位开关；LWCAM 中读取数据库队列的 service（QC: `capture_folders WHERE qc_status='PENDING'`；Export: `WHERE qc_status='PASS' AND NOT is_exported`；Upload: `WHERE is_exported AND NOT is_ingested`）；并通过与图片处理阶段相同的 **outbox -> sink** 机制写入结果（第 5 节），用自然键解析云端 id。

不要创造第二条写入路径；`pg_sync_sink.dart` 中的 `capture_folder_processing` 实体是新建 `qc_verdict`、`rework_log`、`capture_folder_export`、`capture_folder_ingest` 的工作示例。QC 不需要新表；已有状态字段、`rework_logs` 和 LWCAM 本地 audit log 已足够。Export 的序列是 PG SEQUENCE 对象，不是表。见 `MODULE_1` 第 2 节。

## 4. 云数据库（PostgreSQL，事实来源）

一个 PostgreSQL 数据库（`lw_db`，Aliyun RDS Singapore）保存权威状态。schema 位于 `LWCam Workflow & SQL update/LWCam_database_20260720.sql`，该文件是唯一权威。它大量使用 `CREATE TABLE IF NOT EXISTS`；项目约定是在 schema 变化时 **删除并重建**（研发阶段，没有已交付安装，也没有需要保留的迁移历史）。

### 表

- **`users`** - 账号。`user_id`（用户名）是自然键。`roles` 是逗号拼接列表（`admin`、`capture`；SuperAdmin 仅存在于 Admin 应用）。`password` 是 bcrypt hash。`device_id` 将采集账号绑定到一台手机。`roles` 会原样读回，**不会** 从 `user_projects` 重新推导，因此零项目 admin 仍保留角色。
- **`projects`** - `project_key`（VARCHAR(64)，一次写入，`'p'` + base36）是 **所有引用使用的稳定身份**。`project_id` 是可人工编辑标签，可自由重命名，绝不要用它解析身份。`country_location_code` 将设备绑定到项目（FK）。`template`（JSONB）是元数据录入表单。
- **`devices`** - 每台采集手机一行（`device_id` = `SAX##`）。通过 `country_location_code` 绑定项目（结构性 FK），设备只能采集到绑定项目。只有 LWCam Admin 可以重新绑定。
- **`user_projects`** - 用户 -> 项目 -> 角色的多对多表。下游工具会读取它；认证角色来自 `users.roles`。
- **`capture_boxes`** - box（同项目内 `box_name` 唯一）。`status` 为 OPEN/TRANSFERRED/REWORK。传输时填写 `transferred_to`、`transfer_start_at`、`transfer_end_at`。
- **`capture_folders`** - 流水线核心，每个已录入 Folder 一行。包含所有元数据（`cover_tag`、`title`、`volume`、日期、`archival_ref_no`、`record_type`、`place`、`language`、`record_custodian`、采集操作员字段、`digitizing_entity`），以及每个阶段的状态字段。`UNIQUE(box_id, folder_seq)` 是 box 内自然键。字段归属规则见第 4.1 节，非常重要。
- **`capture_images`** - 每张图片一行（`UNIQUE(folder_id, image_name)`）。`file_format` 限制为 jpg/jpeg/tif/tiff/png。
- **`rework_logs`** - 为 Rework 阶段保留。每条返工请求一行，可按 Folder 或图片范围记录，包含 `rework_type`、`rework_status`、`rework_comments`。目前尚无写入者。
- **`app_settings`** - LWCam Admin 拥有的 key/value 存储（元数据录入开关、快门配置、默认临时密码 hash、SuperAdmin override hash）。LWCAM 只读拉取。
- **`roles`** - `user_projects.role_id` 使用的角色名注册表。

`updated_at` trigger（`lwcam_set_updated_at`）会在 `users`、`projects`、`capture_boxes`、`capture_folders`、`app_settings` 每次 UPDATE 时打时间戳，应用代码不手动设置 `updated_at`。

### 4.1 `capture_folders` 字段归属（关键）

不同阶段拥有不同字段。越界写入会破坏其他团队数据：

| Columns | Owner | Written via |
|---|---|---|
| metadata（`cover_tag`、`title` 等）、`folder_name`、`folder_seq` | Capture（LWCAM）；QC 可修正元数据（Metadata Rework） | folder upsert；QC metadata write |
| `is_deskewed`、`is_cropped`、`is_created_thumbnail`、`folder_path`、`thumbnail_path`，以及 `qc_status='PENDING'` 重置 | Image processing（LWCAM） | `folderProcessingUpdateSql`。**例外：** QC 在标记页面为 **ReCapture** 返工时，会把这三个标记重置为 FALSE，这是唯一文档化跨写入 |
| `group_id`、`qc_status` PASS/REWORK/PENDING | QC / Export | QC verdict statement；`group_id` 在导出时生成（模块 2） |
| `client_qc_status`、`client_rework` | 未来 client-rework 阶段 | 当前模块不写（Export 只为 CSV 的 `Rework` 列读取 `client_rework`） |
| `is_tif_converted`、`is_exported`、`exported_time` | Export | Export statement（模块 2） |
| `is_ingested`、`ingested_time` | Upload | Upload statement（模块 3） |

每次重新处理时，图片处理阶段会把 `qc_status` 重置为 `PENDING`，因此重处理后的 Folder 会重新进入 QC。**返工模型很简单：reject = 重新拍摄。** QC 在应用内修复所有可修复问题（裁剪、纠偏、旋转、亮度、元数据、拆分、删除、替换）并通过 Folder；这些内联修复不写 `rework_logs`。唯一 reject 原因是某页面必须实体重拍：QC 写一条 `rework_logs` OPEN 记录 + 设置 `qc_status='REWORK'` + 重置三个处理标记 -> 采集工位上 box 显示 REWORK（本地推导）并只暴露需要重拍的页面 -> 操作员用相同 `image_name` 原地重拍 -> 重新传输 -> LWIP 重新处理 -> 标记 TRUE + `qc_status='PENDING'` -> LWCAM 关闭 `rework_logs` 行 -> Folder 回到 QC 队列。见 `MODULE_1` 第 6 节。

## 5. 同步模型（LWCAM 如何与云端通信）

LWCAM 从不同步直接写云端业务表。它使用 **持久 outbox**：

1. 每次采集/传输/处理写入会落到本地 SQLite，并在 **同一事务** 中插入 `sync_outbox` 行，因此崩溃不会导致两者不一致。
2. `SyncService`（30 秒定时器）通过 `PgSyncSink` 消费 outbox。
3. outbox payload 携带 **自然键**，绝不携带云端 BIGINT id。sink 按批解析 id：project 用 **`project_key`**，user 用 `user_id`，device 用 `device_id`，box 用 `(project, box_name)`，folder 用 `(box, folder_seq)`，image 用 `(folder, image_name)`。
4. `kSyncEntityOrder` 固定消费顺序，确保父记录先于子记录存在（project -> box -> folder -> image -> folder-processing）。

同一次 tick 还会从 PG 拉取最新 users/projects/app_settings 快照（这些表以 PG 为事实来源），并覆盖本地只读快照 `lwcam_users.json`。LWCAM 对这些表的云端写入只有三个白名单调用：修改自己的密码、登录时间戳、project-has-data。用户/项目/设置的其他所有写入都由 LWCam Admin 拥有。

图片处理阶段是向流水线添加阶段的工作示例：它新增了一个 outbox 实体（`capture_folder_processing`）、一个 PG 语句（`folderProcessingUpdateSql`）和一个 sink `case`。照这个形状复制。

### 离线行为

系统设计支持 **长期离线站点**。同步关闭或 PG 不可达时，应用完全基于本地 SQLite 和本地用户快照运行；outbox 行会累积，并在连接恢复后消费。强制改密会在本地排队并立即应用到快照。设备-项目门禁在 PG 不可达时静默放行。

## 6. 每工位配置（`lwcam_node_config.json`）

每台 PC 一个 JSON 文件，位置为 `%USERPROFILE%\LWCAM_DBs\lwcam_node_config.json`。它只由 LWCam Admin 的 Station Setup 写入，由 LWCAM 在启动和登录时读取。文件包含 PG 连接、采集 outbox 同步开关、消费间隔、用户快照路径、图片目标路径，以及各阶段开关（`processingEnabled` + LWIP input/output/workers、`qcEnabled`、`uploadEnabled`）。这是单机配置，不同步。`NodeConfig`（Dart model）是手工重复的共享文件之一，两份都要保持字节兼容。

## 7. 工位本地存储

全部位于 `%USERPROFILE%\LWCAM_DBs\`：

- `lwcam_node_config.json` - 上述每工位配置。
- `lwcam_users.json` - 只读 users/projects/settings 快照（从 PG 拉取，或由 Admin 为全新离线 PC 初始化）。
- `lwcam_pending_password_changes.json` - 离线密码变更队列。
- `lwcam_stats_<deviceId>.db` - 每设备 SQLite DB（见 LWCAM 文档）。
- `lwip/` - 处理启用时 LWIP 生成的配置与运行时文件（state.json、logs）。

## 8. 给新团队的身份与安全说明

- **凭据**：PG 连接（host/user/password）存在每台工位的 `lwcam_node_config.json` 中，由 Admin 的 Station Setup 写入。它不在 repo 中，本交接包不包含配置、数据库或凭据。你需要准备新的 PG 并运行 Station Setup。
- **密码** 使用 bcrypt（`password_hasher.dart`）。套件中没有任何地方能查看密码；管理员只能重置为共享默认密码。
- **SuperAdmin** 只存在于 LWCam Admin（`super_admin.dart`），包含出厂 bcrypt hash，并可在 `app_settings` 中使用 PG override。
- 该套件按设计只支持 Windows（PowerShell 调用、`adb.exe`、打包的 `scrcpy`/LWIP、`sqflite_common_ffi`、`USERPROFILE`）。

## 9. 构建与运行（两个应用）

```bash
flutter pub get
flutter run -d windows            # debug
flutter build windows --release   # release
flutter analyze
flutter test
```

要求：Flutter SDK（Dart `^3.8.1`）、Windows 工具链（Visual Studio C++ desktop workload）。LWCAM 还需要可访问的 `adb.exe`；Box Mode 的实时镜像和图片处理还需要将打包的 `scrcpy` 与 `LWIP` 文件夹放在构建 exe 旁边（Inno Setup 脚本 `LWCAM/windows/runner/resources/LWCAM.iss` 列出需要打包的内容）。LWIP 以源码交付；需要运行它的离线 setup，为目标路径重建 venv（venv 硬编码绝对路径，移动后不可用）。
