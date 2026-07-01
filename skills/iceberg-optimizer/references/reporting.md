# Recommendation report format

Use this format in Phase 5 after the user has selected or accepted a scenario.
The primary deliverable is Markdown. Generate an HTML version only if the user
asks for one.

For non-trivial reports, read `references/report-sample.md` as a concrete
template and copy its structure, not its facts or action choices.

## Required report order

1. `# Iceberg Optimization Report: <table>`
2. Snapshot of inputs: engine, catalog if known, access mode, profile/workload
   file names, simulator priority, and date generated.
3. `## Executive Summary`: 3-6 bullets covering the chosen scenario, the main
   bottleneck, expected impact direction, and the highest-risk assumption.
4. `## Summary: Why Each Action, In One Sentence`: a table with columns
   `Action` and `Why? (data-driven)`.
5. `## Decision Inputs`: compact profile metrics, workload metrics, interview
   intent, and simulator result used to make the decision.
6. `## Recommendation`: ordered action bundle, including prerequisites.
7. `## Execution Commands`: read-only checks first, then owner-approved
   maintenance commands. Repeat the destructive-operation safety note before
   `expire_snapshots`, `remove_orphan_files`, or any rewrite/delete operation.
8. `## Schedule and Triggers`: cadence, thresholds, and what to rerun.
9. `## Monitoring`: queries or metrics proving the action worked.
10. `## Deferred or Rejected Actions`: actions considered and skipped, with the
    metric or gate that blocked them.
11. `## Resume Notes`: exact files, assumptions, open questions, and next
    decision needed so the user can continue later.

## Summary table rules

Every `Why?` cell must include at least one concrete input, such as:

- `files_under_64mb_pct=0.91`
- `median_mb=12.4 vs target_mb=256`
- `eq_delete_pressure=0.10`
- `snapshot_count=1200`
- `partition_prune_rate=0.0`
- `filter_columns[0]=tenant_id (share=0.98)`
- `query_frequency=3/year`
- `time_travel_need=none`
- `simulator winner=storage_min on storage priority`

Prefer one sentence per action. If an action needs a caveat, put the caveat in
the detailed section rather than bloating the summary table.

Example:

| Action | Why? (data-driven) |
|---|---|
| A - Bin-pack cold partitions | 91% of data files are under 64 MB and median file size is 12 MB, so file-open/planning overhead is dominating scans. |
| F - Snapshot expiry | 1,200 snapshots with only 14 days of rollback required means old metadata can be safely expired after the retention window. |
| Skip sort compaction | The workload has 3 audit queries per year and simulator query savings are below rewrite cost, so sorting cannot amortize. |

## Tone

Be concise, but do not merely list commands. The user should understand why each
action was recommended, why common alternatives were skipped, and what evidence
would change the recommendation later.
