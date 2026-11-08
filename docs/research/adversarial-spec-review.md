# Adversarial review: BehaviorGPT skill-potency specification

Reviewed 2026-11-08 against `main` at `5168c71e74c71ddc7f0aaeefbb698418022db66b`.

## Decision

**Conditional go for an exploratory demo; no-go for the current claim that this measures a skill's influence on agent behavior or identifies skills to prune.** The proposed calculation measures BehaviorGPT's response to adding a skill-name/description event. Observed command agreement is a separate measurement. Neither establishes usefulness, successful execution, or causal influence.

The checkout contains planning artifacts and agent workflow files, with no pipeline implementation, dependency manifest, extracted dataset, or evaluation outputs. No private source data, remote-machine access, API key, quota, inference behavior, latency, or cost was verified during this review. All findings below concern the specification; empirical failure modes are identified as risks rather than observed results. No dependencies or inference workloads were run.

References below are repository-relative paths and line numbers at the reviewed commit. `active/` abbreviates `openspec/changes/behaviorgpt-skill-potency/` only within this document.

## Prioritized findings

### 1. P1: The estimand does not support the influence claim

**Evidence:** `active/design.md:35-39`; `active/proposal.md:16,26`; `active/specs/skill-potency/spec.md:5,10`.

The added event contains the skill name and description, not the loaded instructions. Comparing `p(commands | H, skill-description)` with `p(commands | H)` changes the predictor's input, not the agent's treatment. A semantically suggestive description could raise the score even when the agent never received or followed the instructions. Task intent can cause both loading and subsequent commands. A negative shift does not establish that a skill was inert.

**Minimum fix:** Rename the quantity "model response to skill context" and report it alongside observed command agreement. Remove "isolates the skill's effect," "most influential," and pruning recommendations. Add a small fixed shuffled-description control on the same prefixes, or explicitly defer any claim beyond descriptive model response. No randomized agent experiment is required for this demo if causal claims are removed.

### 2. P1: Probability sampling, tail rank, and cache identity are underspecified

**Evidence:** `active/design.md:37,45`; `active/specs/behavior-scoring/spec.md:17-21`.

D5 samples catalog items but does not say to exclude the top-100 head or exclude forced targets from the sampling estimate. This can double-count head mass or bias the tail. It assumes 100 head items even for smaller catalogs and assumes all prescribed targets plus 99 reference items fit one response. Independent pre/post samples can change a small shift's sign. A filtered target score alone does not give its exact global rank.

The cache key `(catalog_id, history hash, call kind)` also omits target/filter IDs, limit, offset, and other request settings: different filtered queries for the same history can collide. The provider's reference implementation includes these fields in its key, excludes head items from tail estimation, and estimates ranks outside the head rather than retrieving exact ranks. [Provider cache implementation](https://github.com/Unbox-AI/behaviorgpt-anomaly/blob/bed894a4c8985d5da0e7b84d84896d65234c001f/anomaly/api.py#L113-L118); [sampling implementation](https://github.com/Unbox-AI/behaviorgpt-anomaly/blob/bed894a4c8985d5da0e7b84d84896d65234c001f/anomaly/detector.py#L105-L147); [probability and rank implementation](https://github.com/Unbox-AI/behaviorgpt-anomaly/blob/bed894a4c8985d5da0e7b84d84896d65234c001f/anomaly/scoring.py#L60-L94).

**Minimum fix:** Specify head size `min(100, catalog_size)`, a seeded reference sample with head exclusion, separately retrieved forced targets, batched target requests, and approximate tail-rank labels. Reuse reference IDs across paired prefixes and check sign stability on a small pilot. Cache the complete canonical request plus catalog/model/SDK version. If the entire catalog is small enough, retrieve all scores instead of estimating the partition sum.

### 3. P1: Derived histories can still export private text

**Evidence:** `active/specs/agent-trace-extraction/spec.md:27-29,43`; `active/design.md:35,47,55`; `active/tasks.md:11,15-16`; `active/specs/behavior-scoring/spec.md:41-46`.

Command signatures drop arguments, but search events retain query text and external skill events retain descriptions. Both can contain secrets, names, private URLs, or copied content from the source logs. A regex scan is useful but cannot establish that all private text was removed. Printing five decoded tool calls can expose arguments before sanitization. Inline requests and absence of user IDs establish neither absence of provider access nor a general retention guarantee.

**Minimum fix:** Define an allowlist for every exported field, sanitize queries and descriptions on the source machine, and inspect sanitized examples before upload. Print signatures and counts only. Change the requirement title to "No event registration" and explicitly use `register_event=False`; document that sanitized histories are transmitted for scoring. Do not promise unverified provider retention behavior. The [SDK](https://github.com/Unbox-AI/behaviorgpt/blob/d2d1215bde76e7430c7300afea334c765ed62d07/src/behaviorgpt/_client.py#L441-L508) supports inline histories and disabling event registration.

### 4. P1: Command agreement can be a false positive by construction

**Evidence:** `active/specs/agent-trace-extraction/spec.md:17,50-58`; `active/design.md:53,63`.

The explicit example maps `gh pr create --fill` to `terminal: gh pr`. A later `gh pr view` would therefore satisfy an instruction to create a PR. Similarly, any `read_file` can satisfy a file-specific instruction. Code blocks can contain alternatives, examples, setup steps, or commands the agent must avoid. Current SKILL.md content may differ from the version loaded historically.

**Minimum fix:** Use a small manually audited map for the demo's supported skills, retain meaningful nested subcommands, and label the result coarse command agreement. Record the skill-content hash and whether it is historical or current; mark unavailable versions as a limitation or exclude them from stronger claims. Record unparseable, missing, and unsupported cases separately rather than treating them as ignored. Support shell wrappers and compound commands only where the pilot confirms reliable parsing.

### 5. P1: Event order and load success are not defined tightly enough

**Evidence:** `active/specs/agent-trace-extraction/spec.md:43,50`; `docs/research/log-inventory.md:61-65`; `active/specs/skill-potency/spec.md:21`.

The inventory describes assistant rows containing lists of tool calls and separate result rows. The spec does not say how to deduplicate these, break timestamp ties, handle parallel calls, recognize a failed skill load, or distinguish an attempted command from a successful execution. A skill request and command in one assistant batch cannot establish that the command was chosen after reading the returned skill.

**Minimum fix:** Use stable call IDs and source sequence positions, join requests to results, and define a load at successful content availability. Exclude ambiguous same-batch orderings from follow-through attribution. Call shell observations "command attempts" unless execution status is checked. Preserve source-call offsets separately from mapped-history offsets so the ten-call window is unambiguous.

### 6. P1: Follow-through and first-occurrence scoring conflict

**Evidence:** `active/specs/behavior-scoring/spec.md:27-32`; `active/specs/skill-potency/spec.md:21-29`; `active/design.md:41`.

Follow-through may be a repeated command, but repeated commands explicitly have no per-step score. The requirement to attach excess surprisal to every followed load is therefore not implementable as written. Multiple loads can claim the same subsequent command, and session endings or another skill load can truncate or contaminate the window. No match in ten calls is not proof of ignoring a skill.

**Minimum fix:** Record agreement independently of scoring, and allow excess surprisal to be null for repeats. For the demo, deduplicate repeated loads of the same skill within an episode and flag overlapping windows. Distinguish "no match in observed window" from incomplete observation; do not label either "ignored." Fix whether another skill load closes the window before viewing results.

### 7. P1: The prediction task and candidate set need an explicit contract

**Evidence:** `active/specs/agent-trace-extraction/spec.md:32,38-43,61`; `active/specs/behavior-scoring/spec.md:28,35-39`; `active/design.md:33,41`.

Train-only popularity does not specify whether command vocabulary and descriptions may use future sessions. Building the vocabulary from all sessions is a transductive experiment, not automatically an invalid one, but must be disclosed; otherwise test-only items have no defined training-period timestamp. Evaluating only first uses is also a narrower task than general next-command prediction. A bigram baseline can waste predictions on seen commands unless both systems receive the same candidate exclusions. Search and skill context available to BehaviorGPT is not represented in a signatures-only baseline. With one correct next command, top-k inclusion should be defined as hit-rate@k; precision@k would divide hits by k.

**Minimum fix:** Freeze a train-only catalog and report test out-of-vocabulary coverage, or explicitly disclose the transductive catalog and identical baseline candidate universe. Define scored targets as first-occurrence catalog command events, specify treatment of intervening search/skill events and ties, and use the same seen-item mask for both methods. Report hit-rate@{1,5,10}, step counts, session counts, and coverage. Explain the baseline's context disadvantage; add a cheap skill-conditioned frequency baseline only if time permits.

### 8. P2: Support counts and grouped validation do not justify a stable ranking

**Evidence:** `active/specs/skill-potency/spec.md:32,39,46`; `active/tasks.md:28`; `docs/research/log-inventory.md:67,82`; `active/design.md:41`.

Only ten skills have at least five loads in the entire reported corpus, before temporal splitting, parsing, version checks, or window exclusions. The spec does not identify which partition produces the potency ranking. Five loads can come from one session or repeated cron tasks. Grouping by skill does not prevent the same session or related task from crossing folds when multiple skills occur together. Larger prescribed-command sets have more opportunities to match. Counting non-positive estimated shifts also ignores estimation uncertainty.

**Minimum fix:** Call an all-load ranking exploratory and keep the next-command evaluation held out. Show loads, independent sessions, prescribed-set sizes, exclusions, and per-load spread; do not guarantee ten ranked skills. Avoid a fitted shift-to-follow-through predictor or significance claim in the hackathon. If a predictive association is retained, prevent shared session/task groups from crossing folds and report its small effective sample size. Treat near-zero or unstable signs as inconclusive, not evidence to prune.

### 9. P1: Runtime and API feasibility have not been gated

**Evidence:** `active/design.md:37,45,57,61-63`; `active/tasks.md:5-7,20-23,33`; `docs/research/log-inventory.md:19,49,69`.

The workload estimate omits training-prefix scoring needed to fit temperature. Each skill load needs two contexts, each ordinarily requiring a head and filtered call: roughly four requests per load before batching and cache reuse, not two. The roughly 13k tool calls in the inventory are not the eligible first-occurrence count. Rate limits, history truncation, filter score comparability, available catalog slots, and suitable calibration data have not been measured. SDK source supports `ExternalItem`, async calls, and `filters={"id": [...]}` in the reference application, but that is not a live account smoke test.

**Minimum fix:** First freeze a source snapshot and print only eligible counts and exclusion reasons. Then use a tiny sanitized pilot to check the exact SDK version, filtered versus unfiltered scores for the same item, maximum response size, history handling, and latency. Budget `2 * (training_prefixes + test_prefixes) + 4 * skill_loads`, adjusted for target batching, caching, controls, and retries. Set a fixed call/time ceiling and a fallback to descriptive agreement plus cached examples. No need for full scientific infrastructure.

### 10. P2: Historical clocks, snapshots, and obsolete instructions can change the result

**Evidence:** `active/design.md:33,44-47,62-63`; `active/tasks.md:16,20`; `docs/research/log-inventory.md:49,96`; `docs/handoffs/handoff.md:14-19`; `docs/handoffs/handoff-pc.md:19`.

The corpus is live with WAL active, so database mtime can change because of other writers even when the extractor is read-only. Multiple extraction reads need one consistent snapshot. The older handoff maps commands to Orders and equates top-k prediction with observed following; both conflict with the active design. The newer inventory already locates skill files, while the active design still lists that as unknown.

The provider's current [SDK sequence builder](https://github.com/Unbox-AI/behaviorgpt/blob/d2d1215bde76e7430c7300afea334c765ed62d07/src/behaviorgpt/_client.py#L313-L393) synthesizes event timestamps near request time. Historical timing is therefore not automatically preserved. The [catalog documentation](https://github.com/Unbox-AI/behaviorgpt/blob/d2d1215bde76e7430c7300afea334c765ed62d07/docs/catalog-format.md#L8-L15) also says catalog ages and sales use upload time unless a reference time is supplied.

**Minimum fix:** Read from a consistent transaction/snapshot on the source machine and record a dataset manifest, cutoff, SDK version, and catalog reference time. Replace the unchanged-mtime acceptance test with read-only access and snapshot consistency; do not copy only the main file from a live WAL database. State explicitly if the demo uses order-only histories with synthetic timing. Mark the old handoff superseded and reconcile the active open questions with the existing inventory.

## Minimum changes before coding

1. Narrow the claim to model-context response and observed command agreement.
2. Define export sanitization, stable event ordering, successful loads, and the supported skill-command map.
3. Fix candidate sets, hit-rate denominators, partition/coverage rules, overlapping windows, and missing scores.
4. Specify the probability estimator and complete cache key; pin the SDK and clarify synthetic clocks.
5. Make data/API/count/latency checks a small feasibility gate before the full run. Report sparse coverage honestly and permit an empty supported ranking.

These are recommendations for revisions to the active OpenSpec artifacts, not amendments made by this review document. Review and synchronize proposal, design, capability specs, and tasks before implementation.

## Demo path and deliberate deferrals

A defensible few-hour demo can show one next-command hit-rate comparison, audited examples of model-context response, and observed command agreement with explicit denominators and exclusions. Use a deterministic capped subset if the feasibility gate exceeds the budget, and label it as a pilot. A negative prediction result is still reportable.

Defer causal skill effects, usefulness/quality judgments, pruning or improvement recommendations, general selection/overlooked-skill discovery, live integrations, multi-harness support, production privacy guarantees, exhaustive shell parsing, and a fitted cross-skill predictor. Do not use obsolete static-feature or retail-fraud claims as evidence for this experiment.

**Unresolved blockers:** no verified source snapshot or historical skill versions; no sanitized derived corpus; no live SDK/filter/embedding/account-capacity check; no measured eligible sample size or request budget. These prevent an unconditional end-to-end go decision, not a documentation review or a bounded feasibility pilot.
