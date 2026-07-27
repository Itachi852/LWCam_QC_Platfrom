import 'dart:async';
import 'dart:convert';
import 'dart:math';

import 'package:get/get.dart';
import 'package:sqflite/sqflite.dart';

import '../db/upload_stats_db.dart';
import '../models/app_user.dart';
import 'cloud_box_names.dart';
import 'sync_models.dart';
import 'sync_sink.dart';

/// Drains `sync_outbox` on a periodic timer and pushes batches through a
/// [SyncSink]. Runs on the main isolate (see plan P1-3: sqflite's singleton
/// connection can't be shared across isolates, and outbox volume is small
/// enough that async socket I/O here never blocks capture/transfer, which
/// use their own db calls interleaved on the same event loop).
///
/// Since the monthly DB rotation, a device's outbox is actually spread
/// across several files: the stable DB (boxes/folders/replacements always
/// live there) plus one file per month that has ever written an
/// upload_record. [UploadStatsDB.getOutboxDatabases] enumerates all of them;
/// this service drains each in turn, stable first, so the
/// parents-before-children ordering `kSyncEntityOrder` encodes still holds
/// across the whole device, not just within one file.
///
/// Construct with `syncEnabled: false` (or simply never call [start]) to get
/// a fully inert instance — this is what every existing install gets until
/// an admin opts in from Settings.
class SyncService extends GetxController {
  final UploadStatsDB _db;
  final SyncSink _sink;
  final String deviceId;
  final int batchSize;
  final Duration tickInterval;

  /// Applies a freshly PULLED users/projects/app-settings store at the start
  /// of every tick (before the outbox drain, so its FK parents always exist
  /// by the time rows resolve against them) — wired by SyncBootstrap to
  /// [UsersStoreService.applySnapshot]. Null skips the pull entirely (tests
  /// that only exercise the outbox drain).
  final Future<void> Function(UsersStore store)? applyPulledStore;

  /// The active capture project's stable client key (`Project.key`), for the
  /// box-name uniqueness pull at the tail of each tick; null skips the pull.
  final String? Function()? activeProjectKey;

  final Rx<SyncState> state = SyncState.disabled.obs;
  final RxInt pendingCount = 0.obs;
  final Rx<String?> lastError = Rx<String?>(null);

  bool _draining = false;
  Timer? _timer;

  SyncService({
    required UploadStatsDB db,
    required SyncSink sink,
    required this.deviceId,
    this.batchSize = 200,
    this.tickInterval = const Duration(seconds: 30),
    this.applyPulledStore,
    this.activeProjectKey,
  })  : _db = db,
        _sink = sink;

  /// Starts the periodic drain timer. Idempotent — calling it again just
  /// resets the interval. Does nothing if [UploadStatsDB.syncEnabled] is
  /// false; callers only construct/start a SyncService at all when a
  /// NodeConfig has syncEnabled=true, but this guard keeps the class safe to
  /// call unconditionally too.
  void start() {
    _timer?.cancel();
    if (!_db.syncEnabled) {
      state.value = SyncState.disabled;
      return;
    }
    state.value = SyncState.idle;
    _timer = Timer.periodic(tickInterval, (_) => syncNow());
    // Kick off an immediate first drain rather than waiting a full interval.
    syncNow();
  }

  void stop() {
    _timer?.cancel();
    _timer = null;
    state.value = SyncState.disabled;
  }

  @override
  void onClose() {
    stop();
    _sink.close();
    super.onClose();
  }

  /// Drains up to [batchSize] eligible rows per SOURCE DB in one tick (the
  /// stable DB, then every monthly file that already exists — see
  /// [UploadStatsDB.getOutboxDatabases]). Reentrancy-guarded — a slow tick
  /// never overlaps the next timer fire.
  Future<void> syncNow() async {
    if (_draining) return;
    if (!_db.syncEnabled) {
      state.value = SyncState.disabled;
      return;
    }
    _draining = true;
    try {
      final sources = await _db.getOutboxDatabases(deviceId);
      await _updatePendingCount(sources);

      var hadOffline = false;
      var hadError = false;

      // Users/projects/settings pull FIRST, so the outbox drain's FK
      // parents (users, projects) always exist by the time rows resolve
      // against them.
      if (applyPulledStore != null) {
        try {
          state.value = SyncState.syncing;
          final store = await _sink.pullStore();
          await applyPulledStore!(store);
        } on SyncConnectException catch (e) {
          lastError.value = e.message;
          state.value = SyncState.offline;
          return; // destination unreachable — nothing else can land this tick
        } catch (e) {
          // Keep the existing local snapshot — a failed pull must never
          // erase a good one. Idempotent; just let the next tick retry.
          print('⚠️ Users/projects pull failed: $e');
          lastError.value = e.toString();
          hadError = true;
        }
      }

      for (final source in sources) {
        final rows = await _selectEligible(source);
        if (rows.isEmpty) continue;

        state.value = SyncState.syncing;
        final ordered = [...rows]
          ..sort((a, b) => compareEntityOrder(a.entity, b.entity));

        try {
          await _sink.apply(ordered);
          await _ack(source, ordered);
          // Don't clear an error surfaced earlier this tick (e.g. the
          // users/projects pull) just because this source's drain succeeded
          // — the tick as a whole still had a failure worth showing.
          if (!hadError) lastError.value = null;
        } on SyncConnectException catch (e) {
          // Transient and a property of the destination, not this source —
          // no point trying the remaining sources this tick.
          lastError.value = e.message;
          hadOffline = true;
          break;
        } catch (e) {
          // A per-source/per-batch failure — other sources may still
          // succeed this tick, so keep going.
          await _backoff(source, ordered, e.toString());
          lastError.value = e.toString();
          hadError = true;
        }
      }

      // Tail: refresh the cloud box-name cache for the active project (the
      // uniqueness pull). Best-effort — any failure just leaves the cache as
      // it was; the check silently degrades to local-only.
      if (!hadOffline) {
        final projectKey = activeProjectKey?.call()?.trim();
        if (projectKey != null && projectKey.isNotEmpty) {
          try {
            CloudBoxNames.instance
                .update(projectKey, await _sink.fetchBoxNames(projectKey));
          } catch (e) {
            print('⚠️ Cloud box-name pull skipped: $e');
          }
        }
      }

      await _updatePendingCount(sources);
      if (hadError) {
        state.value = SyncState.error;
      } else if (hadOffline) {
        state.value = SyncState.offline;
      } else {
        state.value = SyncState.idle;
      }
    } finally {
      _draining = false;
    }
  }

  Future<List<OutboxRecord>> _selectEligible(Database source) async {
    final nowIso = DateTime.now().toIso8601String();
    final rows = await source.query(
      'sync_outbox',
      where: 'next_attempt_at IS NULL OR next_attempt_at <= ?',
      whereArgs: [nowIso],
      orderBy: 'id ASC',
      limit: batchSize,
    );
    return rows.map((r) {
      final rawPayload = r['payload'] as String?;
      return OutboxRecord(
        id: r['id'] as int,
        entity: r['entity'] as String,
        entityKey: r['entity_key'] as String,
        op: r['op'] as String,
        payload: rawPayload == null
            ? null
            : Map<String, dynamic>.from(jsonDecode(rawPayload) as Map),
        attempts: r['attempts'] as int,
      );
    }).toList();
  }

  Future<void> _ack(Database source, List<OutboxRecord> applied) async {
    await source.transaction((txn) async {
      for (final record in applied) {
        await txn.delete('sync_outbox', where: 'id = ?', whereArgs: [record.id]);
      }
    });
  }

  /// Exponential backoff with jitter, capped at 15 minutes (plan P1-3):
  /// `min(5s * 2^attempts, 15min) + jitter`.
  Future<void> _backoff(
    Database source,
    List<OutboxRecord> failed,
    String error,
  ) async {
    final random = Random();
    await source.transaction((txn) async {
      for (final record in failed) {
        final nextAttempts = record.attempts + 1;
        final baseDelay = Duration(seconds: 5 * pow(2, nextAttempts).toInt());
        final capped = baseDelay > const Duration(minutes: 15)
            ? const Duration(minutes: 15)
            : baseDelay;
        final jitterMs = random.nextInt(1000);
        final nextAttemptAt =
            DateTime.now().add(capped + Duration(milliseconds: jitterMs));
        await txn.update(
          'sync_outbox',
          {
            'attempts': nextAttempts,
            'last_error': error,
            'next_attempt_at': nextAttemptAt.toIso8601String(),
            'updated_at': DateTime.now().toIso8601String(),
          },
          where: 'id = ?',
          whereArgs: [record.id],
        );
      }
    });
  }

  Future<void> _updatePendingCount(List<Database> sources) async {
    var total = 0;
    for (final source in sources) {
      final result = await source.rawQuery('SELECT COUNT(*) AS c FROM sync_outbox');
      total += (result.first['c'] as num).toInt();
    }
    pendingCount.value = total;
  }
}
