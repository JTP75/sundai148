# Tasks

## 0. Data gathering (data session): `corpus-intake`

- [ ] 0.1 Create `corpora.yaml` with entries for orin Hermes and any candidate public corpora (harness, model, date range, privacy class, license/URL)
- [ ] 0.2 Run the orin census in one read transaction, counts only, no adherence. Cover: ledger `before`/`after` content type and sizes, `skill_manage` replay coverage before 2026-10-01, scorable loads and independent sessions per skill, exclusion reasons, task-key coverage (D15), instructed count, Hermes cron preload check (source + config), program frequency list. Verify `census.json` and `manifest.json` exist and contain no adherence fields
- [ ] 0.3 Search public sources for corpora with skill-load events, versioned skill text and, ideally, paired with/without-skill runs; register them and run the census on each that qualifies
- [ ] 0.4 Gate: review the census as a team and record decisions in design.md (version sources available, eligible corpora, preload handling) before task 3 starts

## 1. Setup and audit

- [ ] 1.1 Add `requirements.txt` (pinned, wheels on Windows, macOS and Linux), the `potency/` package skeleton with `python -m` entry points, and `.gitattributes` (`* text=auto eol=lf`); verify `python -m potency.report --help` works on macOS and Windows
- [ ] 1.2 Add the GitHub Actions matrix (ubuntu, macos, windows) running tests, the synthetic end-to-end run and the cross-OS output hash comparison; verify it is green on a PR
- [ ] 1.3 (Justin) Commit the public/local program map from the census program list
- [ ] 1.4 (Justin) Commit the prescription-role maps (required/example/avoid, tool names allowed) for every skill with ≥5 raw loads, and hand-check auto-extraction on 10 other skills. Both are committed before any adherence is computed

## 2. Extraction (source machines): `agent-trace-extraction`

- [ ] 2.1 Implement the signature normalizer (D1: known-CLI two-level subcommands, compound commands) with unit tests for every spec scenario
- [ ] 2.2 Implement ordering, request/result join, successful-load detection, `same_batch`, and command-attempt status; verify on 3 hand-traced sessions (signatures only)
- [ ] 2.3 Implement version sources (ledger replay → `skill_manage` replay → stable core) and prescribed sets with roles; print counts per version source
- [ ] 2.4 Implement `maintenance`/`repeat` flags, trigger labels (on-machine prompt scan, label only), `incomplete`/`overlap` window flags, no-load windows, task keys and provenance (agent-touched)
- [ ] 2.5 Apply the temporal split per corpus; verify no session falls in both splits
- [ ] 2.6 Run the allowlist check and regex scan on outputs, copy derived files to the shared data location, and verify the manifest row counts match

## 3. Expectation model: `adherence-expectation`

- [ ] 3.1 Compute train base rates, IDF weights (D4) and familiarity strata (D6) per corpus
- [ ] 3.2 Fit the per-corpus expectation model on train no-load windows (D3) and the popularity-only baseline, with a train-only vocabulary
- [ ] 3.3 Write `expect_eval.json`: AUC, Brier, calibration bins, hit-rate@{1,5,10} overall and by frequency decile, OOV coverage, step and session counts; verify all methods use the same rows and seen-item mask

## 4. Skill potency (MVP): `skill-potency`

- [ ] 4.1 Synthetic sanity test: a "habit" skill gets lift ≈ 0 with ~100% follow-through and a "novel" skill gets positive lift; this test also serves as the CI end-to-end run
- [ ] 4.2 Compute per-load A, Â, lift, placebo lift (K=20, seed 148) and avoid-match counts; verify sign and value on 3 hand-traced loads
- [ ] 4.3 Rank with shrinkage and bootstrap CIs grouped by session and task key; mark supported skills; report strata, provenance groups, popularity correlations, the bloat stat and the incomplete/overlap sensitivity run; verify `potency.csv` and `strata.csv`
- [ ] 4.4 Generate `potency.png` and `summary.md` per eligible corpus with the three headline numbers and the endogeneity caveat; verify the wording "agreement with prescribed action"

## 5. Stretch (in order; each optional)

- [ ] 5.1 S1 pre/post creation DiD on keyed tasks, by provenance group; feeds headline 2
- [ ] 5.2 S3 paired-run validation, if a paired public corpus exists
- [ ] 5.3 S2 edit-response to recorded skill changes
- [ ] 5.4 BehaviorGPT as an alternative expectation backend (`python -m potency.bgpt_expect`)

## 6. Handover and integration

- [ ] 6.1 Write `docs/runbook.md` (PowerShell and bash commands, data location, current task state) by 17:30; verify that Kris can regenerate the report on Windows from it
- [ ] 6.2 Run all stages end to end from a clean output directory on macOS and Windows, with matching output hashes, producing the chart and summary by 20:00

## Workflow follow-up

- All changes land through PRs. Review outputs with the team before the demo; archive with `/opsx:archive` afterwards.
