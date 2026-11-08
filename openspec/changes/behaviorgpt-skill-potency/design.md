# Design

## Context

- The data is on pacel-orin: `~/.hermes/state.db` (SQLite), with tool calls in a `tool_calls` field on messages. Skill loads appear as `skill_view` calls. The Mac has only derived files.
- BehaviorGPT, per the Unbox docs (`portal.unboxai.com/llms.txt`, SDK README, `docs/catalog-format.md`, `docs/catalogs.md`, `behaviorgpt-anomaly` README):
  - histories hold only three event types: `Search(query)`, `View(item)`, `Order([items])`;
  - `complete` predicts the next **view**;
  - items are embedded from `name`/`brand`/`categories` (plus image, price);
  - the model ranks already-seen items low on purpose;
  - a catalog holds ≤100k items and a key holds 2 catalogs;
  - an embed takes minutes;
  - `ExternalItem` puts an item that is in no catalog into a history (SDK ≥0.10);
  - an all-null `image_url` is allowed (the "minimum viable catalog").
- The time box is about 9 hours, ending 20:00 on 2026-11-08.

## Goals / Non-Goals

**Goals:**
- Run the whole pipeline end to end with one command per stage, caching every API response so reruns cost nothing.
- Keep the method close enough to Unbox's anomaly detector that we can say "their mechanic, applied to agents."

**Non-Goals:**
- No web app or UI. The output is a chart plus a markdown summary.
- No tuning of τ, N, or the support threshold after seeing test results.

## Decisions

**D1. Commands are `View`s, not `Order`s.** `complete` predicts the next view, so the action we want to predict has to be a view. Alternative: map writes and commands to `Order` (the handoff's first draft). Rejected because the prediction would then target an event type we never score. `Order` is unused for now; a later version could use it for "commit/PR created" outcomes.

**D2. Signature granularity = tool + program + subcommand.** Examples: `terminal: git rebase`, `terminal: pytest`, `read_file`. This gives a catalog of a few hundred to a few thousand items, specific enough for skills to prescribe and coarse enough to repeat across sessions. Alternatives: tool family only (too coarse; every skill prescribes `terminal`), or full flags (too sparse). Flags go in `keywords`, not in the `id`.

**D3. Catalog rows are text-only, with meaning-bearing fields.** `name` = a readable signature ("git rebase"), `brand` = the program or tool family ("git"), `categories` = a coarse path ("Terminal, Version control"), plus a short description string in `name` when it adds meaning (e.g. "git rebase — rewrite commit history"). Descriptions come from a fixed hand-written map for the top programs, not from an LLM. `frequency` and `sales_since` come from training-period counts. `timestamp` = first use in the training period.

**D4. Skills enter histories as `View(ExternalItem(...))`, not as catalog items.** This keeps skills out of the ranked output and keeps both catalog slots free. `ExternalItem(name="skill: <name> — <description line>", categories="Agent skill")`.

**D5. Probabilities follow `behaviorgpt-anomaly`.** Per step we make two calls. Call (a) gets the top 100 with scores. Call (b) uses an `id` filter to get the scores of the chosen command(s) plus 99 uniformly sampled catalog items. Then p = softmax(s/τ), with the partition sum = exact over the head + (N−100)·mean over the sample. Excess surprisal = −log p − entropy. τ is fitted by maximum likelihood on training steps, and a 2% uniform mixture bounds surprisal. This is preferred over raw rank because rank cannot separate "slightly off" from "wildly off" and is not comparable across contexts.

**D6. Potency = log-probability shift around the load (counterfactual), not the post-load rank alone.** Rank alone mixes up "this skill works" with "this command is common anyway." Comparing the same history with and without the skill load isolates the skill's effect. The prescribed set's mass is the sum of its members' probabilities.

**D7. Fixed parameters.** These are fixed before looking at test results: temporal cutoff at the session start time that puts ~70% of sessions in train; follow window N = 10 tool calls; potency support threshold = 5 scorable loads; baseline = bigram over signatures with backoff to unigram, trained on train sessions.

**D8. Runtime layout.**
- Stage 1, `extract.py`, runs on pacel-orin with stdlib + pyarrow. It writes `catalog.parquet`, `histories.jsonl`, and `skill_loads.jsonl`, which are copied to the Mac with scp.
- Stage 2, `score.py`, runs on the Mac with `AsyncUnboxAIClient`, bounded concurrency, and a SQLite response cache keyed on (catalog_id, history hash, call kind).
- Stage 3, `report.py`, computes the metrics and draws the chart.
- Raw `state.db` text never leaves pacel-orin.

## Risks / Trade-offs

- [The model ranks seen items low, so a repeat-heavy agent looks unpredictable] → score first occurrences only (spec), and report the baseline on the same steps.
- [Human-retail priors don't transfer to command names] → that is the research question itself. Report the result honestly, and either way the potency shift still measures *relative* change.
- [Prescribed-command extraction from SKILL.md is noisy] → apply the same normalizer to both sides, flag skills with an empty set, and spot-check 10 skills by hand before the full run.
- [Few loads per skill (~3.7 mean)] → use the support threshold and the separate "insufficient data" list, and validate grouped by skill.
- [A secret leaks into catalog names] → signatures drop all arguments; scan the outputs with a regex for tokens, URLs, and paths before upload.
- [Embed job fails or is slow] → embed a 50-row slice first; the full catalog is small.
- [API rate limits or latency] → cache, cap concurrency, and limit the run to test sessions plus the 252 loads (≈2 calls per scored step).

## Open Questions

- Exact `id`-filter syntax for `complete` (in the OpenAPI spec or the anomaly repo's `api.py`). Needed for D5, but finding it doesn't change the approach.
- Whether `View` in an inline history accepts per-event timestamps. If it does, pass them. If not, events carry only their order.
- Where the SKILL.md files live on pacel-orin (likely under `~/.hermes/skills/`), and whether each load's skill version can be recovered or only the current version.
