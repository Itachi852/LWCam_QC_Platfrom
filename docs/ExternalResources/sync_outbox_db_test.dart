import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:lwcam/db/upload_stats_db.dart';
import 'package:lwcam/models/capture_box_models.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

Future<Directory> _tempDir(String prefix) async {
  final dir = await Directory.systemTemp.createTemp(prefix);
  addTearDown(() async {
    if (await dir.exists()) await dir.delete(recursive: true);
  });
  return dir;
}

CaptureFolder _folder(int boxId, {String? volume = 'V file no. 1'}) {
  return CaptureFolder(
    boxId: boxId,
    coverTag: 'Cover Will Be Captured',
    title: 'WWI Medical Files',
    volume: volume,
    startDate: '1914',
    endDate: '1918',
  );
}

/// Spans every outbox source (stable DB + monthly files) — upload_records
/// entries land in the monthly DB for their createdAt month, everything else
/// stays in the stable DB (see MONTHLY ROTATION in upload_stats_db.dart).
Future<List<Map<String, dynamic>>> _outboxRows(
  UploadStatsDB db,
  String deviceId, {
  String? entity,
}) async {
  final result = <Map<String, dynamic>>[];
  for (final source in await db.getOutboxDatabases(deviceId)) {
    final rows = await source.query(
      'sync_outbox',
      where: entity == null ? null : 'entity = ?',
      whereArgs: entity == null ? null : [entity],
    );
    result.addAll(rows.map((r) => {
          ...r,
          'decoded_payload':
              r['payload'] == null ? null : jsonDecode(r['payload'] as String),
        }));
  }
  return result;
}

void main() {
  setUpAll(() {
    sqfliteFfiInit();
    databaseFactory = databaseFactoryFfi;
  });

  group('schema', () {
    test('fresh device DB has sync_outbox with a unique (entity, entity_key) index',
        () async {
      final base = await _tempDir('sync_fresh_');
      final db = UploadStatsDB();
      db.debugOverrideBaseFolderForTests(base.path);
      addTearDown(() => db.debugCloseAllForTests());

      final fresh = await db.getDatabase('devFresh9');
      expect(await fresh.getVersion(), 1);

      final tables = (await fresh
              .rawQuery("SELECT name FROM sqlite_master WHERE type='table'"))
          .map((r) => r['name'] as String)
          .toSet();
      expect(tables, contains('sync_outbox'));

      final indexes = (await fresh
              .rawQuery("SELECT sql FROM sqlite_master WHERE type='index' AND name='idx_outbox_entity_key'"))
          .single['sql'] as String;
      expect(indexes, contains('UNIQUE'));

      // Natural keys replaced the old box_uid/folder_uid columns — the sink
      // resolves cloud ids from (project_id, box_name)/(box, folder_seq).
      final columns = (await fresh.rawQuery('PRAGMA table_info(capture_boxes)'))
          .map((r) => r['name'] as String)
          .toSet();
      expect(columns, isNot(contains('box_uid')));
      expect(columns, containsAll(['box_name', 'project_id', 'renamed_from']));
      final folderColumns =
          (await fresh.rawQuery('PRAGMA table_info(capture_folders)'))
              .map((r) => r['name'] as String)
              .toSet();
      expect(folderColumns, isNot(contains('folder_uid')));
    });
  });

  group('outbox hooks', () {
    Future<UploadStatsDB> freshDb(String prefix, {required bool syncEnabled}) async {
      final base = await _tempDir(prefix);
      final db = UploadStatsDB();
      db.debugOverrideBaseFolderForTests(base.path);
      db.syncEnabled = syncEnabled;
      addTearDown(() {
        db.syncEnabled = false; // don't leak into later tests via the singleton
        return db.debugCloseAllForTests();
      });
      return db;
    }

    test('syncEnabled=false: every hooked write path enqueues nothing', () async {
      final db = await freshDb('hooks_off_', syncEnabled: false);
      const deviceId = 'devHooksOff';

      await db.insertUploadRecord(
        deviceId: deviceId,
        scanningOpr: 'alice',
        boxDetails: 'BOX-1',
        filename: 'IMG_1.jpg',
        format: 'jpg',
        createdAt: DateTime(2026, 1, 1),
      );
      final boxId = await db.insertCaptureBox(deviceId: deviceId, boxDetails: 'BOX-1');
      await db.updateCaptureBoxDetails(
          deviceId: deviceId, boxId: boxId, boxDetails: 'BOX-1-renamed');
      await db.markCaptureBoxTransferred(deviceId: deviceId, boxId: boxId);
      final folderId = await db.insertCaptureFolder(
        deviceId: deviceId,
        folder: _folder(boxId),
        isComplete: false,
      );
      await db.updateCaptureFolderMetadata(
        deviceId: deviceId,
        folder: _folder(boxId).copyWith(id: folderId, title: 'Updated'),
        isComplete: true,
      );
      await db.updateCaptureFolderName(
          deviceId: deviceId, folderId: folderId, folderName: 'F001');
      await db.deleteCaptureFolder(deviceId: deviceId, folderId: folderId);
      await db.insertReplacementRecord(
        deviceId: deviceId,
        sequenceIndex: 1,
        dateKey: '20260101',
        originalFilename: 'IMG_2.jpg',
        replacementFilename: 'IMG_2_r1.jpg',
        replacementLocalPath: 'C:/tmp/IMG_2_r1.jpg',
      );
      await db.markReplacementRecordSuperseded(
        deviceId: deviceId,
        originalFilename: 'IMG_2.jpg',
        replacementFilename: 'IMG_2_r1.jpg',
      );
      await db.markReplacementRecordsSuperseded(
          deviceId: deviceId, originalFilename: 'IMG_2.jpg');

      expect(await _outboxRows(db, deviceId), isEmpty);
    });

    test('insertUploadRecord enqueues NOTHING — upload_records left the sync '
        'pipeline (capture_images replaced it)', () async {
      final db = await freshDb('hooks_upload_', syncEnabled: true);
      const deviceId = 'devUpload';

      await db.insertUploadRecord(
        deviceId: deviceId,
        scanningOpr: 'alice',
        boxDetails: 'BOX-1',
        filename: 'IMG_1.jpg',
        format: 'jpg',
        createdAt: DateTime(2026, 1, 1),
      );

      expect(await _outboxRows(db, deviceId), isEmpty);
    });

    test('insertCaptureBox enqueues an upsert keyed by the local row id, '
        'payload in cloud shape (box_name, CAPS status, project_id)', () async {
      final db = await freshDb('hooks_box_insert_', syncEnabled: true);
      const deviceId = 'devBox';

      final boxId = await db.insertCaptureBox(
          deviceId: deviceId,
          boxDetails: 'BOX-1',
          scanningOpr: 'alice',
          projectId: 'PRJ-1');

      final rows = await _outboxRows(db, deviceId, entity: 'capture_boxes');
      expect(rows, hasLength(1));
      expect(rows.single['entity_key'], '$boxId');
      expect(rows.single['op'], 'upsert');
      final payload = rows.single['decoded_payload'] as Map;
      expect(payload['box_name'], 'BOX-1');
      expect(payload['status'], 'OPEN');
      expect(payload['user_id'], 'alice');
      expect(payload['project_id'], 'PRJ-1');
    });

    test('updateCaptureBoxDetails and markCaptureBoxTransferred coalesce into a '
        'single pending outbox row carrying the latest snapshot + renamed_from',
        () async {
      final db = await freshDb('hooks_box_coalesce_', syncEnabled: true);
      const deviceId = 'devBoxCoalesce';

      final boxId =
          await db.insertCaptureBox(deviceId: deviceId, boxDetails: 'BOX-1');
      await db.updateCaptureBoxDetails(
          deviceId: deviceId, boxId: boxId, boxDetails: 'BOX-1-renamed');
      await db.markCaptureBoxTransferred(
          deviceId: deviceId, boxId: boxId, transferredTo: r'D:\dest');

      final rows = await _outboxRows(db, deviceId, entity: 'capture_boxes');
      expect(rows, hasLength(1)); // insert + 2 updates -> 1 coalesced row
      final payload = rows.single['decoded_payload'] as Map;
      expect(payload['box_name'], 'BOX-1-renamed');
      // The sink's rename fixup needs the name PG last saw.
      expect(payload['renamed_from'], 'BOX-1');
      expect(payload['status'], 'TRANSFERRED');
      expect(payload['transferred_to'], r'D:\dest');
      expect(payload['transfer_end_at'], isNotNull);
    });

    test('a second rename keeps the ORIGINAL renamed_from (only-if-null rule)',
        () async {
      final db = await freshDb('hooks_box_rename2_', syncEnabled: true);
      const deviceId = 'devBoxRename2';

      final boxId =
          await db.insertCaptureBox(deviceId: deviceId, boxDetails: 'A');
      await db.updateCaptureBoxDetails(
          deviceId: deviceId, boxId: boxId, boxDetails: 'B');
      await db.updateCaptureBoxDetails(
          deviceId: deviceId, boxId: boxId, boxDetails: 'C');

      final rows = await _outboxRows(db, deviceId, entity: 'capture_boxes');
      final payload = rows.single['decoded_payload'] as Map;
      expect(payload['box_name'], 'C');
      expect(payload['renamed_from'], 'A');
    });

    test('markCaptureBoxTransferStarted stamps transfer_start_at and enqueues',
        () async {
      final db = await freshDb('hooks_box_start_', syncEnabled: true);
      const deviceId = 'devBoxStart';

      final boxId =
          await db.insertCaptureBox(deviceId: deviceId, boxDetails: 'BOX-1');
      await db.markCaptureBoxTransferStarted(deviceId: deviceId, boxId: boxId);

      final rows = await _outboxRows(db, deviceId, entity: 'capture_boxes');
      final payload = rows.single['decoded_payload'] as Map;
      expect(payload['transfer_start_at'], isNotNull);
      expect(payload['status'], 'OPEN');
    });

    test("insertCaptureFolder's payload carries the parent box's natural keys "
        'and the operator stamps', () async {
      final db = await freshDb('hooks_folder_insert_', syncEnabled: true);
      const deviceId = 'devFolder';

      final boxId = await db.insertCaptureBox(
          deviceId: deviceId, boxDetails: 'BOX-1', projectId: 'PRJ-1');
      final folderId = await db.insertCaptureFolder(
        deviceId: deviceId,
        folder: _folder(boxId),
        isComplete: false,
        captureOperatorName: 'alice',
      );

      final rows = await _outboxRows(db, deviceId, entity: 'capture_folders');
      final folderRow = rows.singleWhere((r) => r['entity_key'] == '$folderId');
      final payload = folderRow['decoded_payload'] as Map;
      expect(payload['box_name'], 'BOX-1');
      expect(payload['project_id'], 'PRJ-1');
      expect(payload['device_id'], deviceId);
      expect(payload['title'], 'WWI Medical Files');
      expect(payload['capture_operator_id'], deviceId);
      expect(payload['capture_operator_name'], 'alice');
      expect(payload['source_created_at'], isNotNull);
    });

    test('updateCaptureFolderMetadata and updateCaptureFolderName coalesce into a '
        "single pending row that still carries the parent's natural keys", () async {
      final db = await freshDb('hooks_folder_coalesce_', syncEnabled: true);
      const deviceId = 'devFolderCoalesce';

      final boxId =
          await db.insertCaptureBox(deviceId: deviceId, boxDetails: 'BOX-1');
      final folderId = await db.insertCaptureFolder(
        deviceId: deviceId,
        folder: _folder(boxId),
        isComplete: false,
      );
      await db.updateCaptureFolderMetadata(
        deviceId: deviceId,
        folder: _folder(boxId).copyWith(id: folderId, title: 'Updated Title'),
        isComplete: true,
      );
      await db.updateCaptureFolderName(
          deviceId: deviceId, folderId: folderId, folderName: 'F001');

      final rows = await _outboxRows(db, deviceId, entity: 'capture_folders');
      expect(rows, hasLength(1));
      final payload = rows.single['decoded_payload'] as Map;
      expect(payload['title'], 'Updated Title');
      expect(payload['folder_name'], 'F001');
      // Regression guard: a coalesced update must not drop the FK keys the
      // initial insert carried — the payload is re-joined fresh every time,
      // not sourced from whichever write happened to run last.
      expect(payload['box_name'], 'BOX-1');
    });

    test('deleteCaptureFolder after insert coalesces to a single delete op '
        'carrying the cloud natural key', () async {
      final db = await freshDb('hooks_folder_delete_', syncEnabled: true);
      const deviceId = 'devFolderDelete';

      final boxId = await db.insertCaptureBox(
          deviceId: deviceId, boxDetails: 'BOX-1', projectId: 'PRJ-1');
      final folderId = await db.insertCaptureFolder(
        deviceId: deviceId,
        folder: _folder(boxId),
        isComplete: false,
      );

      final deleted =
          await db.deleteCaptureFolder(deviceId: deviceId, folderId: folderId);
      expect(deleted, isTrue);

      final rows = await _outboxRows(db, deviceId, entity: 'capture_folders');
      expect(rows, hasLength(1));
      expect(rows.single['entity_key'], '$folderId');
      expect(rows.single['op'], 'delete');
      // Delete ops carry the key payload — the sink soft-deletes by
      // (box, folder_seq), which no longer exists locally after the delete.
      final payload = rows.single['decoded_payload'] as Map;
      expect(payload['folder_seq'], 1);
      expect(payload['box_name'], 'BOX-1');
      expect(payload['project_id'], 'PRJ-1');
    });

    test('assignImageToFolder enqueues a capture_images upsert with parent '
        'keys + file_format; unassignImage coalesces it into a delete', () async {
      final db = await freshDb('hooks_image_', syncEnabled: true);
      const deviceId = 'devImage';

      final boxId = await db.insertCaptureBox(
          deviceId: deviceId, boxDetails: 'BOX-1', projectId: 'PRJ-1');
      final folderId = await db.insertCaptureFolder(
        deviceId: deviceId,
        folder: _folder(boxId),
        isComplete: false,
      );
      final ok = await db.assignImageToFolder(
        deviceId: deviceId,
        boxId: boxId,
        folderId: folderId,
        deviceFilename: 'IMG_1.JPG',
      );
      expect(ok, isTrue);

      var rows = await _outboxRows(db, deviceId, entity: 'capture_images');
      expect(rows, hasLength(1));
      expect(rows.single['entity_key'], '$folderId|IMG_1.JPG');
      expect(rows.single['op'], 'upsert');
      var payload = rows.single['decoded_payload'] as Map;
      expect(payload['image_name'], 'IMG_1.JPG');
      expect(payload['file_format'], 'jpg'); // extension lowercased
      expect(payload['folder_seq'], 1);
      expect(payload['box_name'], 'BOX-1');
      expect(payload['project_id'], 'PRJ-1');

      await db.unassignImage(deviceId: deviceId, deviceFilename: 'IMG_1.JPG');
      rows = await _outboxRows(db, deviceId, entity: 'capture_images');
      expect(rows, hasLength(1)); // coalesced — same (entity, key)
      expect(rows.single['op'], 'delete');
      payload = rows.single['decoded_payload'] as Map;
      expect(payload['image_name'], 'IMG_1.JPG');
      expect(payload['folder_seq'], 1);
    });

    test('a duplicate assignImageToFolder returns false and enqueues nothing new',
        () async {
      final db = await freshDb('hooks_image_dup_', syncEnabled: true);
      const deviceId = 'devImageDup';

      final boxId =
          await db.insertCaptureBox(deviceId: deviceId, boxDetails: 'BOX-1');
      final folderId = await db.insertCaptureFolder(
        deviceId: deviceId,
        folder: _folder(boxId),
        isComplete: false,
      );
      expect(
          await db.assignImageToFolder(
              deviceId: deviceId,
              boxId: boxId,
              folderId: folderId,
              deviceFilename: 'IMG_1.jpg'),
          isTrue);
      expect(
          await db.assignImageToFolder(
              deviceId: deviceId,
              boxId: boxId,
              folderId: folderId,
              deviceFilename: 'IMG_1.jpg'),
          isFalse);

      final rows = await _outboxRows(db, deviceId, entity: 'capture_images');
      expect(rows, hasLength(1));
    });

    test('deleteCaptureFolder refuses (and enqueues nothing) when images are '
        'assigned', () async {
      final db = await freshDb('hooks_folder_delete_refuse_', syncEnabled: true);
      const deviceId = 'devFolderDeleteRefuse';

      final boxId =
          await db.insertCaptureBox(deviceId: deviceId, boxDetails: 'BOX-1');
      final folderId = await db.insertCaptureFolder(
        deviceId: deviceId,
        folder: _folder(boxId),
        isComplete: false,
      );
      await db.assignImageToFolder(
        deviceId: deviceId,
        boxId: boxId,
        folderId: folderId,
        deviceFilename: 'IMG_1.jpg',
      );

      final deleted =
          await db.deleteCaptureFolder(deviceId: deviceId, folderId: folderId);
      expect(deleted, isFalse);

      final rows = await _outboxRows(db, deviceId, entity: 'capture_folders');
      // Only the insert's upsert — no delete was enqueued for the refusal.
      expect(rows, hasLength(1));
      expect(rows.single['op'], 'upsert');
    });

    test('insertReplacementRecord enqueues nothing — replacements are '
        'local-only, never synced', () async {
      final db = await freshDb('hooks_replacement_insert_', syncEnabled: true);
      const deviceId = 'devReplacement';

      await db.insertReplacementRecord(
        deviceId: deviceId,
        sequenceIndex: 1,
        dateKey: '20260101',
        originalFilename: 'IMG_1.jpg',
        replacementFilename: 'IMG_1_r1.jpg',
        replacementLocalPath: 'C:/tmp/IMG_1_r1.jpg',
      );

      final row = (await (await db.getDatabase(deviceId))
              .query('replacement_records'))
          .single;
      expect(row['original_filename'], 'IMG_1.jpg');
      expect(
        await _outboxRows(db, deviceId, entity: 'replacement_records'),
        isEmpty,
      );
    });

    test('markReplacementRecordSuperseded and markReplacementRecordsSuperseded '
        '(bulk) enqueue nothing even with syncEnabled=true', () async {
      final db = await freshDb('hooks_replacement_supersede_', syncEnabled: true);
      const deviceId = 'devReplacementSupersede';

      await db.insertReplacementRecord(
        deviceId: deviceId,
        sequenceIndex: 1,
        dateKey: '20260101',
        originalFilename: 'IMG_1.jpg',
        replacementFilename: 'IMG_1_r1.jpg',
        replacementLocalPath: 'C:/tmp/IMG_1_r1.jpg',
      );
      await db.insertReplacementRecord(
        deviceId: deviceId,
        sequenceIndex: 1,
        dateKey: '20260101',
        originalFilename: 'IMG_1.jpg',
        replacementFilename: 'IMG_1_r2.jpg',
        replacementLocalPath: 'C:/tmp/IMG_1_r2.jpg',
      );

      await db.markReplacementRecordSuperseded(
        deviceId: deviceId,
        originalFilename: 'IMG_1.jpg',
        replacementFilename: 'IMG_1_r1.jpg',
      );
      final supersededCount = await db.markReplacementRecordsSuperseded(
          deviceId: deviceId, originalFilename: 'IMG_1.jpg');
      // r1 was already superseded above; the bulk call only catches r2.
      expect(supersededCount, 1);

      expect(
        await _outboxRows(db, deviceId, entity: 'replacement_records'),
        isEmpty,
      );
    });
  });

  group('processing reports (LWIP)', () {
    Future<UploadStatsDB> freshDb(String prefix, {required bool syncEnabled}) async {
      final base = await _tempDir(prefix);
      final db = UploadStatsDB();
      db.debugOverrideBaseFolderForTests(base.path);
      db.syncEnabled = syncEnabled;
      addTearDown(() {
        db.syncEnabled = false;
        return db.debugCloseAllForTests();
      });
      return db;
    }

    Future<Map<String, dynamic>> folderRow(UploadStatsDB db, String deviceId, int id) async =>
        (await (await db.getDatabase(deviceId))
                .query('capture_folders', where: 'id = ?', whereArgs: [id]))
            .single;

    test('records the processing entity, ledgers it, resets qc_status, and '
        'mirrors the six pipeline columns onto the local folder row', () async {
      final db = await freshDb('proc_same_', syncEnabled: true);
      const deviceId = 'devProc';
      final boxId = await db.insertCaptureBox(
          deviceId: deviceId, boxDetails: 'BOX-1', projectId: 'PRJ-1', projectKey: 'pabc');
      final folderId = await db.insertCaptureFolder(
          deviceId: deviceId, folder: _folder(boxId), isComplete: true);
      // Simulate an earlier QC verdict that reprocessing must reset.
      await (await db.getDatabase(deviceId)).update(
          'capture_folders', {'qc_status': 'PASS'},
          where: 'id = ?', whereArgs: [folderId]);

      await db.recordFolderProcessing(
        deviceId: deviceId,
        identity: {
          'project_key': 'pabc',
          'project_id': 'PRJ-1',
          'box_name': 'BOX-1',
          'device_id': deviceId,
          'folder_seq': 1,
          'folder_name': 'F001',
        },
        folderPath: r'D:\CAP_processed\20260722\F001',
        thumbnailPath: r'D:\CAP_processed\20260722\F001\thumbs',
        isCreatedThumbnail: true,
        inputPath: r'D:\CAP\20260722\F001',
        fingerprint: 'fp1',
      );

      final rows =
          await _outboxRows(db, deviceId, entity: 'capture_folder_processing');
      expect(rows, hasLength(1));
      expect(rows.single['entity_key'], 'pabc|BOX-1|1');
      expect(rows.single['op'], 'upsert');
      final payload = rows.single['decoded_payload'] as Map;
      expect(payload['project_key'], 'pabc');
      expect(payload['box_name'], 'BOX-1');
      expect(payload['folder_seq'], 1);
      expect(payload['folder_path'], r'D:\CAP_processed\20260722\F001');
      expect(payload['is_created_thumbnail'], true);

      expect(
          await db.isProcessingReported(
              deviceId: deviceId,
              inputPath: r'D:\CAP\20260722\F001',
              fingerprint: 'fp1'),
          isTrue);

      final row = await folderRow(db, deviceId, folderId);
      expect(row['is_deskewed'], 1);
      expect(row['is_cropped'], 1);
      expect(row['is_created_thumbnail'], 1);
      expect(row['folder_path'], r'D:\CAP_processed\20260722\F001');
      expect(row['thumbnail_path'], endsWith('thumbs'));
      expect(row['qc_status'], 'PENDING'); // reset from PASS
    });

    test('on a folder absent locally (split-PC) it still enqueues + ledgers, '
        'with no local mirror update and no throw', () async {
      final db = await freshDb('proc_split_', syncEnabled: true);
      const deviceId = 'PROCESSING';
      await db.recordFolderProcessing(
        deviceId: deviceId,
        identity: {
          'project_key': 'pxyz',
          'project_id': 'PRJ-9',
          'box_name': 'BOX-9',
          'device_id': 'SAX07',
          'folder_seq': 2,
          'folder_name': 'F002',
        },
        folderPath: r'\\nas\proc\20260722\F002',
        thumbnailPath: r'\\nas\proc\20260722\F002\thumbs',
        isCreatedThumbnail: false,
        inputPath: r'\\nas\cap\20260722\F002',
        fingerprint: 'fp2',
      );

      final rows =
          await _outboxRows(db, deviceId, entity: 'capture_folder_processing');
      expect(rows, hasLength(1));
      expect((rows.single['decoded_payload'] as Map)['is_created_thumbnail'], false);
      // No capture_folders exist on this processing-only device DB.
      expect(await (await db.getDatabase(deviceId)).query('capture_folders'), isEmpty);
    });

    test('a re-transfer (new fingerprint) re-reports, coalescing the outbox row '
        'to the latest; the ledger keeps both fingerprints', () async {
      final db = await freshDb('proc_reproc_', syncEnabled: true);
      const deviceId = 'devReproc';
      final identity = {
        'project_key': 'pabc',
        'project_id': 'PRJ-1',
        'box_name': 'BOX-1',
        'device_id': deviceId,
        'folder_seq': 1,
        'folder_name': 'F001',
      };
      await db.recordFolderProcessing(
          deviceId: deviceId, identity: identity, folderPath: 'p1',
          thumbnailPath: 't1', isCreatedThumbnail: true, inputPath: 'in',
          fingerprint: 'fp1');
      await db.recordFolderProcessing(
          deviceId: deviceId, identity: identity, folderPath: 'p2',
          thumbnailPath: 't2', isCreatedThumbnail: true, inputPath: 'in',
          fingerprint: 'fp2');

      final rows =
          await _outboxRows(db, deviceId, entity: 'capture_folder_processing');
      expect(rows, hasLength(1)); // same entity_key → coalesced
      expect((rows.single['decoded_payload'] as Map)['folder_path'], 'p2');

      expect(await db.isProcessingReported(
          deviceId: deviceId, inputPath: 'in', fingerprint: 'fp1'), isTrue);
      expect(await db.isProcessingReported(
          deviceId: deviceId, inputPath: 'in', fingerprint: 'fp2'), isTrue);
      expect(await db.isProcessingReported(
          deviceId: deviceId, inputPath: 'in', fingerprint: 'fp3'), isFalse);
    });

    test('with sync OFF it still ledgers + mirrors locally but enqueues no '
        'outbox row (offline site gets local updates only)', () async {
      final db = await freshDb('proc_off_', syncEnabled: false);
      const deviceId = 'devProcOff';
      final boxId = await db.insertCaptureBox(
          deviceId: deviceId, boxDetails: 'BOX-1', projectId: 'PRJ-1', projectKey: 'pabc');
      final folderId = await db.insertCaptureFolder(
          deviceId: deviceId, folder: _folder(boxId), isComplete: true);

      await db.recordFolderProcessing(
        deviceId: deviceId,
        identity: {'project_key': 'pabc', 'box_name': 'BOX-1', 'folder_seq': 1},
        folderPath: 'p', thumbnailPath: 't', isCreatedThumbnail: true,
        inputPath: 'in', fingerprint: 'fp1',
      );

      expect(await _outboxRows(db, deviceId, entity: 'capture_folder_processing'),
          isEmpty);
      expect(await db.isProcessingReported(
          deviceId: deviceId, inputPath: 'in', fingerprint: 'fp1'), isTrue);
      expect((await folderRow(db, deviceId, folderId))['is_deskewed'], 1);
    });
  });
}
