// ignore_for_file: avoid_print

import 'dart:convert';
import 'dart:io';
import 'package:sqflite/sqflite.dart';
import 'package:path/path.dart' as p;

import '../models/capture_box_models.dart';

class TransferProtectionHandle {
  final String deviceId;
  final File localLockFile;
  final RandomAccessFile localLockRaf;

  const TransferProtectionHandle({
    required this.deviceId,
    required this.localLockFile,
    required this.localLockRaf,
  });
}

class UploadStatsDB {
  static final UploadStatsDB _instance = UploadStatsDB._internal();
  factory UploadStatsDB() => _instance;
  UploadStatsDB._internal();

  Database? _db;
  String? _currentDeviceId;
  String? _baseFolder;

  /// Monthly device DBs (upload_records/daily_summary/their own sync_outbox
  /// — see the "MONTHLY ROTATION" section below), keyed `deviceId|YYYY-MM`.
  final Map<String, Database> _monthlyDbs = {};

  /// Set once at startup from NodeConfig.syncEnabled. False (the default) ⇒
  /// every outbox hook below is a no-op and behavior is byte-identical to
  /// before the sync feature existed.
  bool syncEnabled = false;

  // =======================================================
  // PATH HANDLING
  // =======================================================

  Future<String> _ensurePathExists() async {
    if (_baseFolder != null && _baseFolder!.trim().isNotEmpty) {
      final cached = Directory(_baseFolder!);
      if (!cached.existsSync()) {
        await cached.create(recursive: true);
      }
      return cached.path;
    }

    Directory _resolvePrimaryDir() {
      final home =
          Platform.environment['USERPROFILE'] ??
          Platform.environment['HOME'] ??
          'C:\\';
      return Directory(p.join(home, 'LWCAM_DBs'));
    }

    Future<String> _prepare(Directory dir, {required bool fallback}) async {
      if (!dir.existsSync()) {
        await dir.create(recursive: true);
        print(
          fallback
              ? "📦 Created fallback DB folder at: ${dir.path}"
              : "📂 Created DB folder at: ${dir.path}",
        );
      } else {
        print(
          fallback
              ? "📦 Fallback DB folder verified: ${dir.path}"
              : "📁 DB folder verified: ${dir.path}",
        );
      }
      _baseFolder = dir.path;
      return dir.path;
    }

    try {
      return await _prepare(_resolvePrimaryDir(), fallback: false);
    } catch (e) {
      print("❌ Failed to access main DB path (home-based): $e");
      final fallbackBase = await getDatabasesPath();
      return await _prepare(
        Directory(p.join(fallbackBase, 'LWCAM_DBs')),
        fallback: true,
      );
    }
  }

  // =======================================================
  // PATH HELPERS (PUBLIC)
  // =======================================================

  Future<String> getBaseFolder() async => _ensurePathExists();

  /// Test-only seam: redirects the DB base folder away from the real
  /// `%USERPROFILE%\LWCAM_DBs` and drops any cached database
  /// handles, so tests never touch the real user's data. Not called from
  /// any production code path.
  void debugOverrideBaseFolderForTests(String path) {
    _baseFolder = path;
    _db = null;
    _currentDeviceId = null;
    _monthlyDbs.clear();
  }

  /// Test-only seam: closes any open device/monthly DB handles so a
  /// test's temp directory can be deleted afterward without a file-in-use
  /// error.
  Future<void> debugCloseAllForTests() async {
    try {
      await _db?.close();
    } catch (_) {}
    for (final db in _monthlyDbs.values) {
      try {
        await db.close();
      } catch (_) {}
    }
    _db = null;
    _currentDeviceId = null;
    _monthlyDbs.clear();
  }

  /// The STABLE per-device DB — long-lived operational state only as of the
  /// monthly-rotation change: capture_boxes/folders/images, replacement_records,
  /// sync_outbox, plus whatever upload_records/daily_summary rows predate
  /// rotation (kept as a frozen legacy read archive — see getMonthlyDbFilePath
  /// for where NEW rows of those two tables go).
  Future<String> getDeviceDbFilePath(String deviceId) async {
    final base = await _ensurePathExists();
    return p.join(base, 'lwcam_stats_$deviceId.db');
  }

  /// `YYYY-MM` for [d] — the monthly device DB file this date's
  /// upload_records/daily_summary rows belong in.
  String monthKeyFor(DateTime d) =>
      '${d.year.toString().padLeft(4, '0')}-${d.month.toString().padLeft(2, '0')}';

  /// The per-device, per-month DB holding upload_records + daily_summary
  /// (+ its own sync_outbox — see MONTHLY ROTATION below) for [monthKey].
  /// Shares the `lwcam_stats_` prefix with the stable DB so the existing
  /// directory scan (`_listMonthlyDbFilesForDevice`) picks it up with zero
  /// changes.
  Future<String> getMonthlyDbFilePath(String deviceId, String monthKey) async {
    final base = await _ensurePathExists();
    return p.join(base, 'lwcam_stats_${deviceId}_$monthKey.db');
  }

  Future<void> _ensureDbParentExists(String path) async {
    final file = File(path);
    final parent = file.parent;

    if (!parent.existsSync()) {
      await parent.create(recursive: true);
    }
  }

  Future<bool> _isDatabaseUsable(Database db) async {
    try {
      await db.rawQuery('SELECT 1');
      return true;
    } catch (_) {
      return false;
    }
  }

  // =======================================================
  // INITIALIZATION
  // =======================================================

  Future<Database> _initDB(String deviceId) async {
    final dbPath = await _ensurePathExists();
    final dbName = 'lwcam_stats_$deviceId.db';
    final path = p.join(dbPath, dbName);

    await _ensureDbParentExists(path);

    final dbFile = File(path);
    if (dbFile.existsSync() && dbFile.lengthSync() == 0) {
      try {
        dbFile.deleteSync();
      } catch (_) {}
    }

    print("📂 Using per-device database: $path");

    try {
      final db = await openDatabase(
        path,
        version: 1,
        onCreate: (db, version) async {
          await db.execute('''
            CREATE TABLE IF NOT EXISTS upload_records (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              scanning_opr TEXT,
              device_id TEXT,
              box_details TEXT,
              filename TEXT,
              format TEXT,
              created_at TEXT,
              cover_tag TEXT,
              image_tags TEXT,
              title TEXT,
              volume TEXT,
              start_date TEXT,
              end_date TEXT,
              archival_ref_no TEXT,
              record_type TEXT,
              place TEXT,
              language TEXT,
              record_custodian TEXT,
              digitizing_entity TEXT,
              capture_operator_id TEXT,
              capture_operator_name TEXT
            )
          ''');

          await db.execute('''
            CREATE TABLE IF NOT EXISTS daily_summary (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              scanning_opr TEXT,
              device_id TEXT,
              date TEXT,
              total_count INTEGER
            )
          ''');

          await db.execute('''
            CREATE TABLE IF NOT EXISTS replacement_records (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              device_id TEXT NOT NULL,
              scanning_opr TEXT,
              box_details TEXT,
              sequence_index INTEGER NOT NULL,
              date_key TEXT,
              original_filename TEXT NOT NULL,
              replacement_filename TEXT NOT NULL,
              replacement_local_path TEXT,
              replacement_type TEXT NOT NULL,
              confirmed_at TEXT NOT NULL,
              transferred_at TEXT,
              superseded_at TEXT,
              created_at TEXT NOT NULL
            )
          ''');

          await _createCaptureBoxTablesIfNotExists(db);

          await db.execute('''
            CREATE TABLE IF NOT EXISTS sync_outbox (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              entity TEXT NOT NULL,
              entity_key TEXT NOT NULL,
              op TEXT NOT NULL,
              payload TEXT,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              attempts INTEGER NOT NULL DEFAULT 0,
              last_error TEXT,
              next_attempt_at TEXT
            )
          ''');
          await db.execute(
            'CREATE UNIQUE INDEX IF NOT EXISTS idx_outbox_entity_key ON sync_outbox(entity, entity_key)',
          );

          // Restart-safe dedupe for the image-processing report agent: one
          // row per (LWIP input folder, fingerprint) that has already been
          // reported. A re-transfer changes the fingerprint → new key →
          // re-report (and qc_status resets to PENDING downstream). Stable
          // DB only, like the outbox — never rotates.
          await db.execute('''
            CREATE TABLE IF NOT EXISTS processing_ledger (
              input_path TEXT NOT NULL,
              fingerprint TEXT NOT NULL,
              reported_at TEXT NOT NULL,
              PRIMARY KEY (input_path, fingerprint)
            )
          ''');

          await _ensureDeviceIndexes(db);
        },
        onOpen: (db) async {
          await _configureDatabaseForConcurrentAccess(db);
        },
      );

      print("✅ Database opened successfully at: $path");
      return db;
    } catch (e) {
      print("❌ Failed to open database at $path: $e");
      rethrow;
    }
  }

  Future<Database> getDatabase(String deviceId) async {
    if (_db != null && _currentDeviceId == deviceId) {
      if (await _isDatabaseUsable(_db!)) return _db!;
      _db = null;
    }
    _currentDeviceId = deviceId;
    _db = await _initDB(deviceId);
    return _db!;
  }

  // =======================================================
  // MONTHLY ROTATION (upload_records / daily_summary only)
  // =======================================================
  //
  // Only the two high-volume, ever-growing tables rotate into a new file
  // each month — everything else (boxes/folders/images, replacement_records,
  // sync_outbox for those entities) stays in the ONE stable per-device DB
  // forever, since that's long-lived operational state that
  // can't be cut off at a month boundary (an open box, a pending sync row).
  // A record's month is its `created_at` MONTH, never wall-clock write time
  // — this guarantees a calendar day's rows always live in exactly one file,
  // which is what keeps _updateDailySummary's per-day recount exact.

  /// Opens (creating if needed) the monthly DB for [deviceId] — [forDate]'s
  /// month, or the current month if omitted. Cached per (deviceId, month);
  /// a session spanning a month rollover simply misses the cache on its next
  /// write and opens/creates the new file — no explicit rollover handling
  /// needed.
  Future<Database> getMonthlyDatabase(String deviceId, {DateTime? forDate}) {
    return _getMonthlyDatabaseForMonthKey(
      deviceId,
      monthKeyFor(forDate ?? DateTime.now()),
    );
  }

  Future<Database> _getMonthlyDatabaseForMonthKey(
    String deviceId,
    String monthKey,
  ) async {
    final cacheKey = '$deviceId|$monthKey';
    final cached = _monthlyDbs[cacheKey];
    if (cached != null) {
      if (await _isDatabaseUsable(cached)) return cached;
      _monthlyDbs.remove(cacheKey);
    }
    final db = await _initMonthlyDB(deviceId, monthKey);
    _monthlyDbs[cacheKey] = db;
    return db;
  }

  Future<Database> _initMonthlyDB(String deviceId, String monthKey) async {
    final path = await getMonthlyDbFilePath(deviceId, monthKey);
    await _ensureDbParentExists(path);

    final dbFile = File(path);
    if (dbFile.existsSync() && dbFile.lengthSync() == 0) {
      try {
        dbFile.deleteSync();
      } catch (_) {}
    }

    print("📂 Using monthly device database: $path");

    try {
      final db = await openDatabase(
        path,
        // Own schema line, independent of the stable DB's version — the
        // filename (not this number) is what disambiguates the two DB
        // families, so a fresh monthly file always starts at v1.
        version: 1,
        onCreate: (db, version) async {
          await _ensureMonthlyDbSchema(db);
        },
        onOpen: (db) async {
          await _configureDatabaseForConcurrentAccess(db);
          await _ensureMonthlyDbSchema(db);
        },
      );
      print("✅ Monthly database opened successfully at: $path");
      return db;
    } catch (e) {
      print("❌ Failed to open monthly database at $path: $e");
      rethrow;
    }
  }

  /// Lean schema: just the two high-volume local-only tables and the indexes
  /// every hot query here needs. No sync_outbox — upload_records stopped
  /// syncing when the cloud schema replaced it with capture_images, so the
  /// stable DB holds the only outbox.
  Future<void> _ensureMonthlyDbSchema(Database db) async {
    await db.execute('''
      CREATE TABLE IF NOT EXISTS upload_records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        scanning_opr TEXT,
        device_id TEXT,
        box_details TEXT,
        filename TEXT,
        format TEXT,
        created_at TEXT,
        cover_tag TEXT,
        image_tags TEXT,
        title TEXT,
        volume TEXT,
        start_date TEXT,
        end_date TEXT,
        archival_ref_no TEXT,
        record_type TEXT,
        place TEXT,
        language TEXT,
        record_custodian TEXT,
        digitizing_entity TEXT,
        capture_operator_id TEXT,
        capture_operator_name TEXT
      )
    ''');

    await db.execute('''
      CREATE TABLE IF NOT EXISTS daily_summary (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        scanning_opr TEXT,
        device_id TEXT,
        date TEXT,
        total_count INTEGER
      )
    ''');

    await db.execute(
      'CREATE INDEX IF NOT EXISTS idx_ur_device_filename ON upload_records(device_id, filename)',
    );
    await db.execute(
      'CREATE INDEX IF NOT EXISTS idx_ur_opr_created ON upload_records(device_id, scanning_opr, created_at)',
    );
    // UNIQUE here (unlike the stable DB's copy of this index): a monthly
    // file never has pre-existing legacy duplicates to worry about.
    await db.execute(
      'CREATE UNIQUE INDEX IF NOT EXISTS idx_ds_device_opr_date ON daily_summary(device_id, scanning_opr, date)',
    );
  }

  /// The monthKey encoded in a monthly DB filename for [deviceId], or null if
  /// [path] doesn't match that pattern (e.g. it's the stable DB, an unrelated
  /// file, or — critically — a WAL-mode `.db-wal`/`.db-shm` sidecar:
  /// `p.basenameWithoutExtension` only strips the text after the LAST dot,
  /// so "..._2026-01.db-wal" would otherwise still resolve to the same
  /// basename as "..._2026-01.db" and get double/triple-counted as the same
  /// month via a different File entry. Requiring the filename to literally
  /// end in ".db" rules those out.
  String? _monthKeyFromMonthlyFilename(String path, String deviceId) {
    final fullName = p.basename(path);
    if (!fullName.toLowerCase().endsWith('.db')) return null;
    final nameNoExt = fullName.substring(0, fullName.length - '.db'.length);
    final prefix = 'lwcam_stats_${deviceId}_';
    if (!nameNoExt.startsWith(prefix)) return null;
    final rest = nameNoExt.substring(prefix.length);
    return RegExp(r'^\d{4}-\d{2}$').hasMatch(rest) ? rest : null;
  }

  /// Every monthly DB file already on disk for [deviceId] (never creates
  /// one) — used by the spanning readers below and by SyncService to find
  /// outbox sources without ever manufacturing a new empty month.
  List<File> _listMonthlyDbFilesForDevice(String directoryPath, String deviceId) {
    final dir = Directory(directoryPath);
    if (!dir.existsSync()) return const <File>[];
    final files = dir
        .listSync(recursive: false, followLinks: false)
        .whereType<File>()
        .where((f) => _monthKeyFromMonthlyFilename(f.path, deviceId) != null)
        .toList();
    files.sort(
      (a, b) => p.basename(a.path).toLowerCase().compareTo(p.basename(b.path).toLowerCase()),
    );
    return files;
  }

  /// Every DB connection that may hold upload_records/daily_summary rows for
  /// [deviceId]: the stable DB (legacy, frozen rows) plus every monthly file
  /// that already exists on disk — spanning reads (skip-logic, stats) must
  /// see all of them; hot per-insert writes do not (see
  /// insertUploadRecord's targeted dedup lookback instead).
  Future<List<Database>> _allDeviceUploadDatabases(String deviceId) async {
    final stable = await getDatabase(deviceId);
    final base = await _ensurePathExists();
    final monthlyFiles = _listMonthlyDbFilesForDevice(base, deviceId);
    final result = <Database>[stable];
    for (final file in monthlyFiles) {
      final monthKey = _monthKeyFromMonthlyFilename(file.path, deviceId);
      if (monthKey == null) continue;
      try {
        result.add(await _getMonthlyDatabaseForMonthKey(deviceId, monthKey));
      } catch (e) {
        print('⚠️ Failed to open monthly DB ${file.path}: $e');
      }
    }
    return result;
  }

  /// Public for `SyncService`: every DB that may hold pending `sync_outbox`
  /// rows for [deviceId]. Since upload_records left the sync pipeline, only
  /// the stable DB carries an outbox (boxes/folders/images all live there).
  Future<List<Database>> getOutboxDatabases(String deviceId) async =>
      [await getDatabase(deviceId)];

  Future<void> _configureDatabaseForConcurrentAccess(Database db) async {
    try {
      await db.execute('PRAGMA journal_mode=WAL');
    } catch (e) {
      print('⚠️ Failed to enable WAL mode: $e');
    }

    try {
      await db.execute('PRAGMA synchronous=NORMAL');
    } catch (_) {}

    try {
      await db.execute('PRAGMA busy_timeout = 60000');
    } catch (_) {}
  }

  Future<void> checkpointDatabases(String deviceId) async {
    final deviceDbPath = await getDeviceDbFilePath(deviceId);
    if (File(deviceDbPath).existsSync()) {
      try {
        final deviceDb = await getDatabase(deviceId);
        await deviceDb.execute('PRAGMA wal_checkpoint(TRUNCATE)');
      } catch (e) {
        print('⚠️ Device DB checkpoint failed for $deviceId: $e');
      }
    }

    // Checkpoint every currently-cached monthly DB for this device, then
    // evict (close) any that aren't the current month — keeps the cache from
    // holding handles open forever across a long-running session that spans
    // several months.
    final currentMonthKey = monthKeyFor(DateTime.now());
    final devicePrefix = '$deviceId|';
    final staleKeys = <String>[];
    for (final entry in _monthlyDbs.entries) {
      if (!entry.key.startsWith(devicePrefix)) continue;
      try {
        await entry.value.execute('PRAGMA wal_checkpoint(TRUNCATE)');
      } catch (e) {
        print('⚠️ Monthly DB checkpoint failed for ${entry.key}: $e');
      }
      if (entry.key.substring(devicePrefix.length) != currentMonthKey) {
        staleKeys.add(entry.key);
      }
    }
    for (final key in staleKeys) {
      final db = _monthlyDbs.remove(key);
      try {
        await db?.close();
      } catch (_) {}
    }
  }

  Future<TransferProtectionHandle> acquireTransferProtection({
    required String deviceId,
    required String scanningOpr,
  }) async {
    final localBaseFolder = await getBaseFolder();
    final localLockFile = File(
      p.join(localBaseFolder, 'lwcam_transfer_in_progress.lock'),
    );

    RandomAccessFile? localLockRaf;

    final metadata = _buildTransferLockMetadata(
      deviceId: deviceId,
      scanningOpr: scanningOpr,
    );

    try {
      localLockRaf = await _openLockedFile(localLockFile, metadata);

      final deviceDbPath = await getDeviceDbFilePath(deviceId);
      if (File(deviceDbPath).existsSync()) {
        try {
          await _configureDatabaseForConcurrentAccess(
            await getDatabase(deviceId),
          );
        } catch (e) {
          print(
            '⚠️ Skipping device DB protection configuration for $deviceId: $e',
          );
        }
      }

      // Always (not gated on existsSync) — a transfer starting in a brand
      // new month must open/create that month's file and WAL-configure it
      // from the very first write.
      try {
        await _configureDatabaseForConcurrentAccess(
          await getMonthlyDatabase(deviceId),
        );
      } catch (e) {
        print(
          '⚠️ Skipping monthly device DB protection configuration for $deviceId: $e',
        );
      }

      return TransferProtectionHandle(
        deviceId: deviceId,
        localLockFile: localLockFile,
        localLockRaf: localLockRaf,
      );
    } catch (e) {
      if (localLockRaf != null) {
        await _safeUnlockAndClose(localLockRaf, localLockFile);
      }
      rethrow;
    }
  }

  Future<void> releaseTransferProtection(
    TransferProtectionHandle handle,
  ) async {
    try {
      await checkpointDatabases(handle.deviceId);
    } catch (e) {
      print('⚠️ Failed to checkpoint DBs while releasing protection: $e');
    }

    await _safeUnlockAndClose(handle.localLockRaf, handle.localLockFile);
  }

  String _buildTransferLockMetadata({
    required String deviceId,
    required String scanningOpr,
  }) {
    final startedAt = DateTime.now().toIso8601String();
    return [
      'TRANSFER_IN_PROGRESS=1',
      'device_id=$deviceId',
      'scanning_opr=$scanningOpr',
      'started_at=$startedAt',
      'warning=Do not open or copy database files while transfer is active.',
    ].join('\n');
  }

  Future<RandomAccessFile> _openLockedFile(File file, String metadata) async {
    if (!file.existsSync()) {
      await file.create(recursive: true);
    }

    final raf = await file.open(mode: FileMode.write);
    await raf.lock(FileLock.exclusive);
    await raf.truncate(0);
    await raf.writeString(metadata);
    await raf.flush();
    return raf;
  }

  Future<void> _safeUnlockAndClose(RandomAccessFile? raf, File? file) async {
    if (raf != null) {
      try {
        await raf.unlock();
      } catch (_) {}
      try {
        await raf.close();
      } catch (_) {}
    }

    if (file != null && file.existsSync()) {
      try {
        await file.delete();
      } catch (_) {}
    }
  }

  // =======================================================
  // INSERT / UPDATE UPLOAD RECORD
  // =======================================================

  Future<bool> _uploadRecordExistsInDb(
    Database db,
    String deviceId,
    String filename,
  ) async {
    try {
      final rows = await db.query(
        'upload_records',
        where: 'device_id = ? AND filename = ?',
        whereArgs: [deviceId, filename],
        limit: 1,
      );
      return rows.isNotEmpty;
    } catch (_) {
      return false;
    }
  }

  /// Dedup lookback for a single insert: the target month's file (the
  /// common case), the current month's file if different (a backdated
  /// createdAt), and the stable DB's frozen legacy rows. Deliberately does
  /// NOT scan every historical monthly file — that's `getUploadedBaseNames`'s
  /// job (the real "skip already-uploaded" gate, run once per batch); a miss
  /// here costs at most one duplicate file copy, never a duplicate row.
  Future<bool> _uploadRecordExistsAnywhere(
    String deviceId,
    String filename,
    DateTime createdAt,
  ) async {
    final targetDb = await getMonthlyDatabase(deviceId, forDate: createdAt);
    if (await _uploadRecordExistsInDb(targetDb, deviceId, filename)) {
      return true;
    }

    final targetMonthKey = monthKeyFor(createdAt);
    final currentMonthKey = monthKeyFor(DateTime.now());
    if (currentMonthKey != targetMonthKey) {
      final currentDb = await getMonthlyDatabase(deviceId);
      if (await _uploadRecordExistsInDb(currentDb, deviceId, filename)) {
        return true;
      }
    }

    final stableDb = await getDatabase(deviceId);
    return _uploadRecordExistsInDb(stableDb, deviceId, filename);
  }

  /// Call this ONLY after a successful upload that should be counted.
  /// If the same device+filename already exists, this will NOT insert
  /// another record (overwrite case) and will not bump totals.
  Future<void> insertUploadRecord({
    required String deviceId,
    required String scanningOpr,
    required String boxDetails,
    required String filename,
    required String format,
    required DateTime createdAt,
    // Metadata snapshot columns (null when keying is disabled) — the values
    // that went onto this row's CSV line, kept for the record.
    String? coverTag,
    String? imageTags,
    String? title,
    String? volume,
    String? startDate,
    String? endDate,
    String? archivalRefNo,
    String? recordType,
    // Template fixed-field values (v7) — null when keying is disabled or the
    // corresponding field is disabled in the project's template.
    String? place,
    String? language,
    String? recordCustodian,
    String? digitizingEntity,
    String? captureOperatorId,
    String? captureOperatorName,
  }) async {
    // Rows are routed by their CAPTURE month (createdAt), not wall-clock
    // write time — a July-31 capture transferred on Aug 1 still lands in
    // July's file, so a calendar day's rows are never split across two DBs
    // (see MONTHLY ROTATION above; that invariant is what keeps
    // _updateDailySummary's per-day recount exact).
    final db = await getMonthlyDatabase(deviceId, forDate: createdAt);

    if (await _uploadRecordExistsAnywhere(deviceId, filename, createdAt)) {
      // This is likely an overwrite (e.g., user chose "All Images"
      // including previously uploaded ones). Don't count again.
      print(
        'ℹ️ Skipping DB insert for $filename '
        '(already recorded for device $deviceId).',
      );
      return;
    }

    final row = {
      'scanning_opr': scanningOpr,
      'device_id': deviceId,
      'box_details': boxDetails,
      'filename': filename,
      'format': format,
      'created_at': createdAt.toIso8601String(),
      'cover_tag': coverTag,
      'image_tags': imageTags,
      'title': title,
      'volume': volume,
      'start_date': startDate,
      'end_date': endDate,
      'archival_ref_no': archivalRefNo,
      'record_type': recordType,
      'place': place,
      'language': language,
      'record_custodian': recordCustodian,
      'digitizing_entity': digitizingEntity,
      'capture_operator_id': captureOperatorId,
      'capture_operator_name': captureOperatorName,
    };

    // Local record-keeping only — the cloud schema has no upload_records
    // table (capture_images, enqueued at assignment time, replaced it).
    await db.transaction((txn) async {
      await txn.insert('upload_records', row);
      // Recalculate today's count based on actual successful records.
      await _updateDailySummary(txn, deviceId, scanningOpr, createdAt);
    });

    print('🆕 Added upload record: $filename (Device: $deviceId)');
  }

  // =======================================================
  // DAILY SUMMARY UPDATE (PER DEVICE DB)
  // =======================================================

  /// Ensure daily_summary.total_count matches the number of successful
  /// uploads for this device + operator on that calendar day.
  Future<void> _updateDailySummary(
    DatabaseExecutor db,
    String deviceId,
    String scanningOpr,
    DateTime date,
  ) async {
    final todayStr =
        '${date.year}-${date.month.toString().padLeft(2, '0')}-${date.day.toString().padLeft(2, '0')}';
    final nextDay = DateTime(date.year, date.month, date.day + 1);
    final nextDayStr =
        '${nextDay.year}-${nextDay.month.toString().padLeft(2, '0')}-${nextDay.day.toString().padLeft(2, '0')}';

    // Count successful uploads from upload_records for this day/operator/device.
    // A half-open range (not LIKE 'date%') so idx_ur_opr_created can actually
    // be used — SQLite's LIKE optimization doesn't apply here since the
    // pattern isn't a plain prefix constant known at prepare time in every
    // driver path, and a range predicate is the reliably-indexable form.
    final countResult = await db.rawQuery(
      '''
      SELECT COUNT(*) AS total
      FROM upload_records
      WHERE device_id = ?
        AND scanning_opr = ?
        AND created_at >= ?
        AND created_at < ?
      ''',
      [deviceId, scanningOpr, todayStr, nextDayStr],
    );

    final totalForDay = (countResult.first['total'] as int?) ?? 0;

    final existing = await db.query(
      'daily_summary',
      where: 'device_id = ? AND scanning_opr = ? AND date = ?',
      whereArgs: [deviceId, scanningOpr, todayStr],
      limit: 1,
    );

    if (existing.isEmpty) {
      await db.insert('daily_summary', {
        'scanning_opr': scanningOpr,
        'device_id': deviceId,
        'date': todayStr,
        'total_count': totalForDay,
      });
    } else {
      final id = existing.first['id'];
      await db.update(
        'daily_summary',
        {'total_count': totalForDay},
        where: 'id = ?',
        whereArgs: [id],
      );
    }

    print(
      '📅 Daily summary updated for $todayStr — '
      'Device: $deviceId, Opr: $scanningOpr, Count: $totalForDay',
    );
  }

  // =======================================================
  // SUMMARY RETRIEVAL (PER DEVICE)
  // =======================================================

  /// Sums across the stable DB (legacy rows) and every monthly file — a
  /// device's daily_summary history now lives split across several files.
  Future<Map<String, int>> getTransferStats(String deviceId) async {
    final now = DateTime.now();
    final todayStr =
        '${now.year}-${now.month.toString().padLeft(2, '0')}-${now.day.toString().padLeft(2, '0')}';

    var totalAllTime = 0;
    var totalToday = 0;
    for (final db in await _allDeviceUploadDatabases(deviceId)) {
      try {
        final totalResult = await db.rawQuery(
          'SELECT SUM(total_count) as total FROM daily_summary',
        );
        totalAllTime += (totalResult.first['total'] as int?) ?? 0;

        final todayResult = await db.rawQuery(
          'SELECT SUM(total_count) as total FROM daily_summary WHERE date = ?',
          [todayStr],
        );
        totalToday += (todayResult.first['total'] as int?) ?? 0;
      } catch (_) {
        // Table missing in this source — nothing to add.
      }
    }

    return {'today': totalToday, 'allTime': totalAllTime};
  }

  // =======================================================
  // REPLACEMENT RECORDS
  // =======================================================

  /// replacement_records is local-operational state only (recapture overlay
  /// restoration + transfer-time verification read it back — see
  /// gallery_page.dart/box_session_controller.dart) — it is deliberately
  /// NEVER synced to the cloud PG (local-operational data only).
  Future<void> insertReplacementRecord({
    required String deviceId,
    required int sequenceIndex,
    required String dateKey,
    required String originalFilename,
    required String replacementFilename,
    required String replacementLocalPath,
    String scanningOpr = '',
    String boxDetails = '',
    String replacementType = 'recapture',
    DateTime? confirmedAt,
  }) async {
    final db = await getDatabase(deviceId);
    final now = (confirmedAt ?? DateTime.now()).toIso8601String();
    await db.insert('replacement_records', {
      'device_id': deviceId,
      'scanning_opr': scanningOpr,
      'box_details': boxDetails,
      'sequence_index': sequenceIndex,
      'date_key': dateKey,
      'original_filename': originalFilename,
      'replacement_filename': replacementFilename,
      'replacement_local_path': replacementLocalPath,
      'replacement_type': replacementType,
      'confirmed_at': now,
      'transferred_at': null,
      'created_at': now,
    });
  }

  /// Marks every still-active replacement record of [originalFilename] as
  /// superseded instead of deleting it, preserving the slot's replacement
  /// history for auditing (local only — see class-level note above).
  Future<int> markReplacementRecordsSuperseded({
    required String deviceId,
    required String originalFilename,
    DateTime? supersededAt,
  }) async {
    final db = await getDatabase(deviceId);
    return db.update(
      'replacement_records',
      {'superseded_at': (supersededAt ?? DateTime.now()).toIso8601String()},
      where:
          'device_id = ? AND original_filename = ? AND superseded_at IS NULL',
      whereArgs: [deviceId, originalFilename],
    );
  }

  /// Marks one specific (original, replacement) record as superseded.
  Future<int> markReplacementRecordSuperseded({
    required String deviceId,
    required String originalFilename,
    required String replacementFilename,
    DateTime? supersededAt,
  }) async {
    final db = await getDatabase(deviceId);
    return db.update(
      'replacement_records',
      {'superseded_at': (supersededAt ?? DateTime.now()).toIso8601String()},
      where:
          'device_id = ? AND original_filename = ? AND '
          'replacement_filename = ? AND superseded_at IS NULL',
      whereArgs: [deviceId, originalFilename, replacementFilename],
    );
  }

  /// Returns replacement records for [deviceId]. With [activeOnly] (the
  /// default) superseded records are excluded — pass false to read the full
  /// replacement history of every slot.
  Future<List<Map<String, dynamic>>> getReplacementRecords(
    String deviceId, {
    bool activeOnly = true,
  }) async {
    final db = await getDatabase(deviceId);
    return db.query(
      'replacement_records',
      where: activeOnly
          ? 'device_id = ? AND superseded_at IS NULL'
          : 'device_id = ?',
      whereArgs: [deviceId],
      orderBy: 'sequence_index ASC, id ASC',
    );
  }

  // =======================================================
  // CAPTURE BOXES / FOLDERS — Box→Folders workflow
  // =======================================================
  //
  // Per-device operational state, mirrored to Postgres only via the
  // capture_boxes/capture_folders sync outbox entries below.

  /// Local mirrors of the cloud entities in LWCam_database_20260720.sql —
  /// same column names, full-CAPS statuses — plus local-only columns grouped
  /// at the bottom of each table (excluded from sync payload consumption by
  /// the sink). The QC-owned pipeline columns (group_id, client_qc_status,
  /// client_rework) remain absent: LWCAM never writes them and PG fills their
  /// defaults on INSERT. The image-PROCESSING columns (is_deskewed/is_cropped/
  /// is_created_thumbnail/folder_path/thumbnail_path/qc_status) ARE mirrored
  /// on capture_folders as of the LWIP integration — LWCAM writes them via
  /// recordFolderProcessing (local UPDATE + the capture_folder_processing
  /// outbox entity), never through folderUpsertSql.
  Future<void> _createCaptureBoxTablesIfNotExists(Database db) async {
    await db.execute('''
      CREATE TABLE IF NOT EXISTS capture_boxes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        box_name TEXT NOT NULL,
        device_id TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'OPEN',
        user_id TEXT,
        project_id TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        transfer_start_at TEXT,
        transfer_end_at TEXT,
        transferred_to TEXT,
        -- local-only ↓
        renamed_from TEXT,
        last_active_folder_id INTEGER,
        project_key TEXT,
        template_json TEXT,
        last_transfer_state TEXT,
        last_transfer_error TEXT
      )
    ''');

    await db.execute('''
      CREATE TABLE IF NOT EXISTS capture_folders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        box_id INTEGER NOT NULL,
        folder_seq INTEGER NOT NULL,
        folder_name TEXT,
        cover_tag TEXT,
        image_tags TEXT,
        title TEXT,
        volume TEXT,
        start_date TEXT,
        end_date TEXT,
        archival_ref_no TEXT,
        record_type TEXT,
        place TEXT,
        language TEXT,
        record_custodian TEXT,
        capture_operator_id TEXT,
        capture_operator_name TEXT,
        digitizing_entity TEXT,
        source_created_at TEXT NOT NULL,
        source_updated_at TEXT NOT NULL,
        -- image-processing result (mirrors the cloud pipeline columns;
        -- written by recordFolderProcessing, never by a folder upsert) ↓
        is_deskewed INTEGER NOT NULL DEFAULT 0,
        is_cropped INTEGER NOT NULL DEFAULT 0,
        is_created_thumbnail INTEGER NOT NULL DEFAULT 0,
        folder_path TEXT,
        thumbnail_path TEXT,
        qc_status TEXT NOT NULL DEFAULT 'PENDING',
        -- local-only ↓
        is_complete INTEGER NOT NULL DEFAULT 0,
        UNIQUE(box_id, folder_seq)
      )
    ''');

    await db.execute('''
      CREATE TABLE IF NOT EXISTS capture_images (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        image_name TEXT NOT NULL UNIQUE,
        device_id TEXT NOT NULL,
        folder_id INTEGER NOT NULL,
        file_format TEXT NOT NULL,
        image_created_at TEXT NOT NULL,
        image_updated_at TEXT,
        -- local-only ↓
        box_id INTEGER NOT NULL
      )
    ''');
    await db.execute(
        'CREATE INDEX IF NOT EXISTS idx_ci_folder ON capture_images(folder_id)');
  }

  // =======================================================
  // SYNC (device DB) — durable outbox, natural keys on the wire
  // =======================================================
  //
  // Outbox entity_key is the LOCAL row id (boxes/folders: '<id>'; images:
  // '<folderId>|<imageName>') — it only needs to coalesce repeated edits of
  // the same local row. Cloud identity is resolved by the sink from natural
  // keys carried in the payload: users.user_id (username),
  // projects.project_key (the stable client identity — NEVER project_id,
  // which is a human-editable label LWCam Admin can rename freely),
  // devices.device_id (SAX##), capture_boxes (project, box_name),
  // capture_folders (box, folder_seq), capture_images (folder, image_name)
  // — matching the UNIQUE constraints in LWCam_database_20260720.sql.

  // =======================================================
  // INDEXES (device DB)
  // =======================================================

  /// Indexes on the columns every hot query filters/joins by (dedup on
  /// insert, per-day summary recount, per-box image counts, replacement
  /// lookups).
  Future<void> _ensureDeviceIndexes(Database db) async {
    await db.execute(
      'CREATE INDEX IF NOT EXISTS idx_ur_device_filename ON upload_records(device_id, filename)',
    );
    await db.execute(
      'CREATE INDEX IF NOT EXISTS idx_ur_opr_created ON upload_records(device_id, scanning_opr, created_at)',
    );
    await db.execute(
      'CREATE INDEX IF NOT EXISTS idx_ds_device_opr_date ON daily_summary(device_id, scanning_opr, date)',
    );
    await db.execute(
      'CREATE INDEX IF NOT EXISTS idx_rr_device_original ON replacement_records(device_id, original_filename)',
    );
    await db.execute(
      'CREATE INDEX IF NOT EXISTS idx_ci_box ON capture_images(box_id)',
    );
  }

  /// Enqueues a payload-snapshot outbox row for `SyncService` to drain later.
  /// A no-op when [syncEnabled] is false, so callers may call this
  /// unconditionally. `INSERT OR REPLACE` against the `UNIQUE(entity,
  /// entity_key)` index coalesces repeated edits of the same row into a
  /// single pending outbox entry carrying the latest snapshot (see
  /// the SYNC section comment above). Always called from the same transaction as the
  /// domain write it accompanies, so the two can never disagree after a
  /// crash.
  Future<void> _enqueueOutbox(
    DatabaseExecutor txn, {
    required String entity,
    required String entityKey,
    required String op,
    Map<String, dynamic>? payload,
  }) async {
    if (!syncEnabled) return;
    final now = DateTime.now().toIso8601String();
    await txn.insert(
      'sync_outbox',
      {
        'entity': entity,
        'entity_key': entityKey,
        'op': op,
        'payload': payload == null ? null : jsonEncode(payload),
        'created_at': now,
        'updated_at': now,
        'attempts': 0,
        'last_error': null,
        'next_attempt_at': null,
      },
      conflictAlgorithm: ConflictAlgorithm.replace,
    );
  }

  /// Re-reads a single row by local id, for building an outbox payload after
  /// a write. Returns null if the row is gone (caller's write raced a
  /// delete elsewhere in the same transaction — nothing to enqueue).
  Future<Map<String, dynamic>?> _snapshotRow(
    DatabaseExecutor txn,
    String table,
    int id,
  ) async {
    final rows = await txn.query(table, where: 'id = ?', whereArgs: [id], limit: 1);
    return rows.isEmpty ? null : Map<String, dynamic>.from(rows.first);
  }

  // ── Boxes ────────────────────────────────────────────────────────────────

  Future<int> insertCaptureBox({
    required String deviceId,
    required String boxDetails,
    String? scanningOpr,
    String? projectKey,
    String? projectId,
    String? templateJson,
  }) async {
    final db = await getDatabase(deviceId);
    final now = DateTime.now().toIso8601String();
    final row = {
      'box_name': boxDetails.trim(),
      'device_id': deviceId,
      'status': 'OPEN',
      'user_id': scanningOpr,
      'project_id': projectId,
      'created_at': now,
      'updated_at': now,
      'project_key': projectKey,
      'template_json': templateJson,
    };
    return db.transaction((txn) async {
      final id = await txn.insert('capture_boxes', row);
      await _enqueueOutbox(
        txn,
        entity: 'capture_boxes',
        entityKey: '$id',
        op: 'upsert',
        payload: {...row, 'id': id},
      );
      return id;
    });
  }

  /// All boxes for this device: open first, newest first within status.
  /// When [projectKey] is supplied, only boxes stamped with that project are
  /// returned; null keeps the previous unfiltered behavior.
  Future<List<CaptureBox>> getCaptureBoxes(String deviceId, {String? projectKey}) async {
    final db = await getDatabase(deviceId);
    final rows = await db.query(
      'capture_boxes',
      where: projectKey == null ? 'device_id = ?' : 'device_id = ? AND project_key = ?',
      whereArgs: projectKey == null ? [deviceId] : [deviceId, projectKey],
      orderBy: "CASE status WHEN 'OPEN' THEN 0 ELSE 1 END ASC, created_at DESC",
    );
    return rows.map(CaptureBox.fromDbMap).toList();
  }

  Future<CaptureBox?> getCaptureBoxById({
    required String deviceId,
    required int boxId,
  }) async {
    final db = await getDatabase(deviceId);
    final rows =
        await db.query('capture_boxes', where: 'id = ?', whereArgs: [boxId], limit: 1);
    return rows.isEmpty ? null : CaptureBox.fromDbMap(rows.first);
  }

  /// Renames a box's details. Only meaningful for an OPEN box — folder
  /// destination names are computed from box_details at transfer time, so a
  /// correction here fixes every folder's name without touching them.
  Future<void> updateCaptureBoxDetails({
    required String deviceId,
    required int boxId,
    required String boxDetails,
  }) async {
    final db = await getDatabase(deviceId);
    await db.transaction((txn) async {
      // The cloud row is keyed by (project_id, box_name), so a rename must
      // carry the OLD name for the sink's rename fixup. Set only-if-null: it
      // must keep pointing at the name PG last saw, not an intermediate one.
      // ponytail: a second rename in a later sync tick (after the fixup ran
      // and cleared nothing here) can orphan a cloud row — renames are
      // pre-transfer typo fixes; revisit only if that stops being true.
      await txn.rawUpdate(
        'UPDATE capture_boxes SET renamed_from = COALESCE(renamed_from, box_name), '
        'box_name = ?, updated_at = ? WHERE id = ?',
        [boxDetails.trim(), DateTime.now().toIso8601String(), boxId],
      );
      await _enqueueCaptureBoxUpsert(txn, boxId);
    });
  }

  /// Stamps the moment a background transfer for [boxId] begins (cloud
  /// `transfer_start_at`). Re-stamped on every attempt, including retries.
  Future<void> markCaptureBoxTransferStarted({
    required String deviceId,
    required int boxId,
  }) async {
    final db = await getDatabase(deviceId);
    await db.transaction((txn) async {
      await txn.update(
        'capture_boxes',
        {
          'transfer_start_at': DateTime.now().toIso8601String(),
          'updated_at': DateTime.now().toIso8601String(),
        },
        where: 'id = ?',
        whereArgs: [boxId],
      );
      await _enqueueCaptureBoxUpsert(txn, boxId);
    });
  }

  Future<void> markCaptureBoxTransferred({
    required String deviceId,
    required int boxId,
    String? transferredTo,
  }) async {
    final db = await getDatabase(deviceId);
    await db.transaction((txn) async {
      await txn.update(
        'capture_boxes',
        {
          'status': 'TRANSFERRED',
          'transfer_end_at': DateTime.now().toIso8601String(),
          'updated_at': DateTime.now().toIso8601String(),
          if (transferredTo != null) 'transferred_to': transferredTo,
          // A full success clears any lingering failure/interrupted marker.
          'last_transfer_state': null,
          'last_transfer_error': null,
        },
        where: 'id = ?',
        whereArgs: [boxId],
      );
      await _enqueueCaptureBoxUpsert(txn, boxId);
    });
  }

  /// Persists a box's transfer outcome so it survives restart/re-login and
  /// the box list can show it at a glance: 'running' is written when a
  /// background transfer starts (a leftover 'running' at next login means the
  /// transfer was cut off — power loss/crash), 'partial'/'failed' on the
  /// terminal outcomes, null to clear. Local operational state only — like
  /// setBoxActiveFolder, deliberately NOT enqueued to the sync outbox (the
  /// columns never enter outbox-consumed statements — see pg_statements.dart).
  Future<void> setBoxTransferState({
    required String deviceId,
    required int boxId,
    String? state,
    String? error,
  }) async {
    final db = await getDatabase(deviceId);
    await db.update(
      'capture_boxes',
      {'last_transfer_state': state, 'last_transfer_error': error},
      where: 'id = ?',
      whereArgs: [boxId],
    );
  }

  /// Re-reads box [boxId] and enqueues its current state, when sync is on.
  /// Shared by every capture_boxes update hook.
  Future<void> _enqueueCaptureBoxUpsert(DatabaseExecutor txn, int boxId) async {
    if (!syncEnabled) return;
    final snapshot = await _snapshotRow(txn, 'capture_boxes', boxId);
    if (snapshot == null) return;
    await _enqueueOutbox(
      txn,
      entity: 'capture_boxes',
      entityKey: '$boxId',
      op: 'upsert',
      payload: snapshot,
    );
  }

  /// Persists which folder the operator is capturing into — restored as the
  /// active folder next time the box is opened (see CaptureBox.lastActiveFolderId).
  Future<void> setBoxActiveFolder({
    required String deviceId,
    required int boxId,
    required int folderId,
  }) async {
    final db = await getDatabase(deviceId);
    await db.update(
      'capture_boxes',
      {'last_active_folder_id': folderId},
      where: 'id = ?',
      whereArgs: [boxId],
    );
  }

  // ── Folders ──────────────────────────────────────────────────────────────

  /// Inserts a folder with the next folder_seq for its box (allocated inside
  /// a transaction so two rapid inserts can't collide). Returns the new id.
  /// [isComplete] is caller-supplied — resolved from the box's metadata
  /// template (see MetadataTemplate.isCompleteOf), since completeness is no
  /// longer a context-free property of the folder alone.
  Future<int> insertCaptureFolder({
    required String deviceId,
    required CaptureFolder folder,
    required bool isComplete,
    String? captureOperatorName,
  }) async {
    final db = await getDatabase(deviceId);
    return db.transaction((txn) async {
      final seqRows = await txn.rawQuery(
        'SELECT COALESCE(MAX(folder_seq), 0) + 1 AS next_seq FROM capture_folders WHERE box_id = ?',
        [folder.boxId],
      );
      final nextSeq = (seqRows.first['next_seq'] as num).toInt();
      final now = DateTime.now().toIso8601String();
      final map =
          folder.copyWith(folderSeq: nextSeq).toDbMap(isComplete: isComplete);
      map['source_created_at'] = now;
      map['source_updated_at'] = now;
      map['capture_operator_id'] = deviceId;
      map['capture_operator_name'] = captureOperatorName;
      final id = await txn.insert('capture_folders', map);
      await _enqueueCaptureFolderUpsert(txn, id);
      return id;
    });
  }

  /// Updates a folder's keyed metadata (identity/seq/name untouched).
  /// [isComplete] is caller-supplied (see [insertCaptureFolder]).
  Future<void> updateCaptureFolderMetadata({
    required String deviceId,
    required CaptureFolder folder,
    required bool isComplete,
  }) async {
    final db = await getDatabase(deviceId);
    await db.transaction((txn) async {
      await txn.update(
        'capture_folders',
        {
          'cover_tag': folder.coverTag,
          'image_tags': folder.imageTags,
          'title': folder.title,
          'volume': folder.volume,
          'start_date': folder.startDate,
          'end_date': folder.endDate,
          'archival_ref_no': folder.archivalRefNo,
          'is_complete': isComplete ? 1 : 0,
          'source_updated_at': DateTime.now().toIso8601String(),
        },
        where: 'id = ?',
        whereArgs: [folder.id],
      );
      await _enqueueCaptureFolderUpsert(txn, folder.id);
    });
  }

  /// Persists the transfer-time computed destination name (and optionally the
  /// finalized volume for numberless folders) — see computeFolderNames.
  Future<void> updateCaptureFolderName({
    required String deviceId,
    required int folderId,
    required String folderName,
    String? finalizedVolume,
  }) async {
    final db = await getDatabase(deviceId);
    await db.transaction((txn) async {
      await txn.update(
        'capture_folders',
        {
          'folder_name': folderName,
          if (finalizedVolume != null) 'volume': finalizedVolume,
          'source_updated_at': DateTime.now().toIso8601String(),
        },
        where: 'id = ?',
        whereArgs: [folderId],
      );
      await _enqueueCaptureFolderUpsert(txn, folderId);
    });
  }

  /// Persists the template's effective fixed-field values at transfer prep —
  /// the cloud capture_folders row carries them as real columns, so they
  /// must exist locally too (not just on upload_records/CSV lines).
  Future<void> updateCaptureFolderFixedValues({
    required String deviceId,
    required int folderId,
    String? place,
    String? language,
    String? recordCustodian,
    String? digitizingEntity,
  }) async {
    final db = await getDatabase(deviceId);
    await db.transaction((txn) async {
      await txn.update(
        'capture_folders',
        {
          'place': place,
          'language': language,
          'record_custodian': recordCustodian,
          'digitizing_entity': digitizingEntity,
          'source_updated_at': DateTime.now().toIso8601String(),
        },
        where: 'id = ?',
        whereArgs: [folderId],
      );
      await _enqueueCaptureFolderUpsert(txn, folderId);
    });
  }

  /// The parent box's cloud natural keys, joined into folder/image payloads
  /// so the sink can resolve the PG box row: project_key (FK resolution) +
  /// box_name, plus renamed_from for the rename fixup and device_id for the
  /// devices FK.
  Future<Map<String, dynamic>> _parentBoxKeys(
      DatabaseExecutor txn, Object? boxId) async {
    final rows = await txn.query(
      'capture_boxes',
      columns: ['box_name', 'project_id', 'project_key', 'renamed_from', 'device_id'],
      where: 'id = ?',
      whereArgs: [boxId],
      limit: 1,
    );
    if (rows.isEmpty) return const {};
    final r = rows.first;
    return {
      'box_name': r['box_name'],
      'project_id': r['project_id'],
      'project_key': r['project_key'],
      'renamed_from': r['renamed_from'],
      'device_id': r['device_id'],
    };
  }

  /// Re-reads folder [folderId] and enqueues its current state, when sync is
  /// on. Shared by every capture_folders write hook (insert included) so the
  /// payload's parent natural keys are always freshly joined in — never
  /// sourced from a caller-local variable that a later coalesced edit could
  /// drop.
  Future<void> _enqueueCaptureFolderUpsert(DatabaseExecutor txn, int folderId) async {
    if (!syncEnabled) return;
    final snapshot = await _snapshotRow(txn, 'capture_folders', folderId);
    if (snapshot == null) return;
    snapshot.addAll(await _parentBoxKeys(txn, snapshot['box_id']));
    await _enqueueOutbox(
      txn,
      entity: 'capture_folders',
      entityKey: '$folderId',
      op: 'upsert',
      payload: snapshot,
    );
  }

  // ── Image-processing results (LWIP integration) ───────────────────────────

  /// True when a completed LWIP folder (identified by its input path +
  /// fingerprint) has already been reported — the restart-safe dedupe the
  /// processing agent checks each tick. A re-transfer changes the
  /// fingerprint, so it is treated as a fresh, re-reportable job.
  Future<bool> isProcessingReported({
    required String deviceId,
    required String inputPath,
    required String fingerprint,
  }) async {
    final db = await getDatabase(deviceId);
    final rows = await db.query(
      'processing_ledger',
      where: 'input_path = ? AND fingerprint = ?',
      whereArgs: [inputPath, fingerprint],
      limit: 1,
    );
    return rows.isNotEmpty;
  }

  /// Records one LWIP-processed folder: marks it in the dedupe ledger,
  /// enqueues the `capture_folder_processing` outbox row (self-gated on
  /// syncEnabled — cloud reporting needs sync on), and, when the folder row
  /// also lives in THIS machine's local DB (a co-located capture+processing
  /// station), mirrors the six pipeline columns onto it. Deliberately does
  /// NOT go through a normal folder upsert — the pipeline columns must never
  /// ride `folderUpsertSql`. [identity] is LWIP's marker payload (natural
  /// keys); [inputPath]/[fingerprint] are the LWIP state.json job key.
  Future<void> recordFolderProcessing({
    required String deviceId,
    required Map<String, dynamic> identity,
    required String folderPath,
    required String thumbnailPath,
    required bool isCreatedThumbnail,
    required String inputPath,
    required String fingerprint,
  }) async {
    final projectKey = (identity['project_key'] as String?)?.trim() ?? '';
    final boxName = (identity['box_name'] as String?)?.trim() ?? '';
    final folderSeq = (identity['folder_seq'] as num?)?.toInt();
    if (projectKey.isEmpty || boxName.isEmpty || folderSeq == null) {
      throw ArgumentError(
          'processing identity is missing project_key/box_name/folder_seq');
    }
    final db = await getDatabase(deviceId);
    final nowIso = DateTime.now().toIso8601String();
    await db.transaction((txn) async {
      await txn.insert(
        'processing_ledger',
        {'input_path': inputPath, 'fingerprint': fingerprint, 'reported_at': nowIso},
        conflictAlgorithm: ConflictAlgorithm.replace,
      );

      // entity_key = the folder's natural key. Injective (so it can't
      // wrongly coalesce two distinct folders): project_key carries no '|'
      // and folder_seq is a pipe-free integer at the end, so box_name in the
      // middle is unambiguous even if it contains '|'.
      await _enqueueOutbox(
        txn,
        entity: 'capture_folder_processing',
        entityKey: '$projectKey|$boxName|$folderSeq',
        op: 'upsert',
        payload: {
          'project_key': projectKey,
          'project_id': identity['project_id'],
          'box_name': boxName,
          'renamed_from': identity['renamed_from'],
          'device_id': identity['device_id'],
          'folder_seq': folderSeq,
          'folder_name': identity['folder_name'],
          'is_created_thumbnail': isCreatedThumbnail,
          'folder_path': folderPath,
          'thumbnail_path': thumbnailPath,
          'processed_at': nowIso,
        },
      );

      final boxId = await _localBoxIdByKeys(txn, projectKey, boxName);
      if (boxId != null) {
        await txn.update(
          'capture_folders',
          {
            'is_deskewed': 1,
            'is_cropped': 1,
            'is_created_thumbnail': isCreatedThumbnail ? 1 : 0,
            'folder_path': folderPath,
            'thumbnail_path': thumbnailPath,
            'qc_status': 'PENDING',
          },
          where: 'box_id = ? AND folder_seq = ?',
          whereArgs: [boxId, folderSeq],
        );
      }
    });
  }

  /// Ledgers a completed LWIP folder that could NOT be reported (its manifest
  /// carried no usable identity — e.g. an externally-dropped folder without a
  /// marker) so the report agent doesn't re-read and re-warn every tick. No
  /// outbox row, no local update — just the dedupe marker.
  Future<void> recordProcessingSkip({
    required String deviceId,
    required String inputPath,
    required String fingerprint,
  }) async {
    final db = await getDatabase(deviceId);
    await db.insert(
      'processing_ledger',
      {
        'input_path': inputPath,
        'fingerprint': fingerprint,
        'reported_at': 'SKIPPED-NO-IDENTITY',
      },
      conflictAlgorithm: ConflictAlgorithm.replace,
    );
  }

  /// Local box id for (project_key, box_name), with a renamed_from fallback —
  /// null on a processing-only PC that never captured the box.
  Future<int?> _localBoxIdByKeys(
    DatabaseExecutor txn,
    String projectKey,
    String boxName,
  ) async {
    for (final column in ['box_name', 'renamed_from']) {
      final rows = await txn.query(
        'capture_boxes',
        columns: ['id'],
        where: 'project_key = ? AND $column = ?',
        whereArgs: [projectKey, boxName],
        limit: 1,
      );
      if (rows.isNotEmpty) return (rows.first['id'] as num).toInt();
    }
    return null;
  }

  /// Deletes a folder only when no images are assigned to it. Returns false
  /// (and deletes nothing) otherwise.
  Future<bool> deleteCaptureFolder({
    required String deviceId,
    required int folderId,
  }) async {
    final db = await getDatabase(deviceId);
    return db.transaction((txn) async {
      final countRows = await txn.rawQuery(
        'SELECT COUNT(*) AS c FROM capture_images WHERE folder_id = ?',
        [folderId],
      );
      if ((countRows.first['c'] as num).toInt() > 0) return false;

      // Snapshot the cloud natural key BEFORE the row disappears — delete
      // ops must carry it (the sink soft-deletes by (box, folder_seq)).
      Map<String, dynamic>? deletePayload;
      if (syncEnabled) {
        final rows = await txn.query(
          'capture_folders',
          columns: ['box_id', 'folder_seq'],
          where: 'id = ?',
          whereArgs: [folderId],
          limit: 1,
        );
        if (rows.isNotEmpty) {
          deletePayload = {
            'folder_seq': rows.first['folder_seq'],
            ...await _parentBoxKeys(txn, rows.first['box_id']),
          };
        }
      }

      await txn.delete('capture_folders', where: 'id = ?', whereArgs: [folderId]);

      if (deletePayload != null) {
        await _enqueueOutbox(
          txn,
          entity: 'capture_folders',
          entityKey: '$folderId',
          op: 'delete',
          payload: deletePayload,
        );
      }
      return true;
    });
  }

  Future<List<CaptureFolder>> getCaptureFolders({
    required String deviceId,
    required int boxId,
  }) async {
    final db = await getDatabase(deviceId);
    final rows = await db.query(
      'capture_folders',
      where: 'box_id = ?',
      whereArgs: [boxId],
      orderBy: 'folder_seq ASC',
    );
    return rows.map(CaptureFolder.fromDbMap).toList();
  }

  /// The box's cloud natural keys (box_name, project_id, project_key,
  /// renamed_from, device_id) — the same shape folder/image sync payloads
  /// carry. Used by the processing-marker writer to stamp folder identity
  /// into the destination. Empty map if the box row is gone.
  Future<Map<String, dynamic>> boxNaturalKeys({
    required String deviceId,
    required int boxId,
  }) async {
    final db = await getDatabase(deviceId);
    return _parentBoxKeys(db, boxId);
  }

  // ── Image assignments (cloud capture_images mirror) ─────────────────────

  /// Cloud CHECK constraint set for capture_images.file_format.
  static const _allowedImageFormats = {'jpg', 'jpeg', 'tif', 'tiff', 'png'};

  /// Extension of [filename], lowercased without the dot, coerced into the
  /// cloud CHECK set ('jpg' fallback — phone captures are always JPEG).
  static String fileFormatOf(String filename) {
    final dot = filename.lastIndexOf('.');
    final ext = dot < 0 ? '' : filename.substring(dot + 1).toLowerCase();
    if (_allowedImageFormats.contains(ext)) return ext;
    print('⚠️ Unexpected image extension "$ext" on $filename — recording as jpg.');
    return 'jpg';
  }

  /// Assigns [deviceFilename] to a folder. Returns false without throwing when
  /// the filename is already assigned anywhere (image_name UNIQUE). This is
  /// the single write path for box membership — capture, orphan heal, and
  /// admin resolution all route through here, so the sync enqueue below
  /// covers every assignment source.
  Future<bool> assignImageToFolder({
    required String deviceId,
    required int boxId,
    required int folderId,
    required String deviceFilename,
  }) async {
    final db = await getDatabase(deviceId);
    try {
      await db.transaction((txn) async {
        final row = {
          'image_name': deviceFilename,
          'device_id': deviceId,
          'folder_id': folderId,
          'file_format': fileFormatOf(deviceFilename),
          'image_created_at': DateTime.now().toIso8601String(),
          'box_id': boxId,
        };
        await txn.insert('capture_images', row,
            conflictAlgorithm: ConflictAlgorithm.abort);
        await _enqueueCaptureImageUpsert(txn, folderId, deviceFilename, row);
      });
      return true;
    } on DatabaseException catch (e) {
      if (e.isUniqueConstraintError()) return false;
      rethrow;
    }
  }

  /// Joins the folder's seq + parent box natural keys into an image payload
  /// and enqueues it. Payload identity on the wire: (project_key, box_name,
  /// folder_seq, image_name).
  Future<void> _enqueueCaptureImageUpsert(
    DatabaseExecutor txn,
    int folderId,
    String imageName,
    Map<String, dynamic> row,
  ) async {
    if (!syncEnabled) return;
    final payload = Map<String, dynamic>.from(row);
    final folderRows = await txn.query(
      'capture_folders',
      columns: ['box_id', 'folder_seq'],
      where: 'id = ?',
      whereArgs: [folderId],
      limit: 1,
    );
    if (folderRows.isNotEmpty) {
      payload['folder_seq'] = folderRows.first['folder_seq'];
      payload.addAll(await _parentBoxKeys(txn, folderRows.first['box_id']));
    }
    await _enqueueOutbox(
      txn,
      entity: 'capture_images',
      entityKey: '$folderId|$imageName',
      op: 'upsert',
      payload: payload,
    );
  }

  /// Removes the mapping for a deleted device photo (any box). Deliberately a
  /// plain DELETE — locked decision 5: deletions remove the mapping. The
  /// cloud row is hard-deleted too (capture_images has no soft-delete
  /// columns).
  Future<void> unassignImage({
    required String deviceId,
    required String deviceFilename,
  }) async {
    final db = await getDatabase(deviceId);
    await db.transaction((txn) async {
      final rows = await txn.query(
        'capture_images',
        columns: ['folder_id'],
        where: 'image_name = ?',
        whereArgs: [deviceFilename],
        limit: 1,
      );
      if (rows.isEmpty) return;
      final folderId = (rows.first['folder_id'] as num).toInt();

      Map<String, dynamic>? deletePayload;
      if (syncEnabled) {
        deletePayload = {'image_name': deviceFilename};
        final folderRows = await txn.query(
          'capture_folders',
          columns: ['box_id', 'folder_seq'],
          where: 'id = ?',
          whereArgs: [folderId],
          limit: 1,
        );
        if (folderRows.isNotEmpty) {
          deletePayload['folder_seq'] = folderRows.first['folder_seq'];
          deletePayload
              .addAll(await _parentBoxKeys(txn, folderRows.first['box_id']));
        }
      }

      await txn.delete(
        'capture_images',
        where: 'image_name = ?',
        whereArgs: [deviceFilename],
      );
      if (deletePayload != null) {
        await _enqueueOutbox(
          txn,
          entity: 'capture_images',
          entityKey: '$folderId|$deviceFilename',
          op: 'delete',
          payload: deletePayload,
        );
      }
    });
  }

  /// filename → folder_id for every assignment in [boxId].
  Future<Map<String, int>> getAssignmentsForBox({
    required String deviceId,
    required int boxId,
  }) async {
    final db = await getDatabase(deviceId);
    final rows = await db.query(
      'capture_images',
      columns: ['image_name', 'folder_id'],
      where: 'box_id = ?',
      whereArgs: [boxId],
    );
    return {
      for (final r in rows) (r['image_name'] as String): (r['folder_id'] as num).toInt(),
    };
  }

  /// folder_id → assigned-image count for [boxId].
  Future<Map<int, int>> countImagesPerFolder({
    required String deviceId,
    required int boxId,
  }) async {
    final db = await getDatabase(deviceId);
    final rows = await db.rawQuery(
      'SELECT folder_id, COUNT(*) AS c FROM capture_images WHERE box_id = ? GROUP BY folder_id',
      [boxId],
    );
    return {
      for (final r in rows) (r['folder_id'] as num).toInt(): (r['c'] as num).toInt(),
    };
  }

  // =======================================================
  // ALREADY-UPLOADED BASE NAMES (for skip logic)
  // =======================================================

  /// Returns a set of base names that have been uploaded for this device.
  ///
  /// Our saved filenames look like:
  ///   SAX01_IMG_20251101_121635_001.jpg
  ///   SAX01_IMG_20251101_121635_002.jpg
  ///
  /// The "base name" here is:
  ///   SAX01_IMG_20251101_121635
  ///
  /// This lets us treat all copies with the same timestamp
  /// (e.g. double-click captures) as "already uploaded".
  Future<Set<String>> getUploadedBaseNames(String deviceId) async {
    final result = <String>{};
    final reg = RegExp(r'^(.+)_\d{3}\.[^\.]+$');

    for (final db in await _allDeviceUploadDatabases(deviceId)) {
      final rows = await db.query(
        'upload_records',
        columns: ['filename'],
        where: 'device_id = ?',
        whereArgs: [deviceId],
      );
      for (final row in rows) {
        final filename = row['filename'] as String?;
        if (filename == null) continue;
        final match = reg.firstMatch(filename);
        if (match != null) {
          result.add(match.group(1)!);
        }
      }
    }

    return result;
  }

  /// Every FULL recorded destination filename for [deviceId] (suffix and
  /// extension included), across the stable DB and all monthly files. A
  /// record exists only for a copy that completed and passed its size check —
  /// so a destination file whose name is NOT in this set is an orphan from an
  /// interrupted run (power loss/crash mid-copy) and safe to overwrite; see
  /// the name allocator in upload_contoller.dart.
  Future<Set<String>> getUploadedFilenames(String deviceId) async {
    final result = <String>{};
    for (final db in await _allDeviceUploadDatabases(deviceId)) {
      final rows = await db.query(
        'upload_records',
        columns: ['filename'],
        where: 'device_id = ?',
        whereArgs: [deviceId],
      );
      for (final row in rows) {
        final filename = row['filename'] as String?;
        if (filename != null) result.add(filename);
      }
    }
    return result;
  }
}
