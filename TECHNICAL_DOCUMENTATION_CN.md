# LWCAM - 技术文档

> 请先阅读 `../ARCHITECTURE.md`，了解整个套件的全局视角（流水线阶段、云端 schema、同步模型）。本文说明 LWCAM 内部实现。

LWCAM（package `lwcam`，窗口标题 *"LWCAM (Lifewood Capture)"*）是面向操作员的 Flutter Windows 桌面应用。它通过 ADB 从 Android 手机拉取扫描图片，将图片按 box/folder 和元数据组织起来，在强可靠性保护下传输到 NAS/本地目标位置，并可按工位配置监管 LWIP 图片处理后端并上报处理结果。

---

## 1. 运行形态

- **技术栈**：Flutter（仅 Windows target）、GetX 负责状态/DI/路由、SQLite 使用 `sqflite_common_ffi`、`window_manager`、`postgres`（纯 Dart 客户端）、`win32`/`ffi` 用于 scrcpy 镜像和 job object、`bcrypt` 用于认证、`hotkey_manager` 用于全局快门键。
- **驱动的外部进程**：`adb.exe`（设备 I/O）、打包的 `scrcpy`（Box Mode 实时手机镜像）、打包的 `LWIP` Python（图片处理）。
- **`adb.exe` 解析顺序**（`gallery_page.dart:_resolveAdbPath`）：exe 旁边 -> 项目根目录 -> `C:\Android\platform-tools\adb.exe` -> PATH。

### 启动（`lib/main.dart`）

`main()` 在 `runZonedGuarded` 内运行；任何未捕获错误都会把 crash log 写入用户 Downloads 文件夹，并显示 PowerShell MessageBox。顺序如下：

1. 初始化 SQLite FFI。
2. 注册 `AuditLogService`（在登录前注册，因此失败登录也会记录）。
3. 从 `%USERPROFILE%\LWCAM_DBs\lwcam_node_config.json` 加载 `NodeConfig`；设置 `UploadStatsDB().syncEnabled`。
4. 如果上次运行持久化了采集设备 id，`SyncBootstrap.apply` 会立即启动同步消费（早于任何登录）。
5. 如果该工位启用了 processing，`ProcessingBootstrap.apply` 启动 LWIP 监管和 report agent。它绝不阻塞启动。
6. 加载主题，初始化窗口（使用不透明背景避免冷启动空白窗口），显示窗口，并在首帧之后最大化。

通知初始化故意 **懒加载**（首次使用时初始化），不在启动时执行，因为 Windows notification 插件每次 `initialize()` 都会播放系统错误提示音。

### 关闭（`_AppWindowListener.onWindowClose`）

确认对话框（如果 box transfer 正在进行则警告） -> 立即隐藏窗口 -> kill scrcpy 和 LWIP 子进程 -> 有界清理临时文件 -> 停止 `SyncService` 和 `ProcessingReportService` -> 销毁窗口。

## 2. 路由与入口流程

路由（GetX）：`/` LoginPage -> `/home` HomePage（多角色/admin 选择器） -> `/select-project` -> `/gallery`（Normal Mode，keying 关闭）或 `/boxes`（Box Mode，keying 开启）。Controller 由需要它们的页面懒注册，因此 **实例化顺序很重要**：`UploadController` 要求 `SettingsController` 和 `AuthController` 先存在。

登录始终使用 **username + password**（`auth_controller.dart`）。它检查 `canNormalMode`/`isAdmin`，当账号启用了 metadata keying 时路由到 `/boxes`，否则到 `/gallery`，并对单角色账号自动路由。既没有角色也没有权限的账号会收到通用的“no access to LWCAM”拒绝。LWCAM 中 **没有 SuperAdmin**（它只存在于 LWCam Admin）。

## 3. 两种采集模式

两种模式最终都进入同一个传输引擎（`UploadController`）；差异只在传输前如何组织图片。

### Normal Mode - `lib/pages/gallery_page.dart`

这是应用的重心，也是 **最高风险文件**（约 2800 行）。它直接通过 `Process.run` 驱动 `adb.exe`：扫描 `/storage/emulated/0/DCIM/...`、拉取文件、检测设备型号、启动设备相机、从设备删除文件。维护两个临时目录（gallery cache 和 transfer staging），在 dispose/close 时清理。它还实现了 **替换图片工作流**：重拍坏图会以 Pro mode 启动设备相机（需要前台验证，因为 `am start` 会谎报成功），用新拍照片覆盖设备上原始文件名，并在 DB 中记录每次替换的完整历史（被替代行标记为 superseded，绝不删除）。live-sync timer 会轮询设备上的新照片。

> **把 `gallery_page.dart` 视为承重文件。** 它在 fork 过程中故意保持未动。不要为了无关功能重构它。

### Box Mode - Box/Folders 工作流

文件：`capture_box_list_page.dart`、`box_transfer_flow.dart`、`folder_metadata_form_page.dart`、`box_session_controller.dart`、`gallery_controller.dart`、`models/capture_box_models.dart`、`models/batch_metadata.dart`。

采集 *boxes* 包含已录入的 *folders*（cover tag、image tags、title、volume、dates、archival ref no、record type 等）。每个 Folder 都有自己的目标子目录。传输在后台按 box 队列执行（`transfer_queue_service.dart`）；每个 box tile 显示实时进度和 **持久化** 结果（`capture_boxes.last_transfer_state`/`last_transfer_error`，仅本地），重启后仍保留。中断/部分完成/失败的 box 会在 tile 上提供 **Retry**，重新运行 `runBoxTransferFlow`（已复制图片通过 DB 跳过；staging 会复用持久 `box_images` 存储，或从手机重新拉取）。

Box Mode 还通过 `scrcpy_service.dart` 显示 **实时手机镜像**（使用 “clip-host” 技术把 scrcpy 窗口嵌入为原生 Win32 子窗口），并通过 `shutter_hotkey_service.dart` 激活 **全局快门热键**，经由镜像点击手机快门。

## 4. 采集完整性（不要削弱）

每张图片的 `capture_images` 行是 box 成员关系的 **唯一** 记录，因此采集时写入丢失绝不能被忽略。相关文件：`orphan_image_store.dart`、`box_integrity.dart`。

- `assignNewImage` 会重试 DB 写入；如果硬失败（或没有活跃 Folder），会把拉取的字节保存到 **文件系统** ledger（`<AppSupport>/orphan_images/<deviceId>/` 加 `.intent.json` sidecar）。这里故意不用 DB 表，因为刚失败的正是 DB。
- `healOrphanImages` 会在 box-list 加载、box 打开、预传输时静默重新归档 intent 已知的 orphan。
- `verifyBoxComplete` 阻止每次 `markCaptureBoxTransferred`：每张已记录分配的图片必须已落地，且不能有指向该 box 的 orphan。任何不一致都会让 box 保持 `partial`，绝不标记 transferred。
- 无法修复的 orphan（folder intent 丢失）进入 admin-only 的 “Unresolved Images” 页面（`orphan_resolution_page.dart`），由管理员分配或丢弃。
- 当手机上不再有已分配文件时，`stageBoxFiles` 会回退到持久 `box_images` 副本。这是“手机是事实来源”的 **唯一** 例外（只要手机还有文件，手机仍然权威）。

## 5. 传输引擎 - `lib/controllers/upload_contoller.dart`

> 文件名拼写错误（`contoller`）是有意保留的，imports 依赖它。和已经不再承载页面的 `settings_page.dart` 命名约定相同。

约 1600 行，同时服务两种模式。`uploadAll()` 接收可选 `BoxTransferContext`；`if (box != null)` 分支是唯一行为差异（每 Folder 目标子目录 + CSV/DB 行上的 Folder 元数据）。其他逻辑与原 Normal Mode 引擎字节级一致。

- 使用最多 **12 个并发**任务，以 **4 MB chunk** 复制队列文件，并提供单文件进度。
- **可靠性层**：10 分钟 copy timeout（`_copyOperationTimeout`）、30 秒 stall detection（`_stallTimeout`，每 `_stallCheckIntervalMs` = 5 秒检查一次）、目标可用性轮询与重连对话框。常量位于文件顶部。
- **崩溃/重启恢复基于 DB**，不是 checkpoint：只有在验证复制完成后才写入文件的 `upload_records` 行；batch 启动时跳过已记录 basename；`generateUniqueTargetFile` 会覆盖磁盘上存在但 DB 未记录的目标文件（中断运行留下的 orphan），而不是追加后缀跳过。这里故意 **没有** resume-by-index checkpoint（已于 2026-07-20 移除，因为重启后名称会从磁盘状态重新分配，保存的 index 不再匹配）。
- 每个 batch 在目标位置写入 artifacts：upload records CSV，以及 `logs/` 下的 transfer/summary/error/interruption logs，全部以操作员 device id 为前缀。artifact 写入通过 `_runSerializedArtifactWrite` 串行化。
- 自定义异常 `TransferTimeoutException`、`TransferStallException`、`UploadInterruptionException`（文件顶部）驱动错误对话框和 interruption logs。

**目标目录布局**（`transfer_destination_service.dart`，唯一有单元测试的继承文件）：`<root>/<work-week folder e.g. "June 15-19">/<YYYYMMDD>/`。工作周为 Monday-Friday；周末日期归入前一个工作周。

**传输保护**（`upload_stats_db.dart` + `file_lock_service.dart`）：WAL checkpoint 加 OS 级文件锁（在 batch 期间持有 `lwcam_transfer_in_progress.lock` 的 `RandomAccessFile.lock`）；Excel/CSV/DB/JSON 来源使用 `.lock` sidecar，并在 `finally` 中释放。

## 6. 本地数据库 - `lib/db/upload_stats_db.dart`

基于 sqflite FFI 的单例，是 **唯一** 本地 DB。每设备文件 `lwcam_stats_<deviceId>.db` 位于 `%USERPROFILE%\LWCAM_DBs`；两个高容量本地表（`upload_records`/`daily_summary`）还会按每设备每月轮转文件。schema 是全新的单个 `onCreate`（version 1），**没有 migrations**；schema 变化就是直接编辑 `onCreate`，并清空 `%USERPROFILE%\LWCAM_DBs`。

| Table | Purpose |
|---|---|
| `upload_records` | 已传输文件的本地记录（跳过逻辑 + CSV）。纯本地；云端已由 `capture_images` 替代。 |
| `daily_summary` | 每操作员每日计数。 |
| `replacement_records` | Normal Mode 替换图片历史。 |
| `capture_boxes` / `capture_folders` / `capture_images` | 镜像云端采集 schema，列名相同，状态为全大写（`OPEN`/`TRANSFERRED`），并带有分组的 **本地专用** 列，这些列永不同步。 |
| `sync_outbox` | 持久 outbox（只在稳定 DB 中，不在月度文件中）。 |
| `processing_ledger` | 以 `(input_path, fingerprint)` 对图片处理报告去重。只在稳定 DB 中。 |

采集表镜像云端（`LWCam_database_20260720.sql`），因此行可以用自然键入队。本地专用列在 `onCreate` 中用 `-- local-only ->` 标注，例如 `capture_boxes.renamed_from`、`last_transfer_state`、`template_json`、`project_key`；`capture_folders.is_complete`；`capture_images.box_id`。`capture_folders` 还镜像六个图片处理字段（`is_deskewed`/`is_cropped`/`is_created_thumbnail`/`folder_path`/`thumbnail_path`/`qc_status`），只由 `recordFolderProcessing` 写入，绝不由 folder upsert 写入。QC 拥有的列（`group_id`/`client_qc_status`/`client_rework`）和 export/ingestion 列故意 **不在本地出现**，因为 LWCAM 不拥有它们。

## 7. 同步流水线

文件：`sync_service.dart`、`sync_bootstrap.dart`、`pg_sync_sink.dart`、`pg_statements.dart`、`pg_client.dart`、`sync_models.dart`、`cloud_box_names.dart`、`users_store_service.dart`、`user_directory_service.dart`、`device_registry.dart`。

模型见 `../ARCHITECTURE.md` 第 5 节。LWCAM 特有点：

- `SyncService` 每 30 秒（可配置）通过 `PgSyncSink` 消费 `sync_outbox`，并在每次 tick **开始** 时从 PG 拉取最新 users/projects/app_settings 快照，通过纯函数 `buildUsersStoreFromPgRows` 重建 `UsersStore`（roles 来自 `users.roles`），然后整体覆盖本地 `lwcam_users.json`。
- LWCAM 通过恰好 **3 个** PG-direct 调用写 users/projects 表（`updateOwnPasswordSql` / `recordLoginSql` / `markProjectHasDataSql`）；其他所有内容只读。
- `pg_statements.dart` 是纯 Dart（不连接数据库也可单元测试）。`folderProcessingUpdateSql` 是唯一流水线字段写入者。
- `pg_sync_sink.dart` 按批解析自然键（project 用 `project_key`），并通过本地专用 `renamed_from` 列进行 box rename 修正，以及 devices 行自愈。`capture_folder_processing` 分支如果缺少 parent，会在 20 次尝试内 back off（throw），之后 skip-ack（不能让一台已停机采集 PC 永久毒化处理工位）。
- 每个 tick 结束时，会把当前活跃项目的云端 box names 拉入 `cloud_box_names.dart`（跨 PC 唯一性检查通过 `boxNameExists`）。

**离线改密**：首次登录/重置后的强制改密会先通过 `UserDirectoryService` 尝试 PG，但绝不被离线阻塞。PG 不可达时，新 bcrypt hash 会排入 `lwcam_pending_password_changes.json`，立即应用到本地快照（当前会话可登录），并在每次 sync tick 和后续登录尝试时重试（`flushPendingPasswordChanges`）。所有 snapshot/pending 的读改写都由 mutex 串行化。

**设备门禁**（`device_registry.dart`）：`AuthController.enterCaptureWithProject` 注册/刷新云端 `devices` 行，并 **阻止** 设备进入未绑定项目。同步关闭、PG 不可达或无代码项目时，门禁静默放行。

## 8. 图片处理阶段（LWIP 监管）

按工位可选。文件：`processing_bootstrap.dart`、`lwip_service.dart`、`processing_marker_service.dart`、`processing_report_service.dart`、`win32_job.dart`。

流程：

1. 完全验证通过的 box transfer 后，`BoxSessionController.markTransferred` 调用 `writeBoxProcessingMarkers`，向每个目标 Folder 写入 `lwcam_capture_marker.json`（Folder 的自然键身份）。该 marker 同时是 LWIP 的就绪门禁和 DB 身份 payload；LWIP 在 marker 存在且输出 manifest 嵌入身份之前不会处理 Folder。
2. `LwipService` 解析打包的 `LWIP/`，生成 `deskew_crop_config.json`（绝对路径、`folder_depth: 2` 监听 `<dest>/YYYYMMDD/<folder>`、`completion_marker`、512px thumbnails），启动 `venv\Scripts\python.exe -m deskew_crop_tool`，并把它绑定到 **关闭即 kill 的 job object**（`win32_job.dart`，与 scrcpy 共享）。崩溃时使用 backoff 重启，并有 early-exit streak breaker（配置错误不能让 python 无限 crash-loop）。如果 output 位于 input 内部则拒绝启动。
3. `ProcessingReportService`（15 秒 tick）追踪 LWIP 的 `state.json`；对每个已完成 Folder（通过 `processing_ledger` 的 `(input_path, fingerprint)` 去重，重传会改变 fingerprint 并重新上报）调用 `UploadStatsDB.recordFolderProcessing`。该调用在此 PC 上存在对应行时更新本地 `capture_folders` 六个字段，并入队 `capture_folder_processing` outbox 行。

仅处理 PC（无采集登录）使用 `'PROCESSING'` 伪 device id；payload 的自然键才驱动全部 PG 解析，而不是该 id。云端上报需要开启 capture-data sync；长期离线站点仍会获得本地字段更新。

## 9. 认证与用户模型

- `auth/auth_controller.dart` - 仅 username+password；device id 成为所有 records/logs/DB rows 上的 operator id。强制改密（`AuthStatus.mustChangePassword`）按第 7 节处理。
- `models/app_user.dart` - `UserRole` 为 `{admin, capture}`（没有 `rework`，那是 LWRework 的角色）。磁盘上的未知 role string 会容错解析为空。没有 admin 可见的 password 字段。
- `services/users_store_service.dart` - 读取只读快照 `lwcam_users.json`（由 sync pull 整体写入，或由 Admin 为全新离线 PC 初始化）。PG 是事实来源；除 3 个白名单调用外，LWCAM 绝不直接修改 users/projects/settings。Admin-only JSON keys（`dirty`/`deletedUsernames` 等）通过 `adminExtras` 不透明往返；绝不覆盖 Admin 标记为 `dirty` 的文件。

## 10. Settings（没有 Settings 页面）

`settings_page.dart` 仅在名称上保留（imports 依赖它），只包含精简的 `SettingsController`：`destinationPath`（从 `NodeConfig.destinationPath` 读取，每次登录刷新；为空时拒绝上传）和 `includeUploaded`（仅会话内 gallery filter）。Settings **页面** 已于 2026-07-22 移除（Settings 归 Admin 管）。深/浅色切换是 Home app bar 上的图标（`theme/theme_controller.dart`）。LWCAM 从不写 `lwcam_node_config.json`，它由 Station Setup 拥有。

## 11. 目录图（`lib/`）

```text
main.dart                     bootstrap、窗口生命周期、全局错误处理
auth/auth_controller.dart     登录、强制改密、设备门禁入口
controllers/
  upload_contoller.dart       传输引擎（两种模式）
  box_session_controller.dart Box Mode session；写 processing markers
  gallery_controller.dart     Box Mode gallery 状态
  projects_controller.dart    项目选择
db/upload_stats_db.dart       唯一本地 DB（singleton，sqflite FFI）
models/                       app_user、project、capture_box_models、
                              batch_metadata、metadata_template、node_config
pages/                        login、home、project_select、gallery (Normal)、
                              capture_box_list + box_transfer_flow +
                              folder_metadata_form (Box)、orphan_resolution、
                              upload_status、transferred_box_view、dialogs
services/
  adb_device_service.dart     ADB helpers
  transfer_*                  目标目录布局、队列、alerts
  file_lock_service.dart      .lock sidecars
  orphan_image_store.dart     采集完整性文件系统 ledger
  box_integrity.dart          verifyBoxComplete gate
  scrcpy_service.dart         嵌入式手机镜像
  shutter_hotkey_service.dart 全局快门键
  win32_job.dart              kill-on-close job objects（scrcpy + LWIP）
  lwip_service.dart           LWIP supervisor
  processing_*                marker 写入、report agent、bootstrap
  sync_service.dart           30 秒消费 + 拉取
  pg_sync_sink.dart           outbox -> PG（自然键解析）
  pg_statements.dart          纯 Dart SQL（可单测）
  pg_client.dart              共享连接打开器
  sync_models.dart            kSyncEntityOrder、payload shapes
  cloud_box_names.dart        跨 PC box-name 唯一性缓存
  users_store_service.dart    只读 users 快照 + pending password queue
  user_directory_service.dart 3-call PG 写入白名单
  device_registry.dart        device -> project 绑定门禁
  audit_log_service.dart      只追加本地 audit trail
  path_utils.dart             Windows 路径清理 + FNV-1a box key
theme/                        Lifewood light/dark themes + controller
```

## 12. 给接手团队的注意事项

- lints `avoid_print`、`deprecated_member_use`、`no_leading_underscores_for_local_identifiers` 是故意忽略的；带 emoji 前缀的 `print` 日志是项目风格。
- `contoller` 拼写错误和遗留的 `settings_page.dart` 名称是承重依赖（imports）。不要“修正”它们。
- transfer timeout/stall/lock 行为在 `upload_contoller.dart` / `file_lock_service.dart` / `upload_stats_db.dart` 中有内联说明，改常量前先读这些文件。
- 只有 `windows/` platform 文件夹；没有 Android 构建工具。手机通过外部 `adb.exe` 驱动。
- 添加/移除带 Windows DLL 的插件，或修改打包的 `scrcpy`/`LWIP` 文件夹时，要同步更新 `LWCAM.iss`。
- `CHANGELOG.txt` 按日期记录每个行为变化。任何用户可见变更都要加条目。
