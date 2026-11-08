# Proposal

## Why

Agents often load a skill (SKILL.md) and then ignore it, and nothing measures how often that happens. Raw follow-through ("did the prescribed command run after the load?") is a misleading measure. It rewards skills that prescribe what the agent would do anyway: common commands (`git status`, `python`), public CLIs the model knows from pretraining, and habits the agent already has. Measured that way, potency becomes a popularity metric. Hermes makes this worse: about 72 of its skills are agent-created, distilled from the agent's own past trajectories, so they match its past behavior by construction.

The hack theme is "predict the next action." We use a next-action model as the **counterfactual**: what would the agent have done without the skill? A skill's potency is its **lift** over that expectation, with controls that separate "the skill taught something" from "the agent already knew this." An earlier draft scored BehaviorGPT's own log-prob shift with vs without the load. That was dropped as the core metric: the shift reflects how the model relates the skill's name to command names, not what the agent does. BehaviorGPT stays an optional, pluggable expectation model.

## What Changes

- An offline extractor for the Hermes session log (`~/.hermes/state.db` on pacel-orin: ~1,325 sessions, 254 `skill_view` loads across 68 skills). It emits:
  - normalized command signatures per tool call (e.g. `terminal: git rebase`);
  - ordered session histories;
  - skill-load records with the prescribed command set **from the skill version in force at load time**, the load trigger (prompt-instructed or agent-chosen), and a maintenance-load flag;
  - no-load windows used as controls;
  - per-skill provenance (`created_at`, `created_by`) and curator-ledger patch history.
- An **expectation model**: P(command c runs within the next N calls | context), trained on train-period no-load windows only, with a calibration/AUC report and a popularity-only baseline.
- **Skill potency** = shrunken mean per-load lift (observed adherence − expected adherence), with these controls:
  - specificity weighting that drops generic commands;
  - in-session placebo skills;
  - familiarity strata (novel/occasional/habitual × public/local CLI);
  - a check that potency does not just track load count.
- Natural experiments as stretch goals:
  - pre/post skill creation on the same recurring task;
  - edit-response to curator patches;
  - prompt-instructed vs agent-chosen loads.
- One chart and three headline numbers by 20:00 on 2026-11-08:
  1. median lift on novel+local prescribed commands;
  2. agent-created vs hand-written skill lift;
  3. count of ranked skills whose lift CI includes or is below 0.

Out of scope: training or fine-tuning a large model; any live or online integration; changing the skills themselves; re-running agents. BehaviorGPT is optional (stretch only), not a dependency.

## Capabilities

### New Capabilities
- `agent-trace-extraction`: turns agent session logs into signatures, histories, load records (versioned prescribed sets, trigger, maintenance flag), no-load control windows and skill provenance, all split by time.
- `adherence-expectation`: predicts which commands the agent would run without a given skill, and reports how well that prediction works, including against popularity.
- `skill-potency`: measures each skill's lift over expectation with in-distribution and popularity controls, and ranks skills.

### Modified Capabilities
<!-- none: no existing specs in this project -->

## Impact

- **Dependencies**: Python ≥3.11, pyarrow/pandas, numpy, scikit-learn (logistic model), matplotlib. Optional: the `behaviorgpt` SDK and an `UNBOXAI_API_KEY`, only for the stretch alternative expectation model.
- **External service**: none on the critical path. If the BehaviorGPT stretch runs, only command signatures (no arguments) are uploaded.
- **Data**: reads the private `state.db`, `~/.hermes/skills/.usage.json` and `.curator_ledger.jsonl` read-only on pacel-orin. Only derived artifacts leave the machine. Provenance, ledger and cron-job fields come from the parallel data-extraction session.
- **Risks**:
  - Skill loads are endogenous: the agent loads a skill when it intends the task, so lift is adjusted association, not a causal effect. Only the natural experiments approach causality.
  - Few loads per skill (~3.7 mean).
  - Prescribed-command matching is noisy.
  - Skill versions at load time may be only partly recoverable.
