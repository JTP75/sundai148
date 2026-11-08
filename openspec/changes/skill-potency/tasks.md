# Tasks

Each group lists its owner. "Orch" is the orchestrating session. "W1"–"W5" are Qwen Code workers, each in its own Orca worktree and owning only the paths listed in design D19. "Data" is the data session. "Justin" is the human reviewer. Workers land work through PRs, and only Orch ticks boxes here, at merge time.

## 0. Data gathering (Data): `corpus-intake`

- [x] 0.1 Find public corpora; result: `swechat-v1` is primary (design Context); Entire.io and SWE-chat v2 are future
- [x] 0.2 Answer the Hermes open questions: the ledger is hash-only, `skill_manage` coverage is partial, cron jobs preload skills, and there is no cron job id (design Context, D14, D15)
- [ ] 0.3 After W1 merges: run `extract`, `census`, `draft_rules` and `bundle` on orin; the census reports scorable loads, cluster keys, version-source coverage, preload mapping and the instructed count
- [ ] 0.4 Gate: review both censuses and record any decisions in design.md before real-data scoring (group 7)

## 1. Foundation (Orch, before fan-out)

- [ ] 1.1 `requirements.txt` (pinned, wheels on all three OSes, includes pytest), `pyproject.toml`, `.gitattributes`, and `.gitignore` entries for `.orch/`, `data/` and `derived-*.zip`
- [ ] 1.2 `potency/` package skeleton with a `python -m` stub and `--help` for every D11 stage
- [ ] 1.3 `potency/schema.py` (every table, column, type, enum, status, reason code, version source, trigger and `cluster_key`) and `potency/io.py` (utf-8 JSONL/CSV, sorted keys, fixed float format, SHA-256 helpers)
- [ ] 1.4 `potency/normalize.py` (D1) with tests for every normalization scenario
- [ ] 1.5 `tests/make_fixtures.py` (seed 148): the synthetic corpus plus golden intermediates (`golden/evidence.csv`, `golden/expected.csv`, `golden/potency_expect.json`), `tests/fixtures/claude_code_sample/` and `tests/fixtures/hermes_sample.py`
- [ ] 1.6 Shared venv at `~/.venvs/sundai148`; `pytest` passes and the fixtures regenerate byte-identically

## 2. Hermes source stages (W1): `corpus-intake`, `agent-trace-extraction`

- [ ] 2.1 `potency/adapters/hermes.py`. Covers:
  - one read transaction against a `mode=ro` source;
  - ordering, request/result join, successful loads, `same_batch` and command-attempt status;
  - maintenance and repeat flags, trigger labels (on-machine prompt scan), window flags, no-load windows;
  - task key and cluster key, preload mapping;
  - version sources (`skill_manage` in both formats, ledger hash check, `version_core`);
  - provenance and agent-touched, temporal split.
- [ ] 2.2 `extract.py`, `census.py` (outcome-free), `draft_rules.py` (no skill text exported) and `bundle.py` (zip with a SHA-256 list), using only the standard library (enforced by a test)
- [ ] 2.3 `potency/privacy.py`: the allowlist check plus a regex backstop, run inside `extract` and `bundle`; tests prove that prompts, queries and arguments never appear

## 3. Claude Code adapter (W2): `corpus-intake`, `agent-trace-extraction`

- [ ] 3.1 `potency/adapters/claude_code.py` (D21):
  - `Skill` loads with variant name keys; `is_error` loads dropped;
  - `injected` versions, with `skill_listing` and `invoked_skills` excluded;
  - the `attributionSkill` hint;
  - `sessions.parquet` join for `repo_id`, user, model and version, so the cluster key is `repo_id`;
  - task key from a first-prompt hash.
- [ ] 3.2 `corpora.yaml` with entries for `swechat-v1` and `hermes-orin`; tests on `tests/fixtures/claude_code_sample/`

## 4. Evidence and expectation (W3): `adherence-evidence`, `adherence-expectation`

- [ ] 4.1 `potency/evidence.py`: the D18 status contract; output matches `golden/evidence.csv` on the fixtures
- [ ] 4.2 `potency/expect.py`. Covers:
  - per-corpus base rates, IDF weights and familiarity strata;
  - the model on train no-load windows, the popularity baseline, and a train-only vocabulary;
  - `expected.csv` (load × rule `p_hat`) and `expect_eval.json`.

## 5. Scoring and experiments (W4): `skill-potency`

- [ ] 5.1 `potency/score.py`:
  - A from evidence; lift; placebo lift (K=20, seed 148); avoid matches;
  - strata, shrinkage ranking, cluster-key bootstrap, supported marking;
  - the popularity check, the bloat stat and the sensitivity runs.
  
  On the golden inputs it reproduces `golden/potency_expect.json` (habit ≈ 0, novel > 0).
- [ ] 5.2 `potency/experiments.py`: pre/post creation, edit-response, paired-run validation and the trigger split, with "not computable" entries when inputs are missing

## 6. Report, platform and handover (W5): `skill-potency`, `adherence-evidence`, `cross-platform-runtime`

- [ ] 6.1 `potency/report.py` and `run_all.py`:
  - per corpus: `potency.png`, `status.png` and `summary.md`;
  - the three headline numbers;
  - the required caveats, disclosures and wording;
  - example rows per status, and the map appendix.
- [ ] 6.2 GitHub Actions matrix (ubuntu, macos, windows): pytest plus `run_all` on fixtures, with a cross-OS output hash comparison
- [ ] 6.3 `docs/runbook.md`: PowerShell and bash setup, bundle unpack and checksum verification, `run_all`, and the current task state

## 7. Integration and real data (Orch, Data, Justin)

- [ ] 7.1 Orch: review and merge W1–W5 (scope check plus full pytest on merged main); CI is green on all three OSes
- [ ] 7.2 Orch: run the Claude Code adapter on `swechat-v1` on pacel-pc, then census, draft_rules, evidence, expect, score and report
- [ ] 7.3 Data: run the Hermes source stages on orin and hand over the bundle
- [ ] 7.4 Justin: approve the rule maps and the public/local program map, and commit both (no skill text)
- [ ] 7.5 Orch: rerun with the approved maps, review outputs against the censuses, and fix issues through PRs
- [ ] 7.6 Kris reproduces `run_all` on Windows from the runbook and a shared bundle, with matching output hashes

## Workflow follow-up

- All changes land through PRs. Archive with `/opsx:archive` after the demo.
