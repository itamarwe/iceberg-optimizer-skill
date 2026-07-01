import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from input_common import (
    render_metadata_sql,
    render_workload_sql,
    split_identifier,
    write_bundle,
)


def test_split_identifier_requires_schema_table():
    try:
        split_identifier("tbl")
    except ValueError as exc:
        assert "schema.table" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_trino_metadata_queries_use_dollar_table_syntax():
    sql = render_metadata_sql("trino", "cat.db.tbl")

    assert '"cat"."db"."tbl$files"' in sql
    assert "-- output: snapshots.csv" in sql
    assert "-- output: manifests.csv" in sql


def test_spark_metadata_queries_use_metadata_table_suffixes():
    sql = render_metadata_sql("spark", "cat.db.tbl")

    assert "SELECT * FROM cat.db.tbl.files;" in sql
    assert "SELECT * FROM cat.db.tbl.partitions;" in sql


def test_glue_bundle_prepends_default_catalog_for_two_part_table():
    with tempfile.TemporaryDirectory() as tmp:
        out = write_bundle("glue", "db.tbl", tmp)

        metadata_sql = (out / "metadata_queries.sql").read_text()
        readme = (out / "README.md").read_text()

        assert "glue_catalog.db.tbl.files" in metadata_sql
        assert "Resolved table: `glue_catalog.db.tbl`" in readme
        assert os.access(out / "run_profile.sh", os.X_OK)


def test_snowflake_workload_csv_matches_parser_columns():
    sql = render_workload_sql("snowflake", "db.schema.orders", 14)

    assert "query_text AS query" in sql
    assert "bytes_scanned AS input_bytes" in sql
    assert "DATEADD(day, -14" in sql


def test_write_bundle_creates_profile_and_workload_runners():
    with tempfile.TemporaryDirectory() as tmp:
        out = write_bundle("trino", "cat.db.tbl", tmp)

        expected = {
            "metadata_queries.sql",
            "workload_collection.sql",
            "run_profile.sh",
            "run_workload.sh",
            "README.md",
        }
        assert expected == {p.name for p in Path(out).iterdir()}

        workload_runner = (out / "run_workload.sh").read_text()
        assert "--trino-queries" in workload_runner
        assert "--table \"cat.db.tbl\"" in workload_runner
