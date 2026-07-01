#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
COMPOSE_FILE="$SKILL_DIR/docker/docker-compose.yml"

TABLE_NAME="${TABLE_NAME:-demo.input_helper.helper_smoke_${RANDOM}}"
HOST_BUNDLE_ROOT="${HOST_BUNDLE_ROOT:-$SKILL_DIR/tests/.tmp/input_helper_smoke}"
CONTAINER_BUNDLE_ROOT="/opt/tests/.tmp/input_helper_smoke"
SPARK_BUNDLE_DIR="${SPARK_BUNDLE_DIR:-$CONTAINER_BUNDLE_ROOT/spark}"
TRINO_BUNDLE_DIR="${TRINO_BUNDLE_DIR:-$CONTAINER_BUNDLE_ROOT/trino}"
HOST_TRINO_BUNDLE_DIR="$HOST_BUNDLE_ROOT/trino"
CLEANUP="${CLEANUP:-1}"

run_in_spark() {
  docker exec -i \
    -e TABLE_NAME="$TABLE_NAME" \
    -e BUNDLE_DIR="$SPARK_BUNDLE_DIR" \
    -e SPARK_BUNDLE_DIR="$SPARK_BUNDLE_DIR" \
    -e TRINO_BUNDLE_DIR="$TRINO_BUNDLE_DIR" \
    spark-iceberg "$@"
}

run_trino_cli() {
  docker exec trino trino --server http://localhost:8080 "$@"
}

wait_for_spark() {
  for _ in $(seq 1 90); do
    if docker exec spark-iceberg bash -lc 'command -v python >/dev/null && python -c "import pyspark"' >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
  done

  docker compose -f "$COMPOSE_FILE" ps >&2 || true
  echo "spark-iceberg did not become ready" >&2
  return 1
}

wait_for_trino() {
  for _ in $(seq 1 90); do
    if run_trino_cli --execute "SELECT 1" >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
  done

  docker compose -f "$COMPOSE_FILE" ps >&2 || true
  echo "trino did not become ready" >&2
  return 1
}

export_commented_sql_with_trino() {
  local sql_file="$1"
  local out_dir="$2"
  local output_name=""
  local sql=""
  local line=""

  while IFS= read -r line || [[ -n "$line" ]]; do
    if [[ "$line" == "-- output:"* ]]; then
      output_name="${line#-- output: }"
      sql=""
      continue
    fi
    if [[ -z "$output_name" || -z "${line//[[:space:]]/}" || "$line" == --* ]]; then
      continue
    fi

    sql+="$line"$'\n'
    if [[ "$line" == *";" ]]; then
      run_trino_cli --output-format CSV_HEADER --execute "$sql" > "$out_dir/$output_name"
      echo "wrote $out_dir/$output_name"
      output_name=""
      sql=""
    fi
  done < "$sql_file"
}

drop_table() {
  run_in_spark python - <<'PY' >/dev/null 2>&1 || true
import os
from pyspark.sql import SparkSession

table = os.environ["TABLE_NAME"]
spark = (
    SparkSession.builder
    .appName("iceberg-input-helper-smoke-cleanup")
    .config("spark.sql.catalog.demo", "org.apache.iceberg.spark.SparkCatalog")
    .config("spark.sql.catalog.demo.type", "rest")
    .config("spark.sql.catalog.demo.uri", "http://iceberg-rest:8181")
    .config("spark.sql.catalog.demo.io-impl", "org.apache.iceberg.aws.s3.S3FileIO")
    .config("spark.sql.catalog.demo.s3.endpoint", "http://minio:9000")
    .config("spark.sql.catalog.demo.s3.path-style-access", "true")
    .config("spark.sql.defaultCatalog", "demo")
    .config("spark.sql.extensions", "org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions")
    .getOrCreate()
)
spark.sql(f"DROP TABLE IF EXISTS {table}")
spark.stop()
PY
}

cleanup() {
  set +e
  drop_table
  rm -rf "$HOST_BUNDLE_ROOT" >/dev/null 2>&1 || true
  if [[ "$CLEANUP" == "1" ]]; then
    docker compose -f "$COMPOSE_FILE" down >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

echo "Starting Docker Iceberg stack..."
rm -rf "$HOST_BUNDLE_ROOT"
mkdir -p "$HOST_BUNDLE_ROOT"
docker compose -f "$COMPOSE_FILE" up -d
wait_for_spark
wait_for_trino

echo "Creating smoke table: $TABLE_NAME"
run_in_spark python - <<'PY'
import os
from pyspark.sql import SparkSession

table = os.environ["TABLE_NAME"]
namespace = ".".join(table.split(".")[:-1])
spark = (
    SparkSession.builder
    .appName("iceberg-input-helper-smoke")
    .config("spark.sql.catalog.demo", "org.apache.iceberg.spark.SparkCatalog")
    .config("spark.sql.catalog.demo.type", "rest")
    .config("spark.sql.catalog.demo.uri", "http://iceberg-rest:8181")
    .config("spark.sql.catalog.demo.io-impl", "org.apache.iceberg.aws.s3.S3FileIO")
    .config("spark.sql.catalog.demo.s3.endpoint", "http://minio:9000")
    .config("spark.sql.catalog.demo.s3.path-style-access", "true")
    .config("spark.sql.defaultCatalog", "demo")
    .config("spark.sql.extensions", "org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions")
    .getOrCreate()
)

spark.sql(f"CREATE NAMESPACE IF NOT EXISTS {namespace}")
spark.sql(f"DROP TABLE IF EXISTS {table}")
spark.sql(f"""
CREATE TABLE {table} (
  id BIGINT,
  tenant_id STRING,
  event_time TIMESTAMP
)
USING iceberg
PARTITIONED BY (tenant_id)
""")
spark.sql(f"""
INSERT INTO {table} VALUES
  (1, 'tenant-a', TIMESTAMP '2026-01-01 00:00:00'),
  (2, 'tenant-a', TIMESTAMP '2026-01-01 00:05:00'),
  (3, 'tenant-b', TIMESTAMP '2026-01-01 00:10:00')
""")
spark.stop()
PY

echo "Generating Spark input bundle..."
run_in_spark rm -rf "$SPARK_BUNDLE_DIR"
run_in_spark python /opt/scripts/spark_input.py --table "$TABLE_NAME" --out-dir "$SPARK_BUNDLE_DIR"

echo "Exporting metadata queries through Spark..."
run_in_spark python - <<'PY'
import os
import shutil
from pathlib import Path
from pyspark.sql import SparkSession

bundle = Path(os.environ["BUNDLE_DIR"])
spark = (
    SparkSession.builder
    .appName("iceberg-input-helper-smoke-export")
    .config("spark.sql.catalog.demo", "org.apache.iceberg.spark.SparkCatalog")
    .config("spark.sql.catalog.demo.type", "rest")
    .config("spark.sql.catalog.demo.uri", "http://iceberg-rest:8181")
    .config("spark.sql.catalog.demo.io-impl", "org.apache.iceberg.aws.s3.S3FileIO")
    .config("spark.sql.catalog.demo.s3.endpoint", "http://minio:9000")
    .config("spark.sql.catalog.demo.s3.path-style-access", "true")
    .config("spark.sql.defaultCatalog", "demo")
    .config("spark.sql.extensions", "org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions")
    .getOrCreate()
)

pairs = []
output_name = None
statement = []
for raw in (bundle / "metadata_queries.sql").read_text().splitlines():
    line = raw.strip()
    if line.startswith("-- output:"):
        output_name = line.split(":", 1)[1].strip()
        statement = []
        continue
    if not output_name or not line or line.startswith("--"):
        continue
    statement.append(raw)
    if line.endswith(";"):
        pairs.append((output_name, "\n".join(statement).rstrip().rstrip(";")))
        output_name = None
        statement = []

if not pairs:
    raise SystemExit("metadata_queries.sql did not contain exportable statements")

for output_name, sql in pairs:
    target = bundle / output_name
    tmp = bundle / f".tmp_{output_name}"
    shutil.rmtree(tmp, ignore_errors=True)
    spark.sql(sql).coalesce(1).write.mode("overwrite").option("header", True).csv(str(tmp))
    parts = list(tmp.glob("part-*.csv"))
    if not parts:
        raise SystemExit(f"No CSV part written for {output_name}")
    shutil.copyfile(parts[0], target)
    shutil.rmtree(tmp)
    print(f"wrote {target}")

spark.stop()
PY

echo "Running generated profile wrapper..."
run_in_spark bash -lc 'bash "$BUNDLE_DIR/run_profile.sh"'

echo "Creating representative Spark event log and running workload wrapper..."
run_in_spark python - <<'PY'
import json
import os
from pathlib import Path

table = os.environ["TABLE_NAME"]
bundle = Path(os.environ["BUNDLE_DIR"])
plan = (
    f"Scan iceberg {table} "
    "PartitionFilters: [isnotnull(tenant_id#12), (tenant_id#12 = tenant-a)], "
    "dataFilters: [(event_time#13 >= 2026-01-01 00:00:00)]"
)
events = [
    {"Event": "SparkListenerSQLExecutionStart", "executionId": 1, "physicalPlanDescription": plan},
    {
        "Event": "SparkListenerSQLExecutionEnd",
        "executionId": 1,
        "metrics": [{"id": 99, "name": "size of files read"}],
        "metricValues": {"99": "1.0 MB"},
    },
]
with (bundle / "spark_eventlog.json").open("w") as fh:
    for event in events:
        fh.write(json.dumps(event) + "\n")
PY
run_in_spark bash -lc 'bash "$BUNDLE_DIR/run_workload.sh"'

echo "Validating generated JSON outputs..."
run_in_spark python - <<'PY'
import json
import os
from pathlib import Path

bundle = Path(os.environ["BUNDLE_DIR"])
profile = json.loads((bundle / "profile.json").read_text())
workload = json.loads((bundle / "workload.json").read_text())

assert profile["files"]["data_files"] >= 1, profile
assert profile["snapshots"]["snapshot_count"] >= 1, profile
assert workload["parser"] == "spark-eventlog-regex", workload
assert workload["partition_prune_rate"] == 1.0, workload
assert workload["selectivity"]["sample_count"] == 1, workload
assert workload["selectivity"]["median_bytes_scanned"] > 0, workload

print(
    "PASS: spark helper produced profile.json "
    f"({profile['files']['data_files']} data files, "
    f"{profile['snapshots']['snapshot_count']} snapshots) and workload.json "
    f"({workload['selectivity']['median_bytes_scanned']} bytes scanned)."
)
PY

echo "Generating Trino input bundle..."
run_in_spark rm -rf "$TRINO_BUNDLE_DIR"
run_in_spark python /opt/scripts/trino_input.py --table "$TABLE_NAME" --out-dir "$TRINO_BUNDLE_DIR"

echo "Exporting metadata queries through Trino..."
export_commented_sql_with_trino "$HOST_TRINO_BUNDLE_DIR/metadata_queries.sql" "$HOST_TRINO_BUNDLE_DIR"

echo "Running generated Trino profile wrapper..."
run_in_spark bash -lc 'bash "$TRINO_BUNDLE_DIR/run_profile.sh"'

echo "Running representative Trino query and workload export..."
run_trino_cli --execute "SELECT count(*) FROM $TABLE_NAME WHERE tenant_id = 'tenant-a'" >/dev/null
export_commented_sql_with_trino "$HOST_TRINO_BUNDLE_DIR/workload_collection.sql" "$HOST_TRINO_BUNDLE_DIR"
run_in_spark bash -lc 'bash "$TRINO_BUNDLE_DIR/run_workload.sh"'

echo "Validating generated Trino JSON outputs..."
run_in_spark python - <<'PY'
import json
import os
from pathlib import Path

table = os.environ["TABLE_NAME"]
bundle = Path(os.environ["TRINO_BUNDLE_DIR"])
profile = json.loads((bundle / "profile.json").read_text())
workload = json.loads((bundle / "workload.json").read_text())

assert profile["files"]["data_files"] >= 1, profile
assert profile["snapshots"]["snapshot_count"] >= 1, profile
assert workload["table"] == table, workload
assert (bundle / "query_history.csv").read_text().startswith('"query",'), "missing Trino query history CSV"

print(
    "PASS: trino helper produced profile.json "
    f"({profile['files']['data_files']} data files, "
    f"{profile['snapshots']['snapshot_count']} snapshots) and workload.json."
)
PY
