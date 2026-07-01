# iceberg-optimizer

A [Claude Code](https://claude.com/claude-code) skill that diagnoses an Apache
Iceberg table and produces a ranked, **cost-aware** maintenance and layout plan —
compaction (bin-pack / sort / z-order), partition evolution, snapshot expiry,
orphan-file and manifest cleanup, sort orders, and bloom filters — plus a run
schedule.

What makes it different from a static runbook: it **observes before it asks,
asks before it decides, and simulates before it recommends.**

1. **Profile** the table's physical state from its metadata tables.
2. **Reconstruct the workload** — derive ingestion shape (write cadence, file
   size at write, partition fan-out, late data, mutability) from metadata, then
   interview only for the intent metadata can't reveal (latency / freshness SLAs,
   query frequency, cost priority, time-travel needs).
3. **Decide** with a joint framework that gates every action on intent — so a
   cold, rarely-queried table is told to do *nothing* rather than handed a
   pointless compaction job.
4. **Simulate** Do-nothing / Light / Targeted-sort / Aggressive / Storage-min
   scenarios across query latency, query cost, maintenance cost, and storage
   cost, driven by the table's real numbers, so you optimize for the axis you
   care about.
5. **Plan** as a Markdown report with a data-backed action summary, exact
   engine-specific commands (Spark, Trino, AWS Glue/EMR, Snowflake, Flink /
   Kafka Connect), monitoring, and a schedule.

## Install

Install the skill into your Claude Code skills directory:

```bash
# user-level, directly from GitHub
npx github:itamarwe/iceberg-optimizer-skill install

# after npm publication
npx iceberg-optimizer-skill install

# project-level
npx github:itamarwe/iceberg-optimizer-skill install --target <your-repo>/.claude/skills

# Codex user-level install
npx github:itamarwe/iceberg-optimizer-skill install --codex

# manual fallback
cp -r skills/iceberg-optimizer ~/.claude/skills/
```

Then ask Claude Code to "optimize my Iceberg table" (or profile it, design a
maintenance schedule, decide whether it's worth compacting, etc.).

## The scripts (stdlib-only; `sqlglot` optional)

```bash
# 0. Generate engine-specific collection SQL and runners
python scripts/trino_input.py --table cat.db.tbl --out-dir input_bundle
#   (or spark_input.py, glue_input.py, snowflake_input.py)

# 1. Profile from exported metadata tables
python scripts/profile_table.py --snapshots snap.json --files files.json \
    [--partitions parts.json] [--manifests mans.json] --out profile.json

# 2. Reconstruct read access patterns from query logs
python scripts/parse_query_log.py --trino-queries q.json \
    --table cat.db.tbl --out workload.json
#   (or --sql-file q.sql, or --spark-eventlog app.log)
#   Add --explain-analyze explain.txt to supply measured bytes-scanned from
#   Trino EXPLAIN ANALYZE output — replaces the scan baseline heuristic.

# 3. Simulate scenarios across the four cost axes
python scripts/simulate.py --profile profile.json --workload workload.json \
    --queries-per-month 50000 --priority total
```

These scripts read exported Iceberg metadata, query history, and (when available)
ingestion/writer logs — they never open a connection themselves. The **skill**,
however, can run the underlying queries directly against your catalog in **Direct
mode** (`trino` / `spark-sql` / `beeline`), read provided files in **Exported mode**,
or hand you queries to paste back — staying read-only until you approve a plan. The
simulator's cost model is transparent and every assumption is printed and overridable
via `--assumptions`; treat its output as directional, not a benchmark.

## Output report

The default handoff is `iceberg_optimization_report.md`: a Markdown report that
starts with an executive summary and a `Summary: Why Each Action, In One
Sentence` table. Each recommended, skipped, or deferred action is tied to a
specific metric from `profile.json`, `workload.json`, interview answers, or the
simulator output so the user can understand the recommendation and resume later.
An HTML report can be generated as an optional follow-up, but Markdown is the
source of truth.

The `*_input.py` helpers create an input bundle for the engine the user already
has: read-only export SQL, the expected CSV filenames, and `run_profile.sh` /
`run_workload.sh` wrappers. Glue/EMR uses Spark-compatible metadata tables with
the Glue catalog default. Snowflake can provide workload history and snapshots,
but full physical profiling usually needs Spark, Trino, Glue, or another
Iceberg-capable catalog reader.

To smoke-test the generated Spark and Trino helper bundles against the local
Docker Spark/Trino/Iceberg REST/MinIO stack:

```bash
tests/integration/smoke_input_helpers_docker.sh
```

## Layout

```
SKILL.md                          orchestrator: the 5-phase flow
references/metadata-tables.md     metadata table schemas + diagnostic queries
references/workload-interview.md  derive-then-ask question bank
references/decision-framework.md  joint scoring rules + intent gates
references/reporting.md           required Markdown recommendation report shape
references/report-sample.md       sample report to copy structurally
references/procedures.md          routing index → per-engine procedures
references/scheduling.md          archetype→schedule matrix + triggers
references/testing.md             how to validate recommendations safely
engines/                          per-engine syntax: spark · trino · glue ·
                                  snowflake · ingestion
scripts/                          profile_table · parse_query_log · simulate
                                  spark_input · trino_input · glue_input ·
                                  snowflake_input
tests/                            unit tests + skill_benchmark fixtures
docker/                           local Spark + Trino + Iceberg sandbox
```
