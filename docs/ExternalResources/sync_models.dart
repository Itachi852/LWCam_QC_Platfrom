/// Shared types for the sync outbox drain pipeline (SyncService + SyncSink
/// implementations). Pure Dart — no sqflite/postgres imports here, so this
/// file can be imported by every sink and by tests without pulling in a
/// database driver.
library;

/// `SyncService`'s current activity, surfaced to Settings as a status chip.
enum SyncState {
  /// syncEnabled is false (NodeConfig) — the default; no timer runs.
  disabled,

  /// Timer running, outbox empty, nothing to do.
  idle,

  /// A drain tick is in flight.
  syncing,

  /// The last connection attempt failed to reach the sink at all (as
  /// opposed to a write failing after connecting).
  offline,

  /// A non-connectivity failure (e.g. a write rejected by the schema) that
  /// may need attention; the batch retries on its backoff schedule.
  error,
}

/// One durable outbox row, decoded from `sync_outbox` for draining. Mirrors
/// the table's columns (see upload_stats_db.dart _ensureSyncSchema) plus the
/// already-JSON-decoded payload.
class OutboxRecord {
  final int id;
  final String entity;
  final String entityKey;
  final String op; // 'upsert' | 'delete'
  final Map<String, dynamic>? payload;
  final int attempts;

  const OutboxRecord({
    required this.id,
    required this.entity,
    required this.entityKey,
    required this.op,
    required this.payload,
    required this.attempts,
  });
}

/// Drain order: parents before children, so a folder never arrives at the
/// sink before the box it references and an image never before its folder
/// (the sink resolves real PG FKs from the payloads' natural keys).
/// upload_records / daily_summary / replacement_records are deliberately
/// absent — local-operational data, never synced.
const List<String> kSyncEntityOrder = [
  'capture_boxes',
  'capture_folders',
  'capture_images',
  // The image-processing phase's per-folder result (deskew/crop/thumbnail
  // flags + paths + qc_status). Sorts AFTER capture_folders so a same-tick
  // folder upsert always applies before the processing UPDATE that targets
  // it. It is an UPDATE of an existing folder row, never a parent of anything.
  'capture_folder_processing',
];

int compareEntityOrder(String a, String b) {
  final ia = kSyncEntityOrder.indexOf(a);
  final ib = kSyncEntityOrder.indexOf(b);
  // Unknown entities (shouldn't happen) sort after every known one rather
  // than crashing on indexOf's -1.
  return (ia == -1 ? kSyncEntityOrder.length : ia)
      .compareTo(ib == -1 ? kSyncEntityOrder.length : ib);
}
