# Design

## Context

- The data is on pacel-orin:
  - `~/.hermes/state.db` (SQLite). `messages.tool_calls` holds a JSON list of `{function:{name,arguments}}` on assistant rows. `messages.timestamp` and `sessions.started_at` are epoch REALs. `sessions.source` is one of cron, telegram, auricle, subagent, cli, ...
  - Skill loads are `skill_view` calls with `arguments.name`.
  - Skill files live at `~/.hermes/skills/<category>/<skill>/SKILL.md`.
  - Provenance is in `.usage.json`: `created_by` (agent 72, learn 5, installed 1, null 114; an opt-in flag, not proof of authorship), `created_at` and `patch_count`.
  - `.curator_ledger.jsonl` has `ts`, `actor`, `action`, `skill`, `before`, `after`.
- The Mac has only derived files. A parallel session is extracting the data.
- The time box ends at 20:00 on 2026-11-08.

**The central threat is in-distribution adherence.** An agent runs `git status` or `curl` whether or not a skill says so. The underlying LLM knows public CLIs from pretraining. Agent-created skills restate the agent's own past behavior. Any metric based on "did the prescribed command follow" without a counterfactual therefore measures popularity and familiarity, not skill influence. Every decision below serves to separate the two.

## Goals / Non-Goals

**Goals:**
- One command per stage, end to end, with deterministic outputs.
- The headline number stays honest when a skill only prescribes what the agent already does: lift ≈ 0 in that case.

**Non-Goals:**
- No web app or UI. The output is a chart plus a markdown summary.
- No tuning of N, K, thresholds or strata cutoffs after seeing test results.
- No causal claims from the observational lift alone.

## Decisions

**D1. Signature granularity = tool + program + subcommand.** Examples: `terminal: git rebase`, `terminal: pytest`, `read_file`. Specific enough for skills to prescribe, coarse enough to repeat across sessions. Flags and arguments are dropped. Alternatives rejected: tool family only (too coarse) and full flags (too sparse).

**D2. Estimand = lift, not follow-through.** For a load L of skill s at position t: `lift(L) = A(L) − Â(L)`.
- `A(L)` is observed adherence: the specificity-weighted (D4) share of s's prescribed set run in calls t+1..t+N.
- `Â(L)` is the same quantity's expectation under the no-skill model (D3).

Follow-through alone is reported only as context. Alternative rejected: BehaviorGPT's log-prob shift with vs without the load. It measures the model's sense of how the skill's name relates to command names (≈ text similarity + catalog popularity), not the agent.

**D3. Expectation model trained on no-load windows.** For each command c, the model predicts P(c ∈ next N calls | context).
- Training rows: train-period windows with no load of any skill whose prescribed set contains c in the previous N calls.
- Features: previous k=3 signatures (bag), session source, cron job key (job id or normalized title when available), c's train base rate, and position in the session.
- Model: L2 logistic regression per command family with a bigram-backoff fallback for rare commands. Kept small, as n is small.
- Quality: AUC, a calibration curve and Brier score on test-period no-load windows, against a **popularity-only** baseline (base rate alone). If the model does not beat popularity, the report says so, and Â is then effectively the base rate.

Alternatives: BehaviorGPT as Â (stretch S3, same interface); an LLM judge (rejected: costly and itself in-distribution).

**D4. Specificity weighting.** w(c) = −log(base rate of c in train no-load windows), smoothed. Commands with a base rate above a fixed ceiling (0.2 per window) are removed from prescribed sets: `ls`, `cat`, `cd`, `git status`, `python` and similar. A skill whose set becomes empty is flagged "generic-only" and not ranked. This stops skills scoring by prescribing ubiquitous commands.

**D5. Placebo control.** For each load, draw K=20 other skills whose prescribed sets match in size (±1) and familiarity mix. Compute their A over the same window. `placebo_lift(L) = A(L) − mean A_placebo(L)`.
- This removes "the agent does a lot after any load."
- It is reported alongside D2 lift. A skill must be positive on both to count as potent.

**D6. Familiarity strata.** Each prescribed command gets two labels:
- **In-corpus familiarity:** its no-load base rate *before the skill's `created_at`* (or in train if unknown): novel (0), occasional (≤ 0.02), habitual (> 0.02).
- **Prior-knowledge proxy:** program is **public** (git, gh, curl, docker, python, npm, …: known from pretraining) or **local** (gog, hermes, user scripts, repo-specific CLIs). Taken from a hand-written map over the top programs; unmapped programs default to local.

Lift is reported per stratum. **Novel + local** is the cleanest "skill taught something" signal and supplies headline number 1.

**D7. Natural experiments (stretch, in order).**
- **S1 Pre/post creation.** For skills with `created_at` and a recurring task key (cron job): compare that task's adherence to the skill's commands before vs after creation. Use difference-in-differences against recurring tasks that never got a skill. Split agent-created vs hand-written (headline 2). Hypothesis: agent-created skills show high follow-through but ~0 pre/post change.
- **S2 Edit-response.** For each ledger patch that adds or removes a command signature: does the command's rate after loads rise (added) or fall (removed) after the patch, relative to unchanged commands in the same skill? Popularity cannot explain this.
- **Load trigger split.** Loads named in the user/cron prompt (closer to exogenous) vs loads the agent chose (endogenous intent). Report lift for each.

**D8. Leakage guards.**
- **Skill version at load time.** Rebuild each skill's text at load time by replaying ledger `before`/`after`. The current SKILL.md can contain commands added *because* the agent ran them, which would inflate adherence through reverse causality. If a version can't be rebuilt, score only loads after the last patch and flag the rest.
- **Maintenance loads.** Exclude loads followed by `skill_manage` (or writes to the skill's file) on the same skill within N calls.
- **First load per skill per session** only. Later loads stay in context.
- **Temporal split** by session start, ~70% train. Base rates, IDF weights, strata and the expectation model use train only.

**D9. Statistics.**
- Per-skill potency = empirical-Bayes shrunken mean lift (normal-normal, prior fitted across skills), ranked on posterior means.
- 95% CIs come from a session-level bootstrap (1,000 resamples).
- Support threshold: ≥5 scorable loads to be ranked. Others go to an "insufficient data" list.
- **Popularity check:** Spearman correlation of potency vs load count and vs mean base rate of the prescribed set. A strong correlation is flagged in the summary.
- Any predictive validation is grouped by skill.

**D10. Fixed parameters (pre-registered).**

| Parameter | Value |
|---|---|
| Window N | 10 (sensitivity at 5 and 20, reported but not used for ranking) |
| Context k | 3 |
| Placebo K | 20 |
| Base-rate ceiling | 0.2 |
| Familiarity cutoffs | 0 / 0.02 |
| Support threshold | 5 |
| Train share | ~70% |

All are fixed before any test result is viewed.

**D11. Runtime layout.**
- `extract.py` runs on pacel-orin (stdlib + pyarrow). It writes `signatures.parquet`, `histories.jsonl`, `skill_loads.jsonl`, `skill_versions.jsonl`, `provenance.json` and `windows.parquet`, all derived with no raw text.
- `expect.py` fits D3 and writes `expect_eval.json`.
- `potency.py` computes D2 and D4–D9 and writes `potency.csv` and `strata.csv`.
- `report.py` writes `potency.png` and `summary.md`.
- Optional `bgpt_expect.py` is the S3 alternative Â behind the same interface.

## Risks / Trade-offs

- [Loads are endogenous: the agent loads a skill when it already intends the task] → Â conditions on context but can't see intent, so lift is an upper bound on skill influence. Say so in the summary, and lean on S1, S2 and the trigger split for causal claims.
- [Reverse causality through skill patches] → D8 version replay, with post-last-patch fallback.
- [Strata get thin with ~254 loads] → report counts per stratum, pool to the two-way split (novel+local vs rest) if any cell has < 10 loads, and use shrinkage.
- [The public/local map is subjective] → fixed hand map committed before results, listed in the appendix of the summary.
- [The expectation model doesn't beat popularity] → report it; lift then reduces to "above base rate," which is still the popularity-corrected quantity we want.
- [Prescribed-command extraction from SKILL.md is noisy] → same normalizer on both sides, hand-check 10 skills, flag empty or generic-only sets.
- [A secret leaks into derived files] → signatures drop all arguments; regex-scan outputs for tokens, URLs and paths.

## Open Questions

- Is there a stable cron job key (job id or prompt hash) per cron session? S1 and the D3 features need it. The data session is checking.
- Does `.curator_ledger.jsonl` on orin hold full `before`/`after` SKILL.md text, or only diffs or metadata? This decides whether D8 can replay versions.
- How do prompt-instructed loads show up? Does the skill name appear in the user/cron message, or does Hermes preload skills for cron jobs without a `skill_view` call? Preloads would be loads we can't observe.
