# Contributing

Thanks for your interest in improving **iceberg-optimizer-skill**. Issues, fixes,
new engine support, and additional benchmark scenarios are all welcome.

## Disclosure

This skill — its reference material, scripts, benchmark suite, and reports — was
authored with substantial help from an AI coding assistant (Claude Code) and
reviewed by a human maintainer. The recommendations it encodes are drawn from
published Apache Iceberg guidance and production failure patterns. Treat the
skill's output (and the simulator's cost model in particular) as **directional
advice, not a benchmark** — always validate against your own tables before
running anything destructive.

## Development setup

The runtime scripts are standard-library only (`sqlglot` is an optional
dependency for richer SQL parsing). The unit tests use `pytest`.

```bash
cd skills/iceberg-optimizer
pip install pytest                              # only test dependency
python -m pytest tests/                         # unit tests (fast)
python tests/skill_benchmark/run_benchmark.py --all --judge   # full scenario suite
```

The scenario benchmark drives the `claude` CLI (Claude Code) and needs it
installed and authenticated; see
[`tests/skill_benchmark/benchmark_report.md`](skills/iceberg-optimizer/tests/skill_benchmark/benchmark_report.md)
for what it measures.

An optional local Iceberg sandbox (Spark + REST catalog + MinIO) lives in
[`skills/iceberg-optimizer/docker/`](skills/iceberg-optimizer/docker/):

```bash
cd skills/iceberg-optimizer/docker
docker compose up -d
docker exec -it spark-iceberg bash
```

## Making changes

- **Keep the scripts stdlib-only.** New required third-party dependencies will
  not be accepted for `scripts/`; gate optional ones behind a lazy import.
- **Add a test or fixture** when you change behavior. Profiler/parser changes go
  in `tests/`; skill-advice changes are best covered by a new scenario under
  `tests/skill_benchmark/`.
- **Run `pytest` and (if you touched skill content) the scenario suite** before
  opening a PR, and note the results in the PR description.
- Keep documentation in sync — the per-engine syntax under `engines/` and the
  decision rules under `references/` should match what the scripts emit.

## License

By contributing, you agree that your contributions are licensed under the
[Apache License 2.0](LICENSE), the same license that covers this project.
