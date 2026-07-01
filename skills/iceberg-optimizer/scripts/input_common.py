#!/usr/bin/env python3
"""Generate engine-specific input collection bundles for iceberg-optimizer.

The bundle tells a user exactly which read-only metadata/query-history exports
to create, then provides shell wrappers that turn those exports into
profile.json and workload.json using the existing skill scripts.
"""
import argparse
import os
import re
from pathlib import Path
from textwrap import dedent

METADATA_TABLES = ("snapshots", "files", "partitions", "manifests")

SPARK_PROFILE_SELECTS = {
    "snapshots": (
        "committed_at, snapshot_id, parent_id, operation, "
        "to_json(summary) AS summary"
    ),
    "files": "content, file_path, file_format, record_count, file_size_in_bytes",
    "partitions": "record_count, file_count",
    "manifests": "partition_spec_id",
}

TRINO_PROFILE_SELECTS = {
    "snapshots": (
        "committed_at, snapshot_id, parent_id, operation, "
        "json_format(CAST(summary AS JSON)) AS summary"
    ),
    "files": "content, file_path, file_format, record_count, file_size_in_bytes",
    "partitions": "record_count, file_count",
    "manifests": "partition_spec_id",
}


def split_identifier(identifier):
    parts = [p.strip().strip('`"') for p in identifier.split(".") if p.strip()]
    if len(parts) < 2:
        raise ValueError(
            "table must include at least schema.table; prefer catalog.schema.table"
        )
    return parts


def apply_default_catalog(table, catalog):
    parts = split_identifier(table)
    if catalog and len(parts) == 2:
        return ".".join([catalog] + parts)
    return ".".join(parts)


def spark_ref(table, metadata_name, catalog=None):
    return f"{apply_default_catalog(table, catalog)}.{metadata_name}"


def trino_quote(identifier):
    return '"' + identifier.replace('"', '""') + '"'


def trino_ref(table, metadata_name):
    parts = split_identifier(table)
    if len(parts) < 3:
        prefix = ".".join(trino_quote(p) for p in parts[:-1])
    else:
        prefix = ".".join(trino_quote(p) for p in parts[:2])
    return f"{prefix}.{trino_quote(parts[-1] + '$' + metadata_name)}"


def snowflake_parts(table):
    parts = split_identifier(table)
    if len(parts) == 2:
        return None, parts[0].upper(), parts[1].upper()
    return parts[-3].upper(), parts[-2].upper(), parts[-1].upper()


def sql_literal(value):
    return "'" + value.replace("'", "''") + "'"


def render_metadata_sql(engine, table, catalog=None):
    lines = [
        "-- Read-only Iceberg metadata exports for iceberg-optimizer.",
        "-- Export each result set to the CSV filename named above the query.",
        "",
    ]
    if engine in ("spark", "glue"):
        default_catalog = catalog or ("glue_catalog" if engine == "glue" else None)
        for name in METADATA_TABLES:
            lines.extend([
                f"-- output: {name}.csv",
                f"SELECT {SPARK_PROFILE_SELECTS[name]}",
                f"FROM {spark_ref(table, name, default_catalog)};",
                "",
            ])
    elif engine == "trino":
        for name in METADATA_TABLES:
            lines.extend([
                f"-- output: {name}.csv",
                f"SELECT {TRINO_PROFILE_SELECTS[name]}",
                f"FROM {trino_ref(table, name)};",
                "",
            ])
    elif engine == "snowflake":
        database, schema, name = snowflake_parts(table)
        db_note = (
            f"USE DATABASE {database};\n" if database else
            "-- Run in the database that contains the Iceberg table.\n"
        )
        lines.extend([
            "-- Snowflake-managed Iceberg exposes snapshot metadata, but it does",
            "-- not expose the full Iceberg $files/$partitions/$manifests tables",
            "-- in the same shape as Spark/Trino. Use Spark/Trino/Glue against the",
            "-- catalog for full profile exports when possible.",
            "",
            db_note.rstrip(),
            f"USE SCHEMA {schema};",
            "",
            "-- output: snapshots.csv",
            "SELECT *",
            "FROM TABLE(INFORMATION_SCHEMA.ICEBERG_TABLE_SNAPSHOTS(",
            f"  TABLE_NAME => {sql_literal(name)},",
            f"  SCHEMA_NAME => {sql_literal(schema)}",
            "));",
            "",
        ])
    else:
        raise ValueError(f"unsupported engine: {engine}")
    return "\n".join(lines)


def render_workload_sql(engine, table, days):
    short_name = split_identifier(table)[-1]
    if engine == "trino":
        return dedent(f"""\
            -- output: query_history.csv
            -- system.runtime.queries is short-lived. Prefer event-listener logs
            -- when available, but this is useful for active recent queries.
            SELECT
              query,
              query_id,
              created,
              physical_input_bytes AS input_bytes,
              processed_input_rows AS input_rows
            FROM system.runtime.queries
            WHERE state = 'FINISHED'
              AND lower(query) LIKE lower('%{short_name}%')
            ORDER BY created DESC;
            """)
    if engine == "snowflake":
        return dedent(f"""\
            -- output: query_history.csv
            -- Feed this CSV to parse_query_log.py with --trino-queries; the parser
            -- consumes generic columns named query/input_bytes/output_rows.
            SELECT
              query_text AS query,
              query_id,
              start_time,
              bytes_scanned AS input_bytes,
              rows_produced AS output_rows,
              total_elapsed_time AS elapsed_ms
            FROM snowflake.account_usage.query_history
            WHERE start_time >= DATEADD(day, -{int(days)}, CURRENT_TIMESTAMP())
              AND query_text ILIKE '%{short_name}%'
            ORDER BY start_time DESC;
            """)
    return dedent("""\
        Spark and Glue/EMR workload input comes from Spark event logs, not SQL
        history tables. Copy the relevant event log to spark_eventlog.json in
        this bundle directory, then run ./run_workload.sh.
        """)


def render_profile_runner(skill_dir):
    return dedent(f"""\
        #!/usr/bin/env bash
        set -euo pipefail
        BUNDLE_DIR="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"
        PROFILE_SCRIPT="{skill_dir}/scripts/profile_table.py"

        args=(
          --snapshots "$BUNDLE_DIR/snapshots.csv"
          --files "$BUNDLE_DIR/files.csv"
          --out "$BUNDLE_DIR/profile.json"
        )
        [[ -f "$BUNDLE_DIR/partitions.csv" ]] && args+=(--partitions "$BUNDLE_DIR/partitions.csv")
        [[ -f "$BUNDLE_DIR/manifests.csv" ]] && args+=(--manifests "$BUNDLE_DIR/manifests.csv")

        python "$PROFILE_SCRIPT" "${{args[@]}}"
        """)


def render_workload_runner(engine, table, skill_dir):
    parser = f"{skill_dir}/scripts/parse_query_log.py"
    if engine in ("trino", "snowflake"):
        return dedent(f"""\
            #!/usr/bin/env bash
            set -euo pipefail
            BUNDLE_DIR="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"
            [[ -f "$BUNDLE_DIR/query_history.csv" ]] || {{
              echo "Missing $BUNDLE_DIR/query_history.csv" >&2
              exit 1
            }}
            python "{parser}" \\
              --table "{table}" \\
              --trino-queries "$BUNDLE_DIR/query_history.csv" \\
              --out "$BUNDLE_DIR/workload.json"
            """)
    return dedent(f"""\
        #!/usr/bin/env bash
        set -euo pipefail
        BUNDLE_DIR="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"
        [[ -f "$BUNDLE_DIR/spark_eventlog.json" ]] || {{
          echo "Missing $BUNDLE_DIR/spark_eventlog.json" >&2
          exit 1
        }}
        python "{parser}" \\
          --table "{table}" \\
          --spark-eventlog "$BUNDLE_DIR/spark_eventlog.json" \\
          --out "$BUNDLE_DIR/workload.json"
        """)


def render_readme(engine, table, full_table):
    profile_note = (
        "Run `metadata_queries.sql` and export each result set to the matching CSV file."
    )
    if engine == "snowflake":
        profile_note = (
            "Snowflake can collect workload history here, but full physical profiling "
            "usually needs Spark, Trino, Glue, or DuckDB against the Iceberg catalog."
        )
    return dedent(f"""\
        # iceberg-optimizer input bundle

        Engine: {engine}
        Requested table: `{table}`
        Resolved table: `{full_table}`

        1. {profile_note}
        2. Place the CSV files in this directory.
        3. Run `./run_profile.sh` to create `profile.json` when `snapshots.csv`
           and `files.csv` are available.
        4. Use `workload_collection.sql` or the event-log note to collect workload
           history, then run `./run_workload.sh` to create `workload.json`.

        Expected profile export files:
        - `snapshots.csv`
        - `files.csv`
        - `partitions.csv` (optional but recommended)
        - `manifests.csv` (optional but recommended)

        The generated commands are read-only. They do not run Iceberg maintenance.
        """)


def write_bundle(engine, table, out_dir, query_days=7, catalog=None, skill_dir=None):
    engine = engine.lower()
    if engine == "emr":
        engine = "glue"
    if engine not in {"spark", "glue", "trino", "snowflake"}:
        raise ValueError(f"unsupported engine: {engine}")

    skill_dir = Path(skill_dir or Path(__file__).resolve().parent.parent)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    full_table = apply_default_catalog(
        table, catalog or ("glue_catalog" if engine == "glue" else None)
    )

    files = {
        "metadata_queries.sql": render_metadata_sql(engine, table, catalog),
        "workload_collection.sql": render_workload_sql(engine, table, query_days),
        "run_profile.sh": render_profile_runner(skill_dir),
        "run_workload.sh": render_workload_runner(engine, full_table, skill_dir),
        "README.md": render_readme(engine, table, full_table),
    }
    for name, text in files.items():
        path = out / name
        path.write_text(text.rstrip() + "\n")
        if name.endswith(".sh"):
            os.chmod(path, 0o755)
    return out


def build_parser(engine):
    ap = argparse.ArgumentParser(
        description=f"Create a read-only {engine} input bundle for iceberg-optimizer."
    )
    ap.add_argument("--table", required=True, help="Iceberg table, e.g. catalog.db.tbl")
    ap.add_argument("--out-dir", default="iceberg_optimizer_input",
                    help="directory to create (default: iceberg_optimizer_input)")
    ap.add_argument("--query-days", type=int, default=7,
                    help="query history lookback when the engine supports it")
    ap.add_argument("--catalog",
                    help="default catalog to prepend when --table is schema.table")
    return ap


def main(engine, argv=None):
    args = build_parser(engine).parse_args(argv)
    try:
        out = write_bundle(
            engine=engine,
            table=args.table,
            out_dir=args.out_dir,
            query_days=args.query_days,
            catalog=args.catalog,
        )
    except ValueError as exc:
        raise SystemExit(str(exc))
    print(f"wrote {engine} input bundle: {out}")
    return 0


if __name__ == "__main__":
    script = Path(__file__).stem
    match = re.match(r"(.+)_input$", script)
    raise SystemExit(main(match.group(1) if match else "spark"))
