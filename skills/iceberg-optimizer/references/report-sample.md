# Iceberg Optimization Report: prod.events.stream

Generated: 2026-07-01

Engine: Spark
Catalog: glue_catalog
Access mode: Exported
Inputs: `profile.json`, `workload.json`, `simulate_output.txt`
Simulator priority: query_cost

## Executive Summary

- Recommended scenario: Targeted writer fix plus sort compaction on cold partitions.
- Main bottleneck: streaming commits are producing many tiny files across too many partitions, then dashboard queries scan those files by `tenant_id` and `event_time`.
- Expected impact: reduce file-open overhead immediately after compaction and prevent the small-file pattern from recurring on future writes.
- Highest-risk assumption: `checkpoint_interval_secs=30` was inferred from snapshot cadence; confirm the Flink/Spark Streaming job before changing writer settings.
- Safety: the commands below are a plan for the owner to run; do not run rewrite or delete procedures without explicit approval.

## Summary: Why Each Action, In One Sentence

| Action | Why? (data-driven) |
|---|---|
| J - Set write distribution to hash | `write_cadence.class=streaming`, `avg_added_file_mb=1.0`, and `thin_spread=true` show the writer is creating small files faster than maintenance can clean them up. |
| K - Set write-time sort order | `filter_columns[0]=tenant_id (share=0.90)` and `filter_columns[1]=event_time (share=0.75)` mean future files should be clustered on the same columns dashboards filter. |
| A - Bin-pack cold partitions | `files_under_64mb_pct=1.00` and `median_mb=1.0 vs target_mb=256` make file-open and planning overhead the immediate table-layout problem. |
| B - Sort compact cold partitions | `median_bytes_scanned=4.8 GB` and range/equality filters on `tenant_id,event_time` show sorted files can improve row-group and file skipping. |
| F - Expire snapshots after compaction | `snapshot_count=1100` with `time_travel_need=latest only` means old snapshots are metadata/storage overhead once the compacted snapshot is validated. |
| Skip orphan removal for now | No orphan evidence was exported, so run `remove_orphan_files` only as a dry-run follow-up after snapshot expiry quantifies candidates. |
| Skip manifest rewrite for now | Manifest count was not above the operational threshold, so rewriting manifests is lower ROI than fixing writer output and small files. |

## Decision Inputs

Profile highlights:

| Metric | Value |
|---|---|
| data_files | 5,000 |
| median_mb | 1.0 |
| files_under_64mb_pct | 1.00 |
| snapshot_count | 1,100 |
| write_cadence.class | streaming |
| partition_fanout.thin_spread | true |
| delete_file_pct | 0.0 |

Workload highlights:

| Metric | Value |
|---|---|
| primary equality column | tenant_id |
| primary range column | event_time |
| partition_prune_rate | 0.40 |
| median_bytes_scanned | 4.8 GB |
| query frequency | 50,000/month |
| latency requirement | interactive dashboards |
| freshness SLA | 5 minutes acceptable |

Simulator:

| Scenario | Query cost/month | Maintenance cost/month | Total cost/month |
|---|---:|---:|---:|
| do_nothing | 1,171.88 | 0.00 | 1,172.03 |
| light | 1,054.69 | 0.10 | 1,054.92 |
| targeted_sort | 292.97 | 0.10 | 293.20 |
| aggressive | 175.78 | 0.73 | 176.69 |

The simulator favors `aggressive` on query cost, but the recommendation starts
with writer correction and targeted cold-partition compaction because those
address the root cause with less concurrency risk.

## Recommendation

1. Confirm the streaming writer and checkpoint interval.
2. Set write distribution to hash and persist a write-time sort order on
   `tenant_id, event_time`.
3. Run bin-pack plus sort compaction only on cold partitions.
4. Validate file counts, scan bytes, and dashboard latency.
5. Expire snapshots after the compacted table is validated.
6. Run orphan cleanup only as a dry-run follow-up.

## Execution Commands

Read-only checks:

```sql
SELECT COUNT(*) AS data_files,
       AVG(file_size_in_bytes) / 1048576 AS avg_mb,
       SUM(CASE WHEN file_size_in_bytes < 64 * 1048576 THEN 1 ELSE 0 END) AS files_under_64mb
FROM prod.events.stream.files
WHERE content = 0;

SELECT COUNT(*) AS snapshots
FROM prod.events.stream.snapshots;
```

Owner-approved writer change:

```sql
ALTER TABLE glue_catalog.prod.events.stream SET TBLPROPERTIES (
  'write.distribution-mode' = 'hash',
  'write.target-file-size-bytes' = '268435456'
);

ALTER TABLE glue_catalog.prod.events.stream
WRITE ORDERED BY tenant_id ASC NULLS LAST, event_time ASC NULLS LAST;
```

Owner-approved rewrite. This rewrites data files; get explicit approval first.

```sql
CALL glue_catalog.system.rewrite_data_files(
  table => 'prod.events.stream',
  strategy => 'sort',
  sort_order => 'tenant_id ASC NULLS LAST, event_time ASC NULLS LAST',
  options => map(
    'target-file-size-bytes', '268435456',
    'partial-progress.enabled', 'true'
  ),
  where => 'event_date < current_date()'
);
```

Owner-approved snapshot deletion. This deletes snapshot references and can make
old data files eligible for cleanup; run only after validation.

```sql
CALL glue_catalog.system.expire_snapshots(
  table => 'prod.events.stream',
  older_than => TIMESTAMP '2026-06-24 00:00:00',
  retain_last => 10
);
```

Dry-run orphan cleanup only:

```sql
CALL glue_catalog.system.remove_orphan_files(
  table => 'prod.events.stream',
  older_than => TIMESTAMP '2026-06-24 00:00:00',
  dry_run => true
);
```

## Schedule and Triggers

| Task | Cadence | Trigger |
|---|---|---|
| Writer config audit | Once after next deploy | `avg_added_file_mb < 64` after the change |
| Cold-partition bin-pack/sort | Daily | `files_under_64mb_pct > 0.30` on closed partitions |
| Snapshot expiry | Daily after compaction validation | `snapshot_count > 2 * retain_last` |
| Orphan cleanup dry-run | Weekly | dry-run candidate bytes growing week over week |

## Monitoring

```sql
SELECT
  COUNT(*) AS data_files,
  percentile_approx(file_size_in_bytes / 1048576, 0.5) AS median_mb,
  SUM(CASE WHEN file_size_in_bytes < 64 * 1048576 THEN 1 ELSE 0 END) AS small_files
FROM prod.events.stream.files
WHERE content = 0;
```

Success criteria:

- median file size rises from 1 MB toward 128-256 MB on cold partitions.
- `files_under_64mb_pct` falls below 0.30 on closed partitions.
- dashboard query median scanned bytes drops below the current 4.8 GB baseline.
- compaction succeeds without conflicts because `where` excludes active partitions.

## Deferred or Rejected Actions

| Action | Why not now |
|---|---|
| Z-order | Sort on two dominant columns is sufficient and easier to reason about; revisit only if query patterns diversify. |
| Manifest rewrite | No high manifest count was exported, so this is not the current bottleneck. |
| Aggressive orphan removal | No orphan inventory is available; start with dry-run after expiry. |
| Do nothing | Query volume is 50,000/month and all files are tiny, so maintenance cost is justified. |

## Resume Notes

Use these files to continue:

- `profile.json`
- `workload.json`
- `simulate_output.txt`
- this report

Open questions:

- Confirm the writer is Flink or Spark Structured Streaming.
- Confirm the real checkpoint interval and whether a 5-minute freshness delay is acceptable.
- Confirm the partition column used in `where => 'event_date < current_date()'`.

Next decision:

Approve writer-property changes first. After one successful write cycle, approve
the cold-partition rewrite if the post-change profile still shows small-file
pressure.
