# Proposal

## Why

Agents often load a skill (SKILL.md) and then ignore it, and nothing measures how often that happens. Raw follow-through ("did the prescribed command run after the load?") is a misleading measure. It rewards skills that prescribe what the agent would do anyway: common commands (`git status`, `python`), public CLIs the model knows from pretraining, and habits the agent already has. Measured that way, potency becomes a popularity metric. Hermes makes this worse: many of its skills are created or patched by the agent and its automated curator, distilled from the agent's own past trajectories, so they match past behavior by construction.

The hack theme is "predict the next action." We use a next-action model as the **counterfactual**: what would the agent have done without the skill? A skill's potency is its **lift** over that expectation, with controls that separate "the skill taught something" from "the agent already knew this." The earlier draft scored BehaviorGPT's log-prob shift with vs without the load. That measured the model's response to skill context, not the agent (see `docs/research/adversarial-spec-review.md`), so it was dropped as the core metric. BehaviorGPT stays an optional, pluggable expectation model.

## What Changes

- **Data intake as part of the pipeline.** Adapters turn any harness's logs into one intermediate format. The Hermes corpus on pacel-orin comes first, then OpenCode and public corpora the data session finds. The intake includes:
  - a corpus registry;
  - privacy classes, with a field allowlist for private logs;
  - consistent read-only snapshots with manifests;
  - an outcome-free census that gates analysis.
- **Extraction:**
  - nested-subcommand signatures;
  - stable ordering, with only successful loads counted;
  - same-batch, overlap and incomplete-window flags;
  - prescribed sets from the skill version in force at load time (ledger replay, then `skill_manage` replay, then the stable core);
  - hand-audited prescription roles (required/example/avoid);
  - trigger labels (preloaded/instructed/chosen), task keys and provenance.
- **Expectation model:** P(command c within the next N steps | context), fitted per corpus on train-period no-load windows. It is evaluated against a popularity-only baseline with hit-rate@k, calibration and OOV coverage.
- **Skill potency:** shrunken per-skill lift (observed − expected adherence) within each corpus, with these controls:
  - specificity weighting;
  - placebo skills;
  - familiarity strata (novel/occasional/habitual × public/local);
  - a popularity check;
  - resampling grouped by session and task.

  Every skill with ≥2 loads is ranked, and skills with ≥5 loads in ≥3 sessions are marked supported. An empty supported set is a valid outcome.
- **Natural experiments (stretch):**
  - pre/post skill creation;
  - edit-response;
  - validation against paired with/without-skill runs, if a public corpus has them;
  - the trigger split.
- **Cross-platform runtime:** analysis runs identically on Windows, macOS and Linux, with a CI matrix and a handover runbook (Kris on Windows takes over at about 18:00).
- One chart and three headline numbers by 20:00 on 2026-11-08:
  1. median lift on novel+local prescribed commands;
  2. agent-touched vs no-agent-trace skill lift;
  3. count of ranked skills whose lift CI includes or is below 0.

Out of scope:
- training large models;
- live integrations;
- changing skills;
- re-running agents;
- causal, usefulness or pruning claims beyond the natural experiments;
- exhaustive shell parsing;
- a fitted cross-skill predictor.

BehaviorGPT is optional (stretch only).

## Capabilities

### New Capabilities
- `corpus-intake`: registers corpora, extracts them into a harness-neutral format from consistent read-only snapshots, enforces the private-field allowlist, and produces the outcome-free census.
- `agent-trace-extraction`: turns one corpus's logs into ordered steps, versioned and audited prescribed sets, flagged loads, no-load windows, task keys and provenance, split by time.
- `adherence-expectation`: predicts which commands the agent would run without a given skill, and reports how well that beats popularity.
- `skill-potency`: measures and ranks each skill's lift over expectation with in-distribution and popularity controls.
- `cross-platform-runtime`: makes every analysis stage run identically on Windows, macOS and Linux.

### Modified Capabilities
<!-- none: no existing specs in this project -->

## Impact

- **Dependencies:** Python ≥3.11. Pinned pandas, pyarrow, numpy, scikit-learn, matplotlib (Agg backend) and pyyaml, all with wheels for Windows, macOS and Linux. Optional: the `behaviorgpt` SDK and `UNBOXAI_API_KEY`, for stretch only.
- **External services:** none on the critical path. GitHub Actions runs the CI matrix.
- **Data:** private sources (`~/.hermes/state.db`, `.usage.json`, `.curator_ledger.jsonl` on pacel-orin) are read read-only on their machine, and only allowlisted derived fields leave it. Public corpora are used under their recorded licenses.
- **People:** the data session runs intake and the census. Justin commits the audit maps before adherence is computed. Kris takes over on Windows at about 18:00.
- **Risks:**
  - Loads are endogenous, so lift is an upper bound.
  - Support is sparse (only 10 Hermes skills have ≥5 raw loads).
  - Skill versions before 2026-10-01 are only partly recoverable.
  - Corpora differ in harness and model, so ranking happens within a corpus.
