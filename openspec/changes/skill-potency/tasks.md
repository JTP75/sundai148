# Tasks

Each group lists its owner. "W-x" is a parallel worker in its own Orca worktree. "Orch" is the orchestrating session. "Data" is the data session on the source machines. Workers branch from the orchestrator's foundation commit (group 1) and land their work through PRs.

## 0. Data gathering (Data): `corpus-intake`

- [ ] 0.1 Create `corpora.yaml` with entries for orin Hermes and candidate public corpora (harness, model, date range, privacy class, license/URL)
- [ ] 0.2 Run the orin census in one read transaction, counts only, no adherence. Cover: ledger `before`/`after` content type and sizes, `skill_manage` replay coverage before 2026-10-01, scorable loads and independent sessions per skill, exclusion reasons, task-key coverage (D15), instructed count, Hermes cron preload check (source + config), program frequency list. Verify `census.json` and `manifest.json` contain no adherence fields
- [ ] 0.3 Find public corpora with skill-load events, versioned skill text and, ideally, paired with/without-skill runs; register them and run the census on each
- [ ] 0.4 Gate: review the census and record decisions in design.md (available version sources, eligible corpora, preload handling) before real-data scoring (group 7)

## 1. Foundation (Orch, before fan-out)

- [ ] 1.1 Add `requirements.txt` (pinned, wheels on all three OSes), `.gitattributes` (`* text=auto eol=lf`), the `potency/` package skeleton with a `python -m` stub for every stage (D11), and `pyproject.toml` for pytest
- [ ] 1.2 Implement `potency/schema.py` (all D12 tables, rule map, evidence, outputs: columns, types, enums, status and reason codes) and `potency/io.py` (utf-8 JSONL/CSV, sorted keys, fixed float format, checksum helpers)
- [ ] 1.3 Implement `tests/make_fixtures.py` (seed 148). It must produce a synthetic corpus that covers every evidence status and reason code, `same_batch`, `overlap`/`incomplete` windows, maintenance/repeat loads, all three version sources, all three triggers, task keys, a "habit" skill and a "novel" skill with known expected lift, a pre/post-creation task, an edit event, and a paired with/without-skill subset
- [ ] 1.4 Freeze the foundation: commit, push, and verify `pytest` collects and the fixtures regenerate byte-identically

## 2. Source-machine stages (W-1): `corpus-intake`, `agent-trace-extraction`

- [ ] 2.1 `potency/normalize.py`: D1 normalizer (known-CLI two-level subcommands, compound commands, secret-free), with tests for every spec scenario
- [ ] 2.2 `potency/adapters/hermes.py`: one read transaction against a `mode=ro` source, ordering, request/result join, successful loads, `same_batch`, command-attempt status, maintenance/repeat flags, trigger labels (on-machine prompt scan, label only), window flags, no-load windows, task keys (D15), version sources (D14), provenance and agent-touched (D16), temporal split. Test against a tiny synthetic Hermes-schema SQLite built in the test
- [ ] 2.3 `potency/extract.py`, `census.py` (outcome-free), `draft_rules.py` (draft rule map with no skill text exported) and `bundle.py` (zip plus SHA-256 list); stdlib only, enforced by a test that imports them with third-party packages blocked
- [ ] 2.4 Private-field allowlist check and regex backstop scan, run inside `extract` and `bundle`; tests prove that queries, prompts and arguments never appear in outputs

## 3. Public corpus adapters (W-2): `corpus-intake`

- [ ] 3.1 For each public corpus registered in 0.3, add `potency/adapters/<name>.py` emitting the D12 tables, including paired-run markers when present; test it on a small checked-in sample under the corpus's license, or on a synthetic sample of the same shape
- [ ] 3.2 If no public corpus is registered yet, build the adapter interface test harness so a new adapter is a single file

## 4. Evidence and expectation (W-3): `adherence-evidence`, `adherence-expectation`

- [ ] 4.1 `potency/evidence.py`: the D18 status contract from loads, steps and the rule map (approved or `auto`), with tests for every status and reason scenario
- [ ] 4.2 `potency/expect.py`: per-corpus base rates, IDF weights, familiarity strata, the expectation model on train no-load windows, the popularity baseline, a train-only vocabulary; write `expect_eval.json` (AUC, Brier, calibration, hit-rate@{1,5,10} overall and by decile, OOV coverage, counts), with tests

## 5. Scoring and analyses (W-4): `skill-potency`

- [ ] 5.1 `potency/score.py`: A from evidence, Â, lift, placebo lift (K=20, seed 148), avoid matches, strata, shrinkage ranking with grouped bootstrap, supported marking, popularity check, bloat stat, incomplete/overlap sensitivity; write `potency.csv` and `strata.csv`. Test that the "habit" skill gets lift ≈ 0 at ~100% follow-through and the "novel" skill gets positive lift
- [ ] 5.2 Pre/post-creation DiD, edit-response, paired-run validation and the trigger split; write `experiments.json`, with "not computable" entries when inputs are missing; test against the fixture's known effects

## 6. Report, platform and handover (W-5): `skill-potency`, `adherence-evidence`, `cross-platform-runtime`

- [ ] 6.1 `potency/report.py` and `run_all.py`: `potency.png`, `status.png` and `summary.md` per corpus, with the three headline numbers, the endogeneity caveat, the loaded-episodes disclosure, "agreement with prescribed action" wording, example rows per status, and the rule-map and program-map appendix
- [ ] 6.2 GitHub Actions matrix (ubuntu, macos, windows): pytest plus `run_all` on the fixtures, with an output-hash comparison across OSes
- [ ] 6.3 `docs/runbook.md`: PowerShell and bash setup, bundle unpack (`Expand-Archive`), checksum verification, `run_all`, where outputs land, and a task-state section

## 7. Integration and real data (Orch + Data + Justin)

- [ ] 7.1 Orch: merge worker PRs, run the full fixture pipeline on Linux, and confirm CI is green on all three OSes
- [ ] 7.2 Data: run extract, census, draft_rules and bundle on orin (and on public corpora) with the merged code, then hand the zip to Justin
- [ ] 7.3 Justin: approve the rule map and the public/local program map and commit both (maps hold no skill text)
- [ ] 7.4 Orch: run `run_all` on the real bundle, review outputs against the census, and fix any issues through PRs
- [ ] 7.5 Justin shares the bundle and outputs with Kris via Google Drive; Kris reproduces `run_all` on Windows from the runbook, with matching output hashes

## Workflow follow-up

- All changes land through PRs. Archive with `/opsx:archive` after the demo.
