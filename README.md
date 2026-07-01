# iceberg-optimizer-skill

A [Claude Code](https://claude.com/claude-code) **Agent Skill** that diagnoses an
Apache Iceberg table and produces a ranked, cost-aware Markdown report across three domains —
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
├── references/                decision framework, procedures, reporting, interview, scheduling
├── engines/                   per-engine syntax (spark, trino, glue, snowflake, …)
├── scripts/                   engine input helpers · profile_table ·
│                              parse_query_log · simulate (stdlib-only)
├── tests/                     unit tests + skill_benchmark fixtures
└── docker/                    local Spark + Trino + Iceberg sandbox
```

## Install

The installer is published as
[`iceberg-optimizer-skill`](https://www.npmjs.com/package/iceberg-optimizer-skill)
on npm.

```bash
# user-level via npm (available in every project)
npx iceberg-optimizer-skill install

# project-level via npm (scoped to one repo)
npx iceberg-optimizer-skill install --target <your-repo>/.claude/skills

# Codex user-level install
npx iceberg-optimizer-skill install --codex

# install directly from GitHub for unreleased branches/forks
npx github:itamarwe/iceberg-optimizer-skill install
npx github:itamarwe/iceberg-optimizer-skill#main install

# manual project-level fallback from a local clone
cp -r skills/iceberg-optimizer <your-repo>/.claude/skills/

# manual user-level fallback from a local clone
cp -r skills/iceberg-optimizer ~/.claude/skills/
```

Then ask Claude Code to *"optimize my Iceberg table"* — or to profile it, design
a maintenance schedule, or decide whether it's even worth compacting.

See [`skills/iceberg-optimizer/README.md`](skills/iceberg-optimizer/README.md)
for the full walkthrough and standalone script usage.

## How this compares to other Iceberg skills

Several good Iceberg skills exist; they solve different problems. This one is an
**optimization decision engine** — it reads a specific table's real metadata and
query workload and produces a cost-ranked, table-specific plan (up to and
including *do nothing*), backed by runnable scripts and a scenario benchmark.

|  | **This skill** | **Advisory / best-practice skills** | **Platform-native skills** (e.g. Databricks) |
|---|---|---|---|
| Goal | Decide *whether & how* to optimize *this* table | Answer Iceberg questions correctly | Operate Iceberg inside one platform |
| Profiles the real table + workload | ✅ | ❌ | ❌ |
| Cost simulation across axes | ✅ | ❌ | ❌ (platform auto-manages) |
| Runnable scripts, not just prose | ✅ | ❌ | ❌ |
| Scenario benchmark validating advice | ✅ | ❌ | ❌ |
| Breadth of catalogs / format-spec depth | focused | often wider | platform-scoped |

In short: advisory skills encode broad correctness, and platform skills encode
correct in-platform operations; this skill is the one that looks at *your*
table's numbers and tells you what it specifically needs — and proves the
recommendation against a benchmark suite. The two kinds are complementary: pair
this with a platform skill when you live inside one warehouse.

## Development

```bash
cd skills/iceberg-optimizer
pip install pytest                              # only dependency, for the unit tests
python -m pytest tests/                         # unit tests
tests/integration/smoke_input_helpers_docker.sh  # Docker Spark+Trino/Iceberg helper smoke test
python tests/skill_benchmark/run_benchmark.py --all --judge   # scenario benchmark (needs the `claude` CLI)
```

The scripts themselves are standard-library only (`sqlglot` optional) and never open
a connection — they operate on exported Iceberg metadata and logs. The **skill** can
connect when you let it: in **Direct mode** it runs the diagnostic queries against
your catalog itself (`trino` / `spark-sql` / `beeline`, or `TRINO_URL` / `SPARK_HOME`
/ `DATABRICKS_HOST` / `SNOWFLAKE_ACCOUNT`); in **Exported mode** it reads files you
provide; otherwise it hands you queries to paste back. Either way it stays
**read-only until you approve a plan** — it never runs a destructive operation on its
own.

## Contributing

Issues and PRs welcome — see [`CONTRIBUTING.md`](CONTRIBUTING.md) for setup, test,
and benchmark instructions. This skill was authored with substantial help from an
AI coding assistant and reviewed by a human maintainer; treat its output as
directional advice and validate against your own tables before running anything
destructive.

## License

Apache License 2.0 — see [`LICENSE`](LICENSE) and [`NOTICE`](NOTICE).
