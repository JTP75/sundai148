# Proposal

## Why

Agents often load a skill (SKILL.md) and then ignore it, and nothing measures how often that happens. Sundai Hack 148's theme is "predict the next action," and the sponsor's model (Unbox AI's BehaviorGPT-v4) ranks the next action from a history, on catalogs it has never seen. Pointed at an agent's own tool-call history, the model gives us a measure of skill influence without labels: after a skill loads, how much more likely does the skill's prescribed command become? That question uses the sponsor's stack directly, which the earlier static-feature + LightGBM framing did not.

## What Changes

- New offline pipeline that reads the agent session log (`~/.hermes/state.db` on pacel-orin: 1,323 sessions, 252 `skill_view` loads across 68 skills). It emits:
  - a **command catalog**: normalized command signatures (e.g. `git rebase`), in the 15-column BehaviorGPT catalog format, text-only (no images);
  - **behavior histories**: each session's tool calls mapped onto BehaviorGPT events by meaning (commands → `View`, search queries → `Search`, skill loads → `View(ExternalItem)`);
  - **skill-load events**, each paired with the command(s) its SKILL.md prescribes.
- Scoring through the BehaviorGPT Python SDK. Per scored step: the rank, probability and excess surprisal of the command actually run, computed with the same method as Unbox's `behaviorgpt-anomaly`.
- Two evaluation outputs for the final demo:
  1. **Next-command prediction**: precision@k for BehaviorGPT against a session n-gram baseline, on a temporal split, scoring first occurrences only.
  2. **Skill potency**: per skill, the shift in the prescribed command's probability after the load compared with just before it, ranked to surface "loaded but inert" skills.
- One chart and three headline numbers by 20:00 on 2026-11-08.

Out of scope: training or fine-tuning any model; the static SKILL.md feature model (an optional ablation at most); any live or online integration; changing the skills themselves.

## Capabilities

### New Capabilities
- `agent-trace-extraction`: turns agent session logs into a BehaviorGPT command catalog, event histories, and skill-load records with prescribed commands, all split by time.
- `behavior-scoring`: scores agent steps against BehaviorGPT rankings (rank, probability, excess surprisal) and evaluates next-command prediction against a baseline.
- `skill-potency`: measures and ranks each skill's effect on whether its prescribed command follows the load.

### Modified Capabilities
<!-- none: no existing specs in this project -->

## Impact

- **Dependencies**: `behaviorgpt` Python SDK (≥0.10 for `ExternalItem`), Python ≥3.11, pyarrow/pandas. Needs an Unbox AI API key in `UNBOXAI_API_KEY`; the free key comes from portal.unboxai.com.
- **External service**: the command catalog (command signatures only, no arguments with secrets or paths) is uploaded to Unbox AI and uses 1 of the 2 catalog slots on the key.
- **Data**: reads the private `state.db` read-only. The extractor runs on pacel-orin, and only derived artifacts are copied to the Mac.
- **Risks**: noisy command matching; BehaviorGPT deliberately ranks repeated items low; only ~3.7 loads per skill on average (252/68), so potency is reported only for skills with enough loads.
