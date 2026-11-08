# Tasks

## 1. Setup

- [ ] 1.1 Get an Unbox AI API key (portal.unboxai.com, email sign-in) and export `UNBOXAI_API_KEY` on the Mac; verify `client.list_catalogs()` returns the shared catalogs
- [ ] 1.2 Create a Python ≥3.11 venv on the Mac with `behaviorgpt>=0.10`, pyarrow, pandas, matplotlib; verify `from behaviorgpt import ExternalItem, AsyncUnboxAIClient` imports
- [ ] 1.3 Resolve the open questions in design.md: find the `id`-filter syntax (anomaly repo `api.py` or OpenAPI), check per-event timestamps on `View`, and locate the SKILL.md files on pacel-orin; record the answers in design.md and verify each one with a one-call smoke test or `ls`

## 2. Trace extraction (pacel-orin) — `agent-trace-extraction`

- [ ] 2.1 Inspect the `state.db` schema read-only (`sqlite3 'file:...?mode=ro'`) and write down which columns hold tool calls, session ids and timestamps; verify by printing 5 decoded tool calls
- [ ] 2.2 Implement the signature normalizer (D2) with unit tests covering the spec scenarios: `git rebase -i HEAD~3` → `terminal: git rebase`, `read_file` drops paths, secret-bearing commands leak nothing; verify the tests pass
- [ ] 2.3 Implement history mapping (commands → View, search → Search, skill load → external skill View) and the temporal split (D7 cutoff); verify the spec's mixed-session example reproduces exactly and that no session falls in both splits
- [ ] 2.4 Extract prescribed command sets from each SKILL.md code block with the same normalizer; verify by hand-checking 10 skills and printing the count of skills with an empty set
- [ ] 2.5 Build `catalog.parquet` (D3; frequency and sales_since from train only) with `catalog_from_csv` or `CATALOG_SCHEMA`; verify `check_catalog_schema` passes and a regex scan finds no tokens, URLs or paths in any output file
- [ ] 2.6 Write `histories.jsonl` and `skill_loads.jsonl`, scp all three files to the Mac, and verify the row counts match on both machines; confirm `state.db`'s mtime did not change

## 3. Scoring (Mac) — `behavior-scoring`

- [ ] 3.1 Embed a 50-row slice of the catalog, then the full catalog (`client.embed(..., wait=True)`); verify `complete([Search("rebase")], catalog_id=...)` returns git-related items
- [ ] 3.2 Implement the cached async scoring client (head top-100 call + `id`-filtered tail call, no `user_id`); verify a rerun of 20 steps makes zero network calls
- [ ] 3.3 Implement the probability/entropy/excess-surprisal computation (D5) and fit τ on train steps only; unit-test it against a hand-computed 5-item example and verify it passes
- [ ] 3.4 Score first-occurrence steps of the test sessions and implement the bigram baseline; verify `eval_next_command.json` holds precision@{1,5,10} for both methods with the same step count

## 4. Skill potency — `skill-potency`

- [ ] 4.1 Compute the per-load shift (with vs without the load in the history) and follow-through within N=10; verify on 3 hand-traced loads that the shift's sign and the followed flag match manual inspection
- [ ] 4.2 Rank skills with the ≥5-load threshold and run the grouped-by-skill check of shift vs follow-through; verify `potency.csv` has load counts and follow rates, and that skills below the threshold appear only in the insufficient-data list
- [ ] 4.3 Generate `potency.png` (skills ranked by shift) and `summary.md` with the three headline numbers; verify both exist and the summary uses the wording "agreement with prescribed action"

## 5. Integration

- [ ] 5.1 Run stages 1→3 end to end from a clean output directory and verify they finish without manual steps, producing the chart and summary by 20:00

## Workflow follow-up

- Review the outputs with the team before demo; archive the change with `/opsx:archive` afterwards.
