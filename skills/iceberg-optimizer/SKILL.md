---
name: iceberg-optimizer
description: >-
  Diagnoses an Apache Iceberg table and produces a ranked, cost-aware plan
  covering three domains: table layout (compaction, partition evolution, format
  upgrade), ingestion pipeline (write distribution, file sizing, sort order at
  write time), and maintenance (snapshot expiry, orphan cleanup, manifest
  rewrite). Use when asked to optimize, tune, speed up, shrink the cost of,
  clean up, repartition, compact, or design a maintenance schedule for an
  Iceberg table, or to decide whether a table is even worth optimizing.
  Engines: Spark, Trino, AWS Glue/EMR, Snowflake, Flink / Kafka Connect.
  Adapts to Direct mode (live catalog access), Ask-User mode (user runs queries),
  or Exported mode (pre-exported metadata files).
---

# Iceberg Optimizer

A maintenance plan is only as good as the workload it is tuned for. Don't reach
for the standard "compact + sort + expire" runbook before knowing how the table
is written, how it is read, and what the owner pays for — the same table can
warrant aggressive daily sort compaction or *no maintenance at all*.

**Observe before you ask. Ask before you decide. Simulate before you recommend.**

**CRITICAL — gradual loading:** Read nothing beyond this file until the engine
and access mode are identified in Phase 0. Then load only the relevant sections
of reference/engine files at the boundary where they are needed (the
`> Load (...)` callouts mark when). Loading everything up front pollutes context
with information that may never apply to this table.

## The flow

**0 Scope** (table, engine, mode; read-only) → **1 Profile** (physical state from
metadata) → **2 Workload** (2a derive ingestion/access signals · 2b interview for
intent) → **3 Decide** (joint scoring → action groups, incl. "do nothing") →
**4 Simulate** (perf / query-cost / maintenance-cost / storage) → **5 Plan**
(exact engine commands + schedule + monitoring). Each phase below opens with a
`> Load (...)` callout naming exactly what to read.

### Phase 0 — Scope & safety

Establish (ask if not stated): **which table(s)** (`catalog.schema.table`) and
**which engine** (Spark / Trino / Glue/EMR / Snowflake / Flink — syntax differs).

**Read-only until Phase 5.** Never run `expire_snapshots`, `remove_orphan_files`,
`rewrite_data_files`, or any `ALTER TABLE` until a specific plan is approved —
`remove_orphan_files` and `expire_snapshots` *delete files*; treat as destructive.

**Detect access mode** (in order): **Direct** — an Iceberg-capable SQL CLI is
reachable (`trino`, `spark-sql`, `beeline`, or env `TRINO_URL` / `SPARK_HOME` /
`DATABRICKS_HOST` / `SNOWFLAKE_ACCOUNT`); the skill queries autonomously.
**Exported** — the user provided files (profile.json / metadata CSVs); the skill
reads them. **Ask-User** (default) — no access; ask *"Can I run SQL against your
catalog, or should I give you queries to paste back?"* and the user pastes output.

> **Load (Phase 0):** Nothing beyond SKILL.md. Detect mode and engine only.

### Phase 1 — Profile (metadata)

> **Load (Phase 1):** `Grep references/metadata-tables.md` for only the signal
> sections you need (e.g. `$files`, `$snapshots`, `$manifests`). Do NOT read the
> full file.

Read the table's physical state. Run/request the diagnostic queries from
`references/metadata-tables.md` (Direct/Ask-User), or use the provided files
(Exported), then feed them to the profiler:

```
scripts/profile_table.py --snapshots S --files F [--partitions P] [--manifests M] --out profile.json
```

Emits file-size health, small-file pressure, delete-file pressure,
snapshot/manifest bloat, mixed partition specs, total size and file count — this
phase alone answers "is this table healthy?" and is safe on any table.

### Phase 2 — Reconstruct the workload

> **Load (Phase 2a):** Grep `references/metadata-tables.md` for workload-signal
> sections. Grep `references/workload-interview.md` for the derive-then-ask bank.

#### 2a — Derive what metadata already knows

Most ingestion and access questions are *answerable from metadata* — never ask
the user something `$snapshots` and `$files` already answered.

**Ingestion signals & writer identification:** Derive the ingestion signals
(`write_cadence`, `avg_added_file_mb`, `thin_spread`, `late_data`, delete
pressures, `operation_mix`), infer the likely writer from the signal pattern,
and confirm with the user. The signal definitions, the signal-pattern→writer
table, and the confirmation prompts all live in `references/workload-interview.md`
Part 1a — also confirm `distribution_mode`, `ingestion_write_mode` (mor/cow), and
`checkpoint_interval_secs` there, since Group 2 fixes are writer-specific.

**Access pattern signals:**

```
scripts/parse_query_log.py --table catalog.schema.table --out workload.json \
    [--spark-eventlog LOG] [--trino-queries QUERIES] [--explain-analyze explain.txt]
```

Extracts per-table ranked WHERE-clause columns, range vs equality predicates,
partition-pruning effectiveness, selectivity (rows scanned ÷ returned), and
query frequency from Spark event logs, Trino query exports/event-listener logs,
or Trino `EXPLAIN ANALYZE` (run `--help` for the fields each reads). If none are
available, ask the user to run `EXPLAIN ANALYZE` on 3–5 representative queries.

#### 2b — Interview for intent

> **Load (Phase 2b):** Read `references/workload-interview.md` Part 2 only if 2a
> didn't already load it.

Walk `references/workload-interview.md` Part 2. For each item, present what you
derived in 2a, then ask the user to confirm/correct only the genuinely unknowable
parts. Use `AskUserQuestion` — these are real decisions only the owner can make:
query **latency** requirement, query **frequency** & consumers, **freshness** SLA,
**cost priority** (the `--priority` flag for `simulate.py`), **mutability outlook**
(append-only vs updates/deletes/GDPR), **time-travel / replay / audit** need,
**lifecycle / worth** (hot / warm / cold / not worth optimizing), and
**retention / compliance** (only if deletes were observed in 2a).

### Phase 3 — Decide

> **Load (Phase 3):** Read `references/decision-framework.md` in full.

Apply `references/decision-framework.md`: it combines profile + workload signals
into a ranked set of actions across **three groups** (a complete plan usually
draws from more than one):

- **Group 1 — Table Layout:** compaction (bin-pack / sort / z-order), partition
  evolution, equality/position-delete compaction, format upgrade. Run *after* the writer.
- **Group 2 — Ingestion:** write-time distribution mode, file-size buffering,
  write-time sort order, CDC write-mode (MOR→COW). Run these *first* — fixing the
  writer before compacting its output stops the problem recurring.
- **Group 3 — Maintenance:** snapshot expiry, manifest rewrite, orphan removal,
  bloom filters, scheduling. These are ongoing.

Key gates that prevent over-engineering:
- **Low query frequency + cold table → do little or nothing**; maintenance compute
  can cost more than it ever saves, so pay at query time instead.
- **Sort / z-order only when** queries are selective *and* read often enough to
  amortize the rewrite.
- **Aggressive snapshot expiry only when** replay/time-travel is not needed.
- **Bloom filters only for** high-cardinality equality lookups.

> **Load (Group 2 only):** If any Group 2 actions are recommended, load
> `engines/ingestion.md` now — it has the writer-specific configuration blocks.

### Phase 4 — Simulate

> **Load (Phase 4):** No reference files — run `scripts/simulate.py` directly.

Build candidate scenarios and run:

```
scripts/simulate.py --profile profile.json --workload workload.json \
    [--assumptions a.json] --priority <total|storage|query_cost|latency|maintenance_cost>
```

It compares **Do-nothing / Light / Targeted-sort / Aggressive / Storage-min**
scenarios. Present results as directional estimates with ranges, never precise
figures, and highlight the scenario that wins on the chosen priority. Baseline
scan bytes come from
`selectivity.median_bytes_scanned` when present (logs / EXPLAIN ANALYZE),
otherwise `total_gb × (1 − prune_rate)`; override per-scenario scan fractions with
a post-compaction measurement via `--assumptions '{"scan_fraction":
{"targeted_sort": 0.18}}'`.

### Phase 5 — Plan

> **Load (Phase 5):** Read ONLY the engine file(s) in scope — Spark/Glue/EMR →
> `engines/spark.md` (+ `engines/glue.md` for Glue); Trino → `engines/trino.md`;
> Snowflake → `engines/snowflake.md`; Group 2 actions → `engines/ingestion.md`
> (may already be loaded). Do NOT load files for out-of-scope engines. Grep
> `references/scheduling.md` only if a schedule is requested.

Emit the concrete plan for the chosen scenario.

**Operation order — always:** (1) Group 2 ingestion fixes (writer config; takes
effect next run), then (2) Group 1 table layout (compact → expire snapshots →
remove orphans → rewrite manifests), then (3) Group 3 maintenance (schedule
ongoing tasks). Never remove orphans before expiring snapshots.

Then provide: **Commands** (exact, engine-specific, parameters from the profile —
verify capabilities in the loaded engine file; e.g. Trino does NOT support
sort/z-order compaction or manifest clustering, use Spark for those);
**Schedule** (from `references/scheduling.md`, matched to write cadence and
scenario); and **Monitoring** (metadata-table threshold queries that trigger the
next run).

Restate the safety note before any destructive command, and get explicit approval
before running anything that deletes files or rewrites data.

## Files in this skill

Only `SKILL.md` loads up front. `references/` (metadata-tables, workload-interview,
decision-framework, scheduling) and `engines/` (spark, glue, trino, snowflake,
ingestion) load on demand at the `> Load (...)` callouts above. Scripts run
directly, never into context: `profile_table.py`, `parse_query_log.py`,
`simulate.py` under `scripts/`.
