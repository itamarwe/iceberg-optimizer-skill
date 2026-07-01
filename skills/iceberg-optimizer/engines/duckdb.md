# DuckDB Iceberg access

Use DuckDB when the user wants a lightweight local engine to inspect Iceberg
metadata or query a REST-catalog table without starting Spark/Trino. Prefer an
existing user-provided gateway first; DuckDB is the fallback when no Spark,
Trino, Snowflake, Glue/EMR, or other Iceberg-capable access path is available.
Keep the skill read-only unless the owner explicitly chooses a write/DDL
operation.

Official DuckDB docs:
- Iceberg extension overview: https://duckdb.org/docs/current/core_extensions/iceberg/overview.html
- Iceberg function reference: https://duckdb.org/docs/current/core_extensions/iceberg/reference.html
- REST catalog setup: https://duckdb.org/docs/current/core_extensions/iceberg/iceberg_rest_catalogs.html
- v1.5.3 Iceberg feature update: https://duckdb.org/2026/05/29/new-iceberg-features.html

## Modes

DuckDB has two Iceberg modes:

1. **Direct metadata path**: read a table by pointing at the table directory or a
   metadata JSON file. This requires no catalog and is read-only.
2. **Attached Iceberg REST catalog**: attach the catalog with `ATTACH ... (TYPE
   iceberg, ...)`. This unlocks catalog-managed reads and write/DDL operations
   such as `CREATE TABLE`, `INSERT`, `UPDATE`, `DELETE`, `MERGE INTO`, and
   `ALTER TABLE` when the catalog/storage supports them.

## Fallback decision

Use this order before proposing DuckDB:

1. If the user has Spark, Trino, Snowflake-managed Iceberg, Glue/EMR, S3 Tables,
   Polaris/Nessie/REST through an existing client, or another approved gateway,
   use that gateway. It has the right catalog semantics, audit trail, and often
   richer query history.
2. If the user has already exported `profile.json`, metadata CSVs, or query
   history, use the exports. Do not ask them to set up DuckDB just to recreate
   data they already supplied.
3. If neither exists, ask for one of:
   - the table metadata path, e.g. `s3://bucket/table/metadata/v42.metadata.json`;
   - the table root plus version-hint access;
   - REST catalog endpoint, warehouse, namespace/table, and non-secret auth
     details. Request secrets only through the user's normal local mechanism.
4. Use DuckDB to collect metadata/profile evidence and validate sample reads.
   Route maintenance to the documented engine that supports the chosen action.

## Setup

```sql
INSTALL iceberg;
LOAD iceberg;
```

### Direct metadata path

```sql
SELECT *
FROM iceberg_scan('/lake/events/metadata/v42.metadata.json');

SELECT *
FROM iceberg_scan('s3://bucket/events/metadata/v42.metadata.json');
```

### REST catalog

```sql
CREATE SECRET iceberg_secret (
  TYPE iceberg,
  CLIENT_ID '<client-id>',
  CLIENT_SECRET '<client-secret>'
);

ATTACH 'warehouse' AS lakehouse (
  TYPE iceberg,
  ENDPOINT 'https://catalog.example.com/iceberg',
  SECRET iceberg_secret
);
```

Catalog-specific options differ for S3 Tables, Glue, Polaris, Lakekeeper,
BigLake, and R2. Ask the user for the catalog type and credentials rather than
guessing.

## Profiling exports

DuckDB exposes metadata table functions that accept either a metadata path or a
fully qualified attached-catalog table name:

```sql
-- table_ref can be '/path/to/table_or_metadata.json' or 'lakehouse.db.tbl'
SELECT * FROM iceberg_snapshots(table_ref);
SELECT * FROM iceberg_metadata(table_ref);
SELECT * FROM iceberg_column_stats(table_ref);
SELECT * FROM iceberg_partition_stats(table_ref);
```

Export the two core profiler inputs:

```sql
COPY (
  SELECT snapshot_id, timestamp_ms
  FROM iceberg_snapshots(table_ref)
) TO 'snapshots.csv' (HEADER, DELIMITER ',');

COPY (
  SELECT content, file_path, file_format, record_count
  FROM iceberg_metadata(table_ref)
) TO 'files.csv' (HEADER, DELIMITER ',');
```

Then run:

```bash
python scripts/profile_table.py --snapshots snapshots.csv --files files.csv --out profile.json
```

DuckDB's `iceberg_metadata` output may not include `file_size_in_bytes`. When
file sizes are missing, the profiler reports `size_metrics_available=false` and
must not claim small-file pressure. For precise small-file diagnosis, supplement
DuckDB with Spark/Trino `$files` exports or object-store inventory that includes
file sizes.

## Workload input

DuckDB does not provide a durable warehouse query-history table comparable to
Trino or Snowflake. Use application logs, saved SQL, or representative queries:

```bash
python scripts/parse_query_log.py --table lakehouse.db.tbl \
  --sql-file representative_queries.sql --out workload.json
```

If the user can provide query profiling output, use it as supporting evidence in
the report, but do not invent a parser path that does not exist in this skill.

## Maintenance routing

DuckDB REST-catalog write support is useful for row-level writes, schema
evolution, and table properties when the user explicitly chooses those actions.
For Iceberg maintenance actions, keep routing conservative:

| Action | DuckDB routing |
|---|---|
| Profile / inspect metadata | Preferred lightweight option |
| Query table for sanity checks | OK via `iceberg_scan` or attached catalog |
| `ALTER TABLE` schema/property changes | OK on attached REST catalog with owner approval |
| `MERGE INTO`, `UPDATE`, `DELETE` | OK on attached REST catalog with owner approval; v3 tables may use binary deletion vectors |
| Bin-pack / sort / z-order compaction | Use Spark or a managed catalog service unless DuckDB docs explicitly support the exact maintenance operation |
| Expire snapshots / remove orphan files / rewrite manifests | Use Spark, Trino, Snowflake-managed, S3 Tables, or another documented maintenance engine |

Do not translate Spark stored procedures into DuckDB syntax. If a recommended
action requires a maintenance procedure DuckDB does not document, emit the
DuckDB profiling/validation commands plus the Spark/Trino/etc. maintenance plan.
