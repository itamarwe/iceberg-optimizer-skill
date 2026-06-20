# iceberg-optimizer-skill

A [Claude Code](https://claude.com/claude-code) **Agent Skill** that diagnoses an
Apache Iceberg table and produces a ranked, cost-aware plan across three domains —
**table layout** (compaction, partition evolution, format upgrade), **ingestion
pipeline** (write distribution, file sizing, sort-at-write), and **maintenance**
(snapshot expiry, orphan cleanup, manifest rewrite) — plus a run schedule.

It is built on one rule: **observe before you ask, ask before you decide,
simulate before you recommend.** Rather than reaching for the standard
"compact + sort + expire" runbook, it profiles the table's real metadata,
reconstructs the workload, and simulates trade-offs so the recommendation fits
the table you actually have.

Engines: Spark · Trino · AWS Glue/EMR · Snowflake · Flink / Kafka Connect.

## Repository layout

```
skills/iceberg-optimizer/      the skill (this is what you install)
├── SKILL.md                   orchestrator: the 5-phase flow
├── README.md                  skill overview, install, and script usage
├── references/                decision framework, procedures, interview, scheduling
├── engines/                   per-engine syntax (spark, trino, glue, snowflake, …)
├── scripts/                   profile_table · parse_query_log · simulate (stdlib-only)
├── tests/                     unit tests + skill_benchmark fixtures
└── docker/                    local Spark + Iceberg sandbox
```

## Install

```bash
# user-level (available in every project)
cp -r skills/iceberg-optimizer ~/.claude/skills/

# or project-level (scoped to one repo)
cp -r skills/iceberg-optimizer <your-repo>/.claude/skills/
```

Then ask Claude Code to *"optimize my Iceberg table"* — or to profile it, design
a maintenance schedule, or decide whether it's even worth compacting.

See [`skills/iceberg-optimizer/README.md`](skills/iceberg-optimizer/README.md)
for the full walkthrough and standalone script usage.

## Development

```bash
cd skills/iceberg-optimizer
python -m pytest tests/                    # unit tests
python tests/skill_benchmark/run_benchmark.py   # scenario benchmark
```

The scripts are standard-library only (`sqlglot` optional). The skill never
connects to your warehouse — it operates on exported Iceberg metadata and query
logs.
