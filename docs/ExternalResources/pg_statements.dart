// ignore_for_file: avoid_print

/// SQL statement builders for the cloud schema in
/// `LWCam Workflow & SQL update/LWCam_database_20260720.sql`. Pure Dart — no
/// postgres import — so every statement's SQL and parameters are unit-testable
/// without a connection (the CI has no live PG). `PgSyncSink` executes these.
///
/// Identity model: the cloud uses BIGINT identity PKs; LWCAM rows are created
/// offline and never know them. Every writer here therefore takes the parent
/// ids as ALREADY-RESOLVED integers (the sink resolves them per batch via the
/// resolve* SELECTs below, keyed by the natural keys carried in outbox
/// payloads) and every upsert conflicts on the entity's natural UNIQUE key:
/// users(user_id), projects(project_id), devices(device_id),
/// capture_boxes(project_id, box_name), capture_folders(box_id, folder_seq),
/// capture_images(folder_id, image_name).
///
/// Timestamps travel as the app's local ISO-8601 strings and are cast with
/// CAST(@x AS timestamptz) — interpreted in the server's time zone, same
/// caveat as the retired sink.
library;

import 'dart:convert';

import '../models/app_user.dart';
import '../models/metadata_template.dart';
import '../models/project.dart';

class PgStatement {
  final String sql;
  final Map<String, Object?> parameters;
  const PgStatement(this.sql, this.parameters);
}

/// ISO-8601 string of [value] if it parses as a date/time, else null — a
/// keyed free-text date must never poison a batch with an uncastable value.
/// Archive metadata dates are often just a year ("1914") or year-month
/// ("1914-06"); those coerce to Jan 1 / the 1st rather than being lost.
String? tsOrNull(Object? value) {
  final s = value?.toString().trim() ?? '';
  if (s.isEmpty) return null;
  final direct = DateTime.tryParse(s);
  if (direct != null) return direct.toIso8601String();
  final yearOnly = RegExp(r'^(\d{4})(?:-(\d{1,2}))?$').firstMatch(s);
  if (yearOnly != null) {
    final year = int.parse(yearOnly.group(1)!);
    final month = int.tryParse(yearOnly.group(2) ?? '') ?? 1;
    if (month >= 1 && month <= 12) {
      return DateTime(year, month).toIso8601String();
    }
  }
  return null;
}

// ── FK resolution (sink caches results per drained batch) ──────────────────

PgStatement resolveUserSql(String username) => PgStatement(
      'SELECT id FROM users WHERE user_id = @user_id',
      {'user_id': username},
    );

/// Resolves via `project_key` — the stable client identity — never
/// `project_id`, which is a human-editable label LWCam Admin can rename
/// freely without minting a duplicate cloud row.
PgStatement resolveProjectByKeySql(String projectKey) => PgStatement(
      'SELECT id FROM projects WHERE project_key = @project_key',
      {'project_key': projectKey},
    );

PgStatement resolveDeviceSql(String deviceId) => PgStatement(
      'SELECT id FROM devices WHERE device_id = @device_id',
      {'device_id': deviceId},
    );

/// Self-heal: a capture device that recorded boxes before its first gated
/// login has no devices row yet — create one bound to the payload project's
/// location code. No-op when the row exists.
PgStatement insertDeviceIfMissingSql({
  required String deviceId,
  required int pgProjectId,
}) =>
    PgStatement(
      'INSERT INTO devices (device_id, country_location_code) '
      'SELECT @device_id, p.country_location_code FROM projects p '
      'WHERE p.id = @project_id '
      'ON CONFLICT (device_id) DO NOTHING',
      {'device_id': deviceId, 'project_id': pgProjectId},
    );

PgStatement resolveBoxSql({required int pgProjectId, required String boxName}) =>
    PgStatement(
      'SELECT box_id FROM capture_boxes '
      'WHERE project_id = @project_id AND box_name = @box_name',
      {'project_id': pgProjectId, 'box_name': boxName},
    );

PgStatement resolveFolderSql({required int pgBoxId, required int folderSeq}) =>
    PgStatement(
      'SELECT id FROM capture_folders '
      'WHERE box_id = @box_id AND folder_seq = @folder_seq',
      {'box_id': pgBoxId, 'folder_seq': folderSeq},
    );

// ── capture_boxes ───────────────────────────────────────────────────────────

/// Pre-step for a renamed box: the cloud row is keyed by (project_id,
/// box_name), so move the existing row to the new name before the upsert —
/// otherwise the upsert would mint a duplicate. Idempotent: matches nothing
/// once the rename has been applied (or when the new name already exists).
PgStatement boxRenameFixupSql({
  required int pgProjectId,
  required String renamedFrom,
  required String newName,
}) =>
    PgStatement(
      'UPDATE capture_boxes SET box_name = @new_name '
      'WHERE project_id = @project_id AND box_name = @renamed_from '
      'AND NOT EXISTS (SELECT 1 FROM capture_boxes '
      '  WHERE project_id = @project_id AND box_name = @new_name)',
      {
        'project_id': pgProjectId,
        'renamed_from': renamedFrom,
        'new_name': newName,
      },
    );

/// [payload] is the local capture_boxes row snapshot; ids are resolved.
/// updated_at is left to the PG trigger on UPDATE (and its DEFAULT on
/// INSERT); local-only columns never appear here.
PgStatement boxUpsertSql(
  Map<String, dynamic> payload, {
  required int pgUserId,
  required int pgDeviceId,
  required int pgProjectId,
}) =>
    PgStatement(
      'INSERT INTO capture_boxes (box_name, device_id, status, user_id, '
      'project_id, created_at, transfer_start_at, transfer_end_at, '
      'transferred_to) '
      'VALUES (@box_name, @device_id, @status, @user_id, @project_id, '
      'COALESCE(CAST(@created_at AS timestamptz), clock_timestamp()), '
      'CAST(@transfer_start_at AS timestamptz), '
      'CAST(@transfer_end_at AS timestamptz), @transferred_to) '
      'ON CONFLICT (project_id, box_name) DO UPDATE SET '
      'device_id = EXCLUDED.device_id, status = EXCLUDED.status, '
      'user_id = EXCLUDED.user_id, '
      'transfer_start_at = EXCLUDED.transfer_start_at, '
      'transfer_end_at = EXCLUDED.transfer_end_at, '
      'transferred_to = EXCLUDED.transferred_to, '
      'is_deleted = FALSE, deleted_at = NULL '
      'RETURNING box_id',
      {
        'box_name': payload['box_name'],
        'device_id': pgDeviceId,
        'status': payload['status'] ?? 'OPEN',
        'user_id': pgUserId,
        'project_id': pgProjectId,
        'created_at': tsOrNull(payload['created_at']),
        'transfer_start_at': tsOrNull(payload['transfer_start_at']),
        'transfer_end_at': tsOrNull(payload['transfer_end_at']),
        'transferred_to': payload['transferred_to'],
      },
    );

// ── capture_folders ─────────────────────────────────────────────────────────

/// Writes the LWCAM-owned columns ONLY — never group_id (QC mints it) or any
/// QC/pipeline column (client_qc_status, is_deskewed, folder_path, …): those
/// belong to downstream stages and PG fills their defaults on INSERT.
/// folder_name is NOT NULL in the cloud but locally null until transfer prep
/// — COALESCE to ''. A locally reused folder_seq revives a soft-deleted
/// cloud row (is_deleted=FALSE in DO UPDATE).
PgStatement folderUpsertSql(
  Map<String, dynamic> payload, {
  required int pgBoxId,
  required int pgDeviceId,
}) {
  const metaCols = [
    'cover_tag', 'image_tags', 'title', 'volume', 'archival_ref_no',
    'record_type', 'place', 'language', 'record_custodian',
    'capture_operator_id', 'capture_operator_name', 'digitizing_entity', //
  ];
  final assignments = [
    'folder_name = EXCLUDED.folder_name',
    'device_id = EXCLUDED.device_id',
    for (final c in metaCols) '$c = EXCLUDED.$c',
    'start_date = EXCLUDED.start_date',
    'end_date = EXCLUDED.end_date',
    'source_created_at = EXCLUDED.source_created_at',
    'source_updated_at = EXCLUDED.source_updated_at',
    'is_deleted = FALSE',
    'deleted_at = NULL',
  ].join(', ');
  return PgStatement(
    'INSERT INTO capture_folders (folder_name, box_id, device_id, folder_seq, '
    '${metaCols.join(', ')}, start_date, end_date, '
    'source_created_at, source_updated_at) '
    "VALUES (COALESCE(@folder_name, ''), @box_id, @device_id, @folder_seq, "
    '${metaCols.map((c) => '@$c').join(', ')}, '
    'CAST(@start_date AS timestamptz), CAST(@end_date AS timestamptz), '
    'CAST(@source_created_at AS timestamptz), '
    'CAST(@source_updated_at AS timestamptz)) '
    'ON CONFLICT (box_id, folder_seq) DO UPDATE SET $assignments '
    'RETURNING id',
    {
      'folder_name': payload['folder_name'],
      'box_id': pgBoxId,
      'device_id': pgDeviceId,
      'folder_seq': payload['folder_seq'],
      for (final c in metaCols) c: payload[c],
      'start_date': tsOrNull(payload['start_date']),
      'end_date': tsOrNull(payload['end_date']),
      'source_created_at': tsOrNull(payload['source_created_at']),
      'source_updated_at': tsOrNull(payload['source_updated_at']),
    },
  );
}

PgStatement folderSoftDeleteSql({required int pgBoxId, required int folderSeq}) =>
    PgStatement(
      'UPDATE capture_folders SET is_deleted = TRUE, deleted_at = now() '
      'WHERE box_id = @box_id AND folder_seq = @folder_seq',
      {'box_id': pgBoxId, 'folder_seq': folderSeq},
    );

/// The image-processing phase's per-folder result — the ONLY statement that
/// writes any pipeline column on capture_folders. Sets the three completion
/// flags + the processed/thumbnail paths, and UNCONDITIONALLY resets
/// qc_status to 'PENDING' (a reprocessed folder re-enters QC even over an
/// earlier PASS/REWORK — decision 6). Deliberately never touches the
/// QC-owned columns group_id/client_qc_status/client_rework; updated_at is
/// handled by the capture_folders PG trigger. [pgFolderId] is resolved by
/// the sink from the payload's natural keys.
PgStatement folderProcessingUpdateSql(
  Map<String, dynamic> payload, {
  required int pgFolderId,
}) =>
    PgStatement(
      'UPDATE capture_folders SET '
      'is_deskewed = TRUE, is_cropped = TRUE, '
      'is_created_thumbnail = @is_created_thumbnail, '
      'folder_path = @folder_path, thumbnail_path = @thumbnail_path, '
      "qc_status = 'PENDING' "
      'WHERE id = @folder_id',
      {
        'is_created_thumbnail': payload['is_created_thumbnail'] == true,
        'folder_path': payload['folder_path'],
        'thumbnail_path': payload['thumbnail_path'],
        'folder_id': pgFolderId,
      },
    );

// ── capture_images ──────────────────────────────────────────────────────────

PgStatement imageUpsertSql(
  Map<String, dynamic> payload, {
  required int pgDeviceId,
  required int pgFolderId,
}) =>
    PgStatement(
      'INSERT INTO capture_images (image_name, device_id, folder_id, '
      'file_format, image_created_at) '
      'VALUES (@image_name, @device_id, @folder_id, @file_format, '
      'COALESCE(CAST(@image_created_at AS timestamptz), clock_timestamp())) '
      'ON CONFLICT (folder_id, image_name) DO UPDATE SET '
      'file_format = EXCLUDED.file_format, image_updated_at = now()',
      {
        'image_name': payload['image_name'],
        'device_id': pgDeviceId,
        'folder_id': pgFolderId,
        'file_format': payload['file_format'] ?? 'jpg',
        'image_created_at': tsOrNull(payload['image_created_at']),
      },
    );

/// Hard DELETE — capture_images has no soft-delete columns in the cloud.
PgStatement imageDeleteSql({required int pgFolderId, required String imageName}) =>
    PgStatement(
      'DELETE FROM capture_images '
      'WHERE folder_id = @folder_id AND image_name = @image_name',
      {'folder_id': pgFolderId, 'image_name': imageName},
    );

// ── Pull: rebuild the local snapshot from PG ────────────────────────────────
//
// PostgreSQL is the source of truth for users/projects/app_settings; LWCam
// Admin owns every write to them (see its admin_pg_statements.dart). LWCAM
// only pulls — these 4 SELECTs run once at the START of every sync tick,
// their rows rebuild a fresh [UsersStore], and the result overwrites the
// local snapshot wholesale (see PgSyncSink.pullStore / UsersStoreService).

PgStatement selectUsersSql() => const PgStatement(
      'SELECT u.user_id, u.password, u.active, u.must_change_password, '
      'u.roles, u.device_id, u.created_at, u.last_login_at, '
      'c.user_id AS created_by '
      'FROM users u LEFT JOIN users c ON c.id = u.created_by '
      'WHERE u.is_deleted = FALSE',
      {},
    );

PgStatement selectProjectsSql() => const PgStatement(
      'SELECT project_key, project_id, project_name, country_location_code, '
      "start_date, has_data, template::text, created_at "
      'FROM projects WHERE is_deleted = FALSE',
      {},
    );

PgStatement selectUserProjectsSql() => const PgStatement(
      'SELECT u.user_id, p.project_key, r.role_name FROM user_projects up '
      'JOIN users u ON u.id = up.user_id '
      'JOIN projects p ON p.id = up.project_id '
      'JOIN roles r ON r.id = up.role_id '
      'WHERE u.is_deleted = FALSE AND p.is_deleted = FALSE',
      {},
    );

PgStatement selectAppSettingsSql() =>
    const PgStatement('SELECT key, value FROM app_settings', {});

/// Rebuilds a [UsersStore] from the 4 pull SELECTs' decoded rows (each a
/// `Map<String, Object?>` — e.g. via the postgres package's
/// `Result.toColumnMap()`). Pure and unit-testable without a connection.
/// `updatedAt` is stamped as the pull time (there is no meaningful "last PG
/// write" timestamp to carry, and this is exactly what the login page shows
/// as "last synced").
UsersStore buildUsersStoreFromPgRows({
  required List<Map<String, Object?>> users,
  required List<Map<String, Object?>> projects,
  required List<Map<String, Object?>> userProjects,
  required List<Map<String, Object?>> appSettings,
  required DateTime now,
}) {
  // Roles are the account's GLOBAL roles, from users.roles (comma-joined) —
  // NOT derived from user_projects, which only records per-project grants
  // and would silently drop an admin's role the moment they hold zero
  // project assignments. user_projects supplies projectKeys only.
  final projectKeysByUser = <String, Set<String>>{};
  for (final row in userProjects) {
    final username = row['user_id']?.toString() ?? '';
    final projectKey = row['project_key']?.toString() ?? '';
    if (username.isEmpty || projectKey.isEmpty) continue;
    (projectKeysByUser[username] ??= {}).add(projectKey);
  }

  final appUsers = [
    for (final row in users)
      AppUser(
        username: row['user_id']?.toString() ?? '',
        passwordHash: row['password']?.toString() ?? '',
        roles: _rolesFromColumn(row['roles']),
        deviceId: _nullIfEmpty(row['device_id']?.toString()),
        active: row['active'] as bool? ?? true,
        mustChangePassword: row['must_change_password'] as bool? ?? false,
        createdAt: _asDateTime(row['created_at']),
        createdBy: row['created_by']?.toString(),
        lastLoginAt: _asDateTime(row['last_login_at']),
        projectKeys: projectKeysByUser[row['user_id']?.toString()] ?? const {},
      ),
  ];

  final projectModels = [
    for (final row in projects)
      Project(
        key: row['project_key']?.toString() ?? '',
        projectId: row['project_id']?.toString() ?? '',
        name: row['project_name']?.toString() ?? '',
        countryLocationCode: row['country_location_code']?.toString(),
        startDate: _asDateTime(row['start_date']) ?? DateTime.fromMillisecondsSinceEpoch(0),
        hasData: row['has_data'] as bool? ?? false,
        createdAt: _asDateTime(row['created_at']),
        template: _templateFromColumn(row['template']),
      ),
  ];

  final settingsByKey = {
    for (final row in appSettings) row['key']?.toString() ?? '': row['value']?.toString(),
  };
  final settings = SharedAppSettings(
    metadataKeyingEnabled: settingsByKey['metadata_keying_enabled'] == 'true',
    defaultTempPasswordHash: settingsByKey['default_temp_password_hash'],
    superAdminPasswordHash: settingsByKey['superadmin_password_hash'],
    shutterKeybind: kShutterKeybinds.contains(settingsByKey['shutter_keybind'])
        ? settingsByKey['shutter_keybind']!
        : 'Space',
    shutterMethod: kShutterMethods.contains(settingsByKey['shutter_method'])
        ? settingsByKey['shutter_method']!
        : 'tap',
    shutterTapXPercent: double.tryParse(settingsByKey['shutter_tap_x_percent'] ?? '') ?? 50,
    shutterTapYPercent: double.tryParse(settingsByKey['shutter_tap_y_percent'] ?? '') ?? 90,
  );

  return UsersStore(
    updatedAt: now,
    updatedBy: 'pg-pull',
    settings: settings,
    users: appUsers,
    projects: projectModels,
  );
}

/// `users.roles` is a comma-joined string ('admin', 'capture', or
/// 'admin,capture'); an empty/unknown segment is dropped, not fatal.
Set<UserRole> _rolesFromColumn(Object? value) {
  final s = value?.toString() ?? '';
  if (s.trim().isEmpty) return const {};
  return s.split(',').map(UserRole.fromJson).whereType<UserRole>().toSet();
}

String? _nullIfEmpty(String? s) => (s == null || s.isEmpty) ? null : s;

DateTime? _asDateTime(Object? value) {
  if (value is DateTime) return value;
  return DateTime.tryParse(value?.toString() ?? '');
}

/// `projects.template` (jsonb) may arrive as an already-decoded [Map] or as
/// its raw JSON [String], depending on the driver path — handle both.
MetadataTemplate? _templateFromColumn(Object? value) {
  if (value == null) return null;
  if (value is Map) return MetadataTemplate.fromJson(value.cast<String, Object?>());
  final s = value.toString().trim();
  if (s.isEmpty) return null;
  try {
    final decoded = jsonDecode(s);
    return decoded is Map ? MetadataTemplate.fromJson(decoded.cast<String, Object?>()) : null;
  } catch (_) {
    return null;
  }
}

// ── LWCAM's PG write whitelist ──────────────────────────────────────────────
//
// PostgreSQL is the source of truth for users/projects; LWCAM only PULLS
// them (see the pull pipeline). These three writes are the sole exceptions
// — capture-side events that must land in PG directly, never routed through
// the NAS/local-JSON write path LWCam Admin owns.

/// A forced first-login/reset password change. Only `password` +
/// `must_change_password` — never touches `roles`/`device_id`/anything else
/// LWCam Admin owns, so this can never race a snapshot push destructively.
PgStatement updateOwnPasswordSql({required String username, required String bcryptHash}) =>
    PgStatement(
      'UPDATE users SET password = @password, must_change_password = FALSE '
      'WHERE user_id = @user_id',
      {'user_id': username, 'password': bcryptHash},
    );

/// Best-effort last-login stamp — never blocks login on failure.
PgStatement recordLoginSql(String username) => PgStatement(
      'UPDATE users SET last_login_at = now() WHERE user_id = @user_id',
      {'user_id': username},
    );

/// Best-effort advisory stamp: a box was created under this project. Never
/// clears the flag — `has_data` only ever goes false→true here.
PgStatement markProjectHasDataSql(String projectKey) => PgStatement(
      'UPDATE projects SET has_data = TRUE '
      'WHERE project_key = @project_key AND has_data = FALSE',
      {'project_key': projectKey},
    );

// ── Box-name uniqueness pull ────────────────────────────────────────────────

PgStatement fetchBoxNamesSql(String projectKey) => PgStatement(
      'SELECT b.box_name FROM capture_boxes b '
      'JOIN projects p ON p.id = b.project_id '
      'WHERE p.project_key = @project_key AND b.is_deleted = FALSE',
      {'project_key': projectKey},
    );
