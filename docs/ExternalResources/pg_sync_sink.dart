// ignore_for_file: avoid_print

import 'package:postgres/postgres.dart';

import '../models/app_user.dart';
import 'pg_client.dart';
import 'pg_statements.dart' as st;
import 'sync_models.dart';
import 'sync_sink.dart';

/// PostgreSQL sink targeting the cloud schema in
/// `LWCam Workflow & SQL update/LWCam_database_20260720.sql`. One instance is
/// held for the lifetime of `SyncService`; every method reconnects lazily if
/// the held connection has dropped.
///
/// The cloud uses BIGINT identity PKs; outbox payloads carry natural keys
/// (see upload_stats_db.dart's SYNC section) and [apply] resolves them to
/// real ids per batch, parents first: project → device (self-healed
/// insert-if-missing) → box (with the rename fixup) → folder → image.
class PgSyncSink implements SyncSink {
  final String host;
  final int port;
  final String database;
  final String user;
  final String password;
  final bool useSsl;

  Connection? _conn;

  PgSyncSink({
    required this.host,
    required this.port,
    required this.database,
    required this.user,
    required this.password,
    required this.useSsl,
  });

  Future<Connection> _connect() async {
    final existing = _conn;
    if (existing != null && existing.isOpen) return existing;
    _conn = null;
    return _conn = await openPgConnection(
      host: host,
      port: port,
      database: database,
      user: user,
      password: password,
      useSsl: useSsl,
    );
  }

  /// Executes a [st.PgStatement], wrapping Dart string lists as text[] so
  /// `= ANY(@param)` works.
  Future<Result> _exec(Session session, st.PgStatement stmt) {
    final params = <String, Object?>{
      for (final e in stmt.parameters.entries)
        e.key: e.value is List<String>
            ? TypedValue(Type.textArray, e.value as List<String>)
            : e.value,
    };
    return session.execute(Sql.named(stmt.sql), parameters: params);
  }

  Future<int?> _selectId(Session session, st.PgStatement stmt) async {
    final result = await _exec(session, stmt);
    if (result.isEmpty) return null;
    return (result.first[0] as num?)?.toInt();
  }

  @override
  Future<void> probe() async {
    final conn = await _connect();
    try {
      await conn.execute('SELECT 1');
    } catch (e) {
      throw SyncConnectException(e.toString());
    }
  }

  // ── Outbox drain ──────────────────────────────────────────────────────────

  @override
  Future<void> apply(List<OutboxRecord> batch) async {
    if (batch.isEmpty) return;
    final conn = await _connect();

    await conn.runTx((session) async {
      // Per-batch id caches, keyed by natural key.
      final userIds = <String, int>{};
      final projectIds = <String, int>{};
      final deviceIds = <String, int>{};
      final boxIds = <String, int>{}; // '<pgProjectId>|<box_name lower>'
      final folderIds = <String, int>{}; // '<pgBoxId>|<folder_seq>'

      Future<int> projectId(Map<String, dynamic> payload) async {
        final key = (payload['project_key'] as String?)?.trim() ?? '';
        if (key.isEmpty) {
          throw StateError(
              'row has no project_key (legacy/code-less project) — cannot sync');
        }
        final cached = projectIds[key];
        if (cached != null) return cached;
        final id = await _selectId(session, st.resolveProjectByKeySql(key));
        if (id == null) {
          throw StateError('project "$key" not in PG yet (pull pending?)');
        }
        return projectIds[key] = id;
      }

      Future<int> userId(Map<String, dynamic> payload) async {
        final key = (payload['user_id'] as String?)?.trim() ?? '';
        if (key.isEmpty) throw StateError('box row has no user_id');
        final cached = userIds[key];
        if (cached != null) return cached;
        final id = await _selectId(session, st.resolveUserSql(key));
        if (id == null) {
          throw StateError('user "$key" not in PG yet (snapshot pending?)');
        }
        return userIds[key] = id;
      }

      Future<int> deviceId(Map<String, dynamic> payload, int pgProjectId) async {
        final key = (payload['device_id'] as String?)?.trim() ?? '';
        if (key.isEmpty) throw StateError('row has no device_id');
        final cached = deviceIds[key];
        if (cached != null) return cached;
        var id = await _selectId(session, st.resolveDeviceSql(key));
        if (id == null) {
          // Self-heal: boxes captured before the device's first gated login.
          await _exec(session,
              st.insertDeviceIfMissingSql(deviceId: key, pgProjectId: pgProjectId));
          id = await _selectId(session, st.resolveDeviceSql(key));
        }
        if (id == null) throw StateError('device "$key" could not be registered');
        return deviceIds[key] = id;
      }

      /// Resolves the parent box for folder/image rows: current name first,
      /// then renamed_from (covers a rename racing ahead of the box upsert).
      /// Returns null when neither exists (caller decides throw vs skip).
      Future<int?> boxIdOrNull(Map<String, dynamic> payload, int pgProjectId) async {
        for (final name in [
          payload['box_name'] as String?,
          payload['renamed_from'] as String?,
        ]) {
          if (name == null || name.trim().isEmpty) continue;
          final cacheKey = '$pgProjectId|${name.trim().toLowerCase()}';
          final cached = boxIds[cacheKey];
          if (cached != null) return cached;
          final id = await _selectId(
              session, st.resolveBoxSql(pgProjectId: pgProjectId, boxName: name));
          if (id != null) return boxIds[cacheKey] = id;
        }
        return null;
      }

      for (final record in batch) {
        final payload = record.payload;
        switch (record.entity) {
          case 'capture_boxes':
            if (record.op != 'upsert' || payload == null) break; // no delete path
            final pgProject = await projectId(payload);
            final renamedFrom = (payload['renamed_from'] as String?)?.trim();
            if (renamedFrom != null && renamedFrom.isNotEmpty) {
              await _exec(
                  session,
                  st.boxRenameFixupSql(
                    pgProjectId: pgProject,
                    renamedFrom: renamedFrom,
                    newName: (payload['box_name'] as String?) ?? '',
                  ));
              boxIds.remove('$pgProject|${renamedFrom.toLowerCase()}');
            }
            final result = await _exec(
                session,
                st.boxUpsertSql(
                  payload,
                  pgUserId: await userId(payload),
                  pgDeviceId: await deviceId(payload, pgProject),
                  pgProjectId: pgProject,
                ));
            final name = (payload['box_name'] as String?)?.trim().toLowerCase();
            if (result.isNotEmpty && name != null) {
              boxIds['$pgProject|$name'] = (result.first[0] as num).toInt();
            }
            break;

          case 'capture_folders':
            if (payload == null) break;
            final pgProject = await projectId(payload);
            final pgBox = await boxIdOrNull(payload, pgProject);
            if (record.op == 'delete') {
              // Parent never reached PG ⇒ nothing to soft-delete.
              if (pgBox == null) break;
              await _exec(
                  session,
                  st.folderSoftDeleteSql(
                      pgBoxId: pgBox,
                      folderSeq: (payload['folder_seq'] as num).toInt()));
              break;
            }
            if (pgBox == null) {
              throw StateError(
                  'box "${payload['box_name']}" not in PG yet for folder upsert');
            }
            final result = await _exec(
                session,
                st.folderUpsertSql(
                  payload,
                  pgBoxId: pgBox,
                  pgDeviceId: await deviceId(payload, pgProject),
                ));
            if (result.isNotEmpty) {
              folderIds['$pgBox|${payload['folder_seq']}'] =
                  (result.first[0] as num).toInt();
            }
            break;

          case 'capture_images':
            if (payload == null) break;
            final pgProject = await projectId(payload);
            final pgBox = await boxIdOrNull(payload, pgProject);
            final seq = (payload['folder_seq'] as num?)?.toInt();
            int? pgFolder;
            if (pgBox != null && seq != null) {
              pgFolder = folderIds['$pgBox|$seq'] ??
                  await _selectId(
                      session, st.resolveFolderSql(pgBoxId: pgBox, folderSeq: seq));
              if (pgFolder != null) folderIds['$pgBox|$seq'] = pgFolder;
            }
            if (record.op == 'delete') {
              if (pgFolder == null) break; // parent never synced — no row
              await _exec(
                  session,
                  st.imageDeleteSql(
                      pgFolderId: pgFolder,
                      imageName: (payload['image_name'] as String?) ?? ''));
              break;
            }
            if (pgFolder == null) {
              throw StateError(
                  'folder seq $seq of box "${payload['box_name']}" not in PG yet '
                  'for image upsert');
            }
            await _exec(
                session,
                st.imageUpsertSql(
                  payload,
                  pgDeviceId: await deviceId(payload, pgProject),
                  pgFolderId: pgFolder,
                ));
            break;

          case 'capture_folder_processing':
            if (payload == null) break;
            final pgProject = await projectId(payload);
            final pgBox = await boxIdOrNull(payload, pgProject);
            final seq = (payload['folder_seq'] as num?)?.toInt();
            int? pgFolder;
            if (pgBox != null && seq != null) {
              pgFolder = folderIds['$pgBox|$seq'] ??
                  await _selectId(
                      session, st.resolveFolderSql(pgBoxId: pgBox, folderSeq: seq));
              if (pgFolder != null) folderIds['$pgBox|$seq'] = pgFolder;
            }
            if (pgFolder == null) {
              // Same-PC: the folder upsert is earlier in this ordered batch,
              // so this rarely fires. Split-PC: the capture station's folder
              // may not have synced yet — retry on the normal backoff. After
              // ~20 attempts (hours) give up and ack, so one decommissioned
              // capture PC can't wedge a processing station's reports forever.
              if (record.attempts < 20) {
                throw StateError(
                    'folder seq $seq of box "${payload['box_name']}" not in PG '
                    'yet for processing update (attempt ${record.attempts})');
              }
              print('⚠️ Dropping processing update after ${record.attempts} '
                  'attempts — folder never appeared in PG: '
                  'project_key=${payload['project_key']} '
                  'box="${payload['box_name']}" folder_seq=$seq');
              break;
            }
            await _exec(
                session, st.folderProcessingUpdateSql(payload, pgFolderId: pgFolder));
            break;

          default:
            // Unknown entity — defensively skip (acked, never retried).
            break;
        }
      }
    });
  }

  // ── Users-store pull ───────────────────────────────────────────────────────

  @override
  Future<UsersStore> pullStore() async {
    final conn = await _connect();
    final users = await _exec(conn, st.selectUsersSql());
    final projects = await _exec(conn, st.selectProjectsSql());
    final userProjects = await _exec(conn, st.selectUserProjectsSql());
    final appSettings = await _exec(conn, st.selectAppSettingsSql());
    return st.buildUsersStoreFromPgRows(
      users: [for (final r in users) r.toColumnMap()],
      projects: [for (final r in projects) r.toColumnMap()],
      userProjects: [for (final r in userProjects) r.toColumnMap()],
      appSettings: [for (final r in appSettings) r.toColumnMap()],
      now: DateTime.now(),
    );
  }

  // ── Box-name uniqueness pull ──────────────────────────────────────────────

  @override
  Future<Set<String>> fetchBoxNames(String projectKey) async {
    final conn = await _connect();
    final result = await _exec(conn, st.fetchBoxNamesSql(projectKey));
    return {for (final row in result) row[0] as String};
  }

  @override
  Future<void> close() async {
    final conn = _conn;
    _conn = null;
    if (conn != null) {
      try {
        await conn.close();
      } catch (_) {
        // Already gone — nothing to clean up.
      }
    }
  }
}
