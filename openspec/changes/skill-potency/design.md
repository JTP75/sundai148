# Design

## Context

- **Primary corpus, pacel-orin Hermes:**
  - `~/.hermes/state.db` (SQLite, live, WAL). `messages.tool_calls` holds a JSON list of `{function:{name,arguments}}` on assistant rows; `messages.tool_name` is set on result rows. `messages.timestamp` and `sessions.started_at` are epoch REALs. `sessions.source` is one of cron, telegram, auricle, subagent, cli, ...
  - Skill loads are `skill_view` calls with `arguments.name`.
  - Skill files live at `~/.hermes/skills/<category>/<skill>/SKILL.md`.
- **Census so far (data session, counts only):**
  - 254 loads, 68 skills, 10 skills with ≥5 raw loads.
  - Curator ledger: 391 rows from 2026-10-01 to 11-08 (curator 365, agent 26; patch 288, create 40, archive 38, write_file 24, delete 1).
  - `created_by` over the 68 loaded skills: null 42, agent 16, missing 7, learn 2, installed 1.
  - `state.db` holds 108 `skill_manage` calls, including edits from before the ledger existed.
- **Other corpora:**
  - OpenCode (44 loads), Claude Code (14), Qwen (5), Codex (0); all below the bar alone.
  - The data session is searching public web sources for more. The design is therefore multi-corpus (D12).
- **People and machines:**
  - Analysis runs on the Mac (Justin) until ~18:00, then on Kris's Windows machine until the 20:00 demo (D17).
  - Raw private logs never leave their source machine.

**The central threat is in-distribution adherence.** An agent runs `git status` or `curl` whether or not a skill says so. The underlying LLM knows public CLIs from pretraining. Agent-created and curator-patched skills restate the agent's own past behavior. Any metric based on "did the prescribed command follow" without a counterfactual therefore measures popularity and familiarity, not skill influence. Every decision below serves to separate the two.

## Goals / Non-Goals

**Goals:**
- One command per stage, end to end, with deterministic outputs that are identical on Windows, macOS and Linux.
- A per-rule evidence layer (D18) that is a complete demo on its own, with lift and ranking built on top.
- The headline number stays honest when a skill only prescribes what the agent already does: lift ≈ 0 in that case.
- New corpora plug in through an adapter without changes to analysis code.

**Non-Goals:**
- No web app or UI. The output is a chart plus a markdown summary.
- No tuning of N, K, thresholds or strata cutoffs after any adherence number is seen. Census counts may inform decisions because they contain no outcomes.
- No causal claims from the observational lift alone, and no usefulness, quality or pruning recommendations.
- No exhaustive shell parsing and no fitted cross-skill predictor.

## Decisions

**D1. Signature granularity = tool + program + subcommand(s).**
- Examples: `terminal: git rebase`, `terminal: gh pr create`, `terminal: gog tasks list`, `read_file`.
- A fixed known-CLI list (gh, gog, gcloud, docker, kubectl, hermes, ...) keeps up to two subcommand levels. Other programs keep one.
- Flags and arguments are dropped.
- Compound commands (`a && b`, pipes) yield one signature per segment.
- Rejected alternatives: tool family only (too coarse) and full flags (too sparse).

**D2. Estimand = lift, not follow-through.** For a load L of skill s at step t: `lift(L) = A(L) − Â(L)`.
- `A(L)` is observed adherence: the specificity-weighted (D4) share of s's **required** prescribed commands (D13) attempted in steps t+1..t+N.
- `Â(L)` is the same quantity's expectation under the no-skill model (D3).
- Follow-through alone is reported only as context.
- No match means "no agreement observed," never "ignored."
- Rejected alternative: BehaviorGPT's log-prob shift with vs without the load. It measures the model's response to skill context (≈ text similarity + catalog popularity), not the agent.

**D3. Expectation model trained on no-load windows.** For each command c, the model predicts P(c ∈ next N steps | context).
- **Training rows:** train-period windows with no load (including preloads, D14) of any skill whose prescribed set contains c in the previous N steps.
- **Features:**
  - previous k=3 signatures (bag);
  - session source;
  - task key (D15) when available;
  - c's train base rate;
  - position in the session.
- **Model:** L2 logistic regression per command family, with a bigram-backoff fallback for rare commands. One model per corpus; base rates are not pooled across corpora.
- **Vocabulary:** train-only, with test OOV coverage reported. The model and the baselines share the same candidate universe and seen-item mask.
- **Quality, on test-period no-load windows:**
  - AUC, calibration and Brier score against a **popularity-only** baseline;
  - next-command **hit-rate@{1,5,10}** on first occurrences, overall and by frequency decile, with step and session counts.

  If the model does not beat popularity, the report says so, and Â is effectively the base rate.
- **Rejected alternatives:** BehaviorGPT as Â (a retail model; removed from the project) and an LLM judge (costly, and itself in-distribution).

**D4. Specificity weighting.**
- w(c) = −log(smoothed base rate of c in train no-load windows).
- Commands above a fixed base-rate ceiling (0.2 per window) are removed from prescribed sets.
- A skill whose set becomes empty is flagged `generic-only` and not ranked.

**D5. Placebo control.**
- For each load, draw K=20 other skills whose prescribed sets match in size (±1) and familiarity mix, using a fixed seed.
- `placebo_lift(L) = A(L) − mean A_placebo(L)` over the same window.
- A skill must be positive on both lift and placebo lift to count as having positive agreement beyond expectation.

**D6. Familiarity strata.** Each prescribed command gets two labels:
- **In-corpus familiarity:** its no-load base rate *before the skill's creation date* (or in train if unknown): novel (0), occasional (≤ 0.02), habitual (> 0.02).
- **Prior-knowledge proxy:** the program is **public** (known from pretraining) or **local**, from a hand map that Justin commits before adherence is computed (D13). Unmapped programs default to local.

Lift is reported per stratum and per corpus. **Novel + local** supplies headline number 1. For public corpora most skills are public, so the stratum split matters most there.

**D7. Natural experiments (in scope; each reports "not computable" when its inputs are missing).**
- **S1 Pre/post creation.** For skills with a creation date and a task key:
  - Compare the task's adherence to the skill's commands before vs after creation.
  - Use difference-in-differences against keyed tasks that never got a skill.
  - Split agent-touched vs none (D16).
- **S2 Edit-response.** For each recorded change that adds or removes a signature: does the command's post-load rate move in the matching direction, relative to unchanged commands in the same skill?
- **S3 Paired-run validation.** If a public corpus has paired runs with and without the skill, compare observational lift to the experimental difference on the same skills. This directly checks the endogeneity bias, and it is the most valuable of these analyses.
- **Trigger split.** Report lift separately for `instructed`, `chosen` and `preloaded` loads.

**D8. Event ordering and leakage guards.**
- **Ordering:**
  - Order by source sequence (message id, then position within `tool_calls`), with stable call ids.
  - Join each request to its result. A load counts only when its result is non-error.
  - Commands in the same assistant batch as the load are `same_batch` and excluded from attribution.
  - Shell steps are "command attempts," with exit status recorded when available.
  - Source offsets are kept separate from step offsets.
- **Windows:**
  - Truncated at session end, flagged `incomplete`.
  - Another skill load does not close a window; it is flagged `overlap`.
  - Sensitivity runs exclude both flags.
- **Skill version at load time (D14).**
- **Maintenance loads:** excluded when `skill_manage` or a write to the skill's files on the same skill follows within N steps.
- **First load per skill per session only.** Later loads stay in context.
- **Temporal split** by session start, ~70% train, per corpus. Base rates, IDF weights, strata, vocabulary and the expectation model use train only. Lift is computed over all-period loads and labeled exploratory.

**D9. Statistics and ranking (pre-registered, corpus-agnostic).**
- **Per-skill potency:** empirical-Bayes shrunken mean lift (normal-normal, prior fitted across skills within a corpus).
- **CIs:** 95%, from a bootstrap of 1,000 resamples grouped by session *and* task key.
- **Ranking:** every skill with ≥2 scorable loads is ranked. A skill is **supported** when it has ≥5 scorable loads *and* ≥3 independent sessions. An empty supported set is allowed.
- **Inconclusive:** a CI that spans 0 means "inconclusive," never "inert" or "prune."
- **Popularity check:** Spearman correlation of potency vs load count and vs the mean base rate of the prescribed set; |ρ| ≥ 0.5 is flagged.
- **Validation:** any predictive validation is grouped by skill, session and task key.

**D10. Fixed parameters (pre-registered).**

| Parameter | Value |
|---|---|
| Window N | 10 (sensitivity at 5 and 20, reported but not used for ranking) |
| Context k | 3 |
| Placebo K | 20, seed 148 |
| Base-rate ceiling | 0.2 |
| Familiarity cutoffs | 0 / 0.02 |
| Ranked / supported | ≥2 loads / ≥5 loads and ≥3 sessions |
| Train share | ~70% per corpus |
| Bootstrap | 1,000 resamples, seed 148 |

All are fixed before any adherence number is computed.

**D11. Runtime layout.**
- **Per corpus, on the source machine**, stdlib only, so orin needs no installs:
  - `python -m potency.extract --corpus <name> --out <dir>` writes the intermediate format (D12) and `manifest.json`;
  - `python -m potency.census --corpus <name> --out <dir>` writes `census.json`;
  - `python -m potency.draft_rules --corpus <name> --out <dir>` writes the draft rule map (D13).
- `python -m potency.bundle --in <dir> --out <zip>` packs derived files, `manifest.json` and a SHA-256 list into `derived-<corpus>-<manifest hash>.zip`. Justin shares the zip through Google Drive. Kris unzips it into the data dir (`Expand-Archive` on Windows).
- **Anywhere, on derived files only:**
  - `python -m potency.evidence` writes `evidence.csv` (D18);
  - `python -m potency.expect` writes `expect_eval.json`;
  - `python -m potency.score` writes `potency.csv`, `strata.csv` and `experiments.json`;
  - `python -m potency.report` writes `potency.png`, `status.png` and `summary.md`;
  - `python -m potency.run_all` runs evidence → expect → score → report.
- The data session runs the source-machine stages. Raw logs and skill text never leave the source machine.

**D12. Multi-corpus intake through a harness-neutral intermediate format.**
- Each corpus has an adapter that emits the same tables, as utf-8 JSONL (stdlib-writable on source machines):
  - `steps` (corpus, session, step, source offset, signature, kind, status, batch id);
  - `loads` (skill, step, trigger, flags, version id);
  - `skill_versions` (skill, version id, valid-from, prescribed set with roles, version source);
  - `provenance` (skill, creation date, created_by, agent-touched, change list);
  - `sessions` (corpus, session, start, source, task key, split).
- A `corpora.yaml` registry records each corpus's harness, model(s), date range, privacy class, and license/URL.
- **Privacy classes:**
  - *Private:* only allowlisted fields are exported (signatures, skill names, booleans, hashes, counts, timestamps). Query text, descriptions, prompts and arguments are never exported, and sanitization runs on the source machine.
  - *Public:* text is allowed; the license is recorded.
- **Consistent snapshot:** each SQLite source is read in one read transaction (`mode=ro`). `manifest.json` records max row ids, max timestamp, row counts, cutoff and the extractor git sha. This replaces the "mtime unchanged" check, since other writers change mtime on a live WAL database.
- **Census before analysis:** counts per corpus only, with **no adherence, follow-through or lift**. It reports:
  - raw and scorable loads per skill;
  - independent sessions;
  - exclusion reasons;
  - version-source coverage;
  - task-key coverage;
  - trigger counts;
  - the program frequency list.
- **Eligibility bar:** ≥100 loads and ≥10 skills with ≥5 loads, *or* paired with/without-skill runs. Smaller corpora are reported but not ranked on their own.

**D13. Rule map: agent-drafted, Justin-approved.**
- **Drafting:** an agent on the source machine drafts a rule map from each loaded skill's versioned text. Skill text stays there; the map holds only signatures, tool names, labels and short rule ids. Each rule carries:
  - `rule_id`;
  - skill and version id;
  - instruction location (section heading index);
  - obligation type: `required`, `conditional`, `optional`, `example` or `avoid`;
  - applicability predicate: observable context signatures or task key, or `unknown`;
  - observable predicate: a set of acceptable signatures;
  - allowed alternatives.
- **Approval:** Justin reviews and edits the map, and approval is recorded in the map file. It is committed before any adherence is computed, together with the public/local program map.
- **Counting:** only approved `required` rules, and `conditional` rules whose applicability holds, count toward A. `avoid` matches are reported separately. `optional` and `example` rules are not scored.
- **Unaudited skills:** if a skill has no approved map, auto-extraction from code blocks and inline backticks applies. Every command is `required` with applicability `unknown`, and the skill is flagged `auto`.
- **Prose skills:** the map may use tool names (e.g. `web_search`) as observable predicates.

**D14. Skill version at load time.** Version sources, in priority order:
1. Ledger replay, when `before`/`after` hold full text.
2. Replay of `skill_manage` calls in `state.db`. This covers edits from before 2026-10-01.
3. Otherwise, the **stable core**: commands present in both the earliest known and the current version, flagged `version_core`. It removes later-added commands (the reverse-causality risk) without dropping the load.

A load is `version_unknown` and excluded only when none of the three works.

**Preloads:** if Hermes preloads skills (cron config, system prompt) without `skill_view`, and the preload is detectable, it is a load at step 0 with trigger `preloaded`. If it is not detectable, it is a documented blind spot, and sessions of jobs suspected of preloading are excluded from no-load controls.

**D15. Task key.** Fallback chain:
1. cron job id;
2. hash of the normalized first user/cron prompt (digits and dates stripped), computed on the source machine with only the hash exported;
3. none.

Without a key, S1 is "not computable" for that corpus.

**D16. Provenance grouping.**
- **Agent-touched:** `created_by` ∈ {agent, learn}, or any ledger create, patch or write_file by `agent` or `curator` (the curator is automated). On orin this is 34 skills and 160 loads, vs 34 skills and 94 loads with no agent trace.
- Headline 2 compares agent-touched vs none. `created_by` alone is a secondary split.
- Supporting stat (bloat): the share of agent-touched skills never loaded, and loaded but never supported. It is computed from the census.

**D17. Cross-platform runtime (Windows, macOS, Linux).**
- **Python and packaging:**
  - Pure Python ≥3.11. Dependencies are pinned in `requirements.txt` and limited to wheels available on all three OSes (pandas, numpy, scikit-learn, matplotlib with the Agg backend, pyyaml). Source-machine stages use the stdlib only.
- **Entry points and paths:**
  - Every stage runs as `python -m potency.<stage>`. No bash/Makefile is required; any shell helper is optional.
  - Paths use `pathlib`. There are no hard-coded `~/` or `/tmp` paths; output and data dirs come from CLI args or `POTENCY_DATA_DIR`. No symlinks.
- **File I/O:**
  - Every text open sets `encoding="utf-8"` and `newline=""` where relevant, and outputs use `\n`.
  - `.gitattributes` sets `* text=auto eol=lf`, so CRLF never corrupts JSONL/CSV.
- **Determinism and source access:**
  - Seeded RNG, sorted iteration and fixed float formatting, so outputs match byte for byte across OSes (verified by hash).
  - Source extractors run on the source machine. Analysis stages need only derived files and no SSH, so Windows needs neither SSH nor WSL.
- **Verification:** a GitHub Actions matrix (ubuntu, macos, windows) runs unit tests and the synthetic end-to-end run on each push.

**D18. Evidence layer and status contract (hybrid with the model-free audit in `docs/research/adversarial-spec-review.md`).** Each (scorable load × rule) pair becomes one row in `evidence.csv` with one status:
- `supported_agreement`: the rule's observable predicate (or an allowed alternative) was attempted within the window after a successful load.
- `no_observed_agreement`: applicability is known to hold, the window is intact (not `incomplete`), and no matching step was found. It means only that; it never means "ignored."
- `insufficient_evidence`: applicability is unknown, the version is `version_core` and the rule is not in the core, ordering is ambiguous (`same_batch`), the window is incomplete, or the rule is unsupported.
- `not_applicable`: the applicability predicate is known to be false. These rows are excluded from denominators.

Each row carries: pseudonymous episode id, corpus, skill, version id, rule id, window bounds, status, reason code, and the step ids of the matching evidence. Unknown is never mapped to failure.

A is computed only from `supported_agreement` and `no_observed_agreement` rows. Lift and ranking (D2, D9) build on this layer. **Fallback demo:** if the expectation model or support fails, the evidence table and the per-skill status chart are the demo.

**D19. Module layout and worker contracts (for the parallel build).**
- **Package layout:**

| Module | Purpose |
|---|---|
| `potency/schema.py` | Single source of truth for table columns, types and enums |
| `potency/io.py` | utf-8 JSONL/CSV read and write, deterministic float formatting, sorted keys |
| `potency/normalize.py` | D1 signature normalizer |
| `potency/adapters/hermes.py` | Hermes corpus adapter |
| `potency/adapters/<public>.py` | One adapter per public corpus |
| `potency/extract.py`, `census.py`, `draft_rules.py`, `bundle.py` | Source-machine stages |
| `potency/evidence.py` | D18 evidence layer |
| `potency/expect.py` | D3 expectation model |
| `potency/score.py` | D2, D4–D7, D9 |
| `potency/report.py` | Charts and summary |
| `potency/run_all.py` | Runs the analysis stages in order |
| `tests/fixtures/synthetic/` | Generated by `tests/make_fixtures.py`, seed 148 |

- **Ownership:** `schema.py`, `io.py` and the synthetic fixtures are built first, by the orchestrator, and frozen. Each worker owns one module group plus its tests, and changes the shared modules only through the orchestrator.
- **Fixtures:** the synthetic corpus encodes every evidence-status case, plus a "habit" skill and a "novel" skill with known expected lift. Each module's tests pass against it on its own.
- **Interfaces:** every stage reads and writes only the D12 tables and named output files in a data dir. There are no in-memory cross-module calls except into `schema`, `io` and `normalize`.

**D20. Claims.**
- **Supported:**
  - "for this version, episode and rule, these trace events support agreement";
  - "no matching evidence in the declared applicable window";
  - "evidence is insufficient";
  - lift over expected adherence, as an upper bound;
  - descriptive counts.
- **Not supported:**
  - skill quality or usefulness;
  - causal influence beyond D7;
  - task success;
  - "ignored";
  - whole-procedure compliance;
  - overlooked skills (the audit covers only loaded episodes, a selection-biased sample);
  - deletion or pruning recommendations.

## Risks / Trade-offs

- [Loads are endogenous: the agent loads a skill when it already intends the task] → Â conditions on context but can't see intent, so lift is an upper bound. Say so in the summary, and rely on S1, S2, S3 and the trigger split for causal claims.
- [Reverse causality through skill patches] → D14 version sources, with the stable core as fallback.
- [Sparse support] → shrinkage, ranking from ≥2 loads with a "supported" mark, an empty supported set allowed, and more corpora through D12.
- [Strata get thin] → report counts per stratum, pool to novel+local vs rest if any cell has < 10 loads.
- [The audit maps are subjective] → committed before results and listed in the summary appendix.
- [The expectation model doesn't beat popularity] → report it; lift is then "above base rate," which is still the popularity-corrected quantity.
- [Prescribed-command extraction is noisy] → hand audit for top skills, `auto` flag elsewhere, same normalizer on both sides.
- [A secret leaks into derived files] → field allowlist, sanitization at the source, and a regex scan as a backstop (not a guarantee).
- [Mixed corpora differ in harness and model] → per-corpus models and strata; skills are ranked within a corpus and never pooled across corpora.
- [Platform drift during the 18:00 handover] → CI matrix, byte-identical outputs on synthetic data, and a handover runbook in `docs/`.

## Open Questions

- Do the ledger's `before`/`after` fields hold full text, diffs or nothing? Answered by the census; it decides D14 source 1.
- Does Hermes preload skills for cron jobs? The data session is checking source and config.
- What is the task-key coverage under D15? Answered by the census.
- Which public corpora qualify, and do any have paired with/without-skill runs? The data session is searching.
