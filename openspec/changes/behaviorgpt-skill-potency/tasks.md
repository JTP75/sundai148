# Tasks

## 1. Setup

- [ ] 1.1 Create a Python ≥3.11 venv on the Mac with pyarrow, pandas, numpy, scikit-learn, matplotlib; verify imports
- [ ] 1.2 Resolve design.md open questions with the data session: cron job key per session, curator ledger before/after text on orin, how prompt-instructed or preloaded skills appear; record answers in design.md

## 2. Trace extraction (pacel-orin): `agent-trace-extraction`

- [ ] 2.1 Inspect the `state.db` schema read-only (`sqlite3 'file:...?mode=ro'`); verify by printing 5 decoded tool calls (signatures only)
- [ ] 2.2 Implement the signature normalizer (D1) with unit tests for the spec scenarios (`git rebase -i HEAD~3` → `terminal: git rebase`, `read_file` drops paths, secrets leak nothing); verify tests pass
- [ ] 2.3 Build histories and the temporal split (D8); verify the mixed-session example and that no session falls in both splits
- [ ] 2.4 Rebuild skill versions at load time from the curator ledger and extract prescribed sets with the same normalizer; flag `version_unknown`; hand-check 10 skills; print counts of empty and `version_unknown` loads
- [ ] 2.5 Flag `maintenance` and `repeat` loads and label `instructed` vs `chosen`; verify on 3 hand-traced loads
- [ ] 2.6 Emit no-load windows and per-skill provenance (`created_at`, `created_by`, per-patch added/removed signatures)
- [ ] 2.7 Regex-scan all outputs for tokens, URLs and paths; scp to the Mac; verify row counts match and `state.db`'s mtime is unchanged

## 3. Expectation model (Mac): `adherence-expectation`

- [ ] 3.1 Compute train base rates, IDF weights (D4), and familiarity strata (D6); commit the public/local program map before any test result is viewed
- [ ] 3.2 Fit the expectation model on train no-load windows (D3) and the popularity-only baseline
- [ ] 3.3 Write `expect_eval.json`: AUC, Brier, calibration bins, precision@{1,5,10} overall and by frequency decile, for both; verify both use the same rows

## 4. Skill potency (MVP): `skill-potency`

- [ ] 4.1 Sanity test on synthetic data: a "habit" skill prescribing habitual commands gets lift ≈ 0 with ~100% follow-through; a "novel" skill gets positive lift; verify both
- [ ] 4.2 Compute per-load A, Â, lift and placebo lift (K=20) for scorable loads; verify sign and value on 3 hand-traced loads
- [ ] 4.3 Rank skills with shrinkage, session bootstrap CIs and the ≥5 support threshold; report strata and the popularity correlations; verify `potency.csv` and `strata.csv`
- [ ] 4.4 Generate `potency.png` and `summary.md` with the three headline numbers and the endogeneity caveat; verify the wording "agreement with prescribed action"

## 5. Stretch (in order; each optional)

- [ ] 5.1 S1 pre/post creation DiD on recurring tasks, split by `created_by`; feeds headline 2
- [ ] 5.2 S2 edit-response to ledger patches
- [ ] 5.3 S3 BehaviorGPT as an alternative expectation backend (`bgpt_expect.py`): API key, signature-only catalog, embed, compare in `expect_eval.json`

## 6. Integration

- [ ] 6.1 Run all stages end to end from a clean output directory without manual steps, producing the chart and summary by 20:00

## Workflow follow-up

- Review outputs with the team before demo; archive with `/opsx:archive` afterwards.
