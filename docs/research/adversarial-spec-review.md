# Adversarial review: skill-assessment scope and model choice

Second pass, 2026-11-08, against `main` at `5168c71e74c71ddc7f0aaeefbb698418022db66b`. The upstream specification is unchanged since the first review. This update retains the ten valid findings and reconsiders the approach after the user's decision: "We dont need to use behaviorgpt if its not optimal". No method has been established optimal.

## Decision

**Recommend a bounded, model-free evidence audit as the first demo; keep prediction optional.** Start with 3-5 skills only if a small pilot establishes that their requirements and historical exposure are observable. Produce rule-level evidence and explicit unknowns, not a usefulness score or cleanup recommendation. Fall back to fewer skills or a clearly synthetic demonstration when real data cannot support the audit. This is a recommendation, not an implemented scope change.

**No-go for causal potency, general skill quality, or automated pruning claims.** The current calculation measures BehaviorGPT's response to adding a skill-name/description event. Observed command agreement is separate. Neither establishes usefulness, successful execution, or causal influence. Removing the model removes infrastructure work, not these validity problems.

The checkout contains planning artifacts and agent workflow files, with no pipeline implementation, dependency manifest, extracted dataset, or evaluation outputs. No private source data, remote-machine access, API key, quota, inference behavior, latency, or cost was verified during this review. All findings below concern the specification; empirical failure modes are identified as risks rather than observed results. No dependencies or inference workloads were run.

References below are repository-relative paths and line numbers at the reviewed commit. `active/` abbreviates `openspec/changes/behaviorgpt-skill-potency/` only within this document.

## Retained findings about the current active specification

Findings 1-10 remain valid against the unchanged sources. API/probability/calibration findings apply only if that experiment is retained; they are not prerequisites for the recommended model-free core. Findings about exposure, matching, privacy, missingness, and sample support also apply without a model. The fixes below are conditional recommendations, not a requirement to build every proposed component.

### 1. P1: The estimand does not support the influence claim

**Evidence:** `active/design.md:35-39`; `active/proposal.md:16,26`; `active/specs/skill-potency/spec.md:5,10`.

The added event contains the skill name and description, not the loaded instructions. Comparing `p(commands | H, skill-description)` with `p(commands | H)` changes the predictor's input, not the agent's treatment. A semantically suggestive description could raise the score even when the agent never received or followed the instructions. Task intent can cause both loading and subsequent commands. A negative shift does not establish that a skill was inert.

**Minimum fix:** Rename the quantity "model response to skill context" and report it alongside observed command agreement. Remove "isolates the skill's effect," "most influential," and pruning recommendations. Add a small fixed shuffled-description control on the same prefixes, or explicitly defer any claim beyond descriptive model response. No randomized agent experiment is required for this demo if causal claims are removed.

### 2. P1: Probability sampling, tail rank, and cache identity are underspecified

**Evidence:** `active/design.md:37,45`; `active/specs/behavior-scoring/spec.md:17-21`.

D5 samples catalog items but does not say to exclude the top-100 head or keep forced target retrieval separate from the random sample. This can double-count head mass or bias the tail. A target legitimately drawn in the uniform sample can remain in that sample; forced insertion must not increase its sampling weight. D5 assumes 100 head items even for smaller catalogs and assumes all prescribed targets plus 99 reference items fit one response. Independent pre/post samples can change a small shift's sign. A filtered target score alone does not give its exact global rank.

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

## Second-pass findings: challenge the choice of experiment

### 11. P1: Next-command accuracy does not answer the product question

**Evidence:** `active/proposal.md:5,14-16,24-26`; `active/specs/behavior-scoring/spec.md:5,35`; `active/specs/skill-potency/spec.md:5,46`; `README.md:3`.

The active proposal substitutes next-command prediction and a model-context shift for the broader interest in skill selection, procedural agreement, and usefulness. Even perfect next-command prediction could simply learn common commands; it would not show whether selection was appropriate or whether a skill helped. Conversely, useful instructions can change checks, reasoning, or constraints without changing the next command signature. Sponsor-model use was an explicit motivation in the proposal; the user has now removed it as a constraint.

**Minimum fix:** Choose one demonstrable product question before choosing a model. Recommend "What trace evidence supports agreement with selected observable requirements after a successful skill load?" Keep selection relevance and task benefit as separate, explicitly unanswered questions. Move next-command prediction to an optional appendix; a successful prediction experiment cannot validate the core audit or supply a skill-quality score.

**Story tradeoff:** `active/proposal.md:5` still names "predict the next action" as the hackathon theme. Making a sponsor model optional does not prove a descriptive audit satisfies that theme or the user's broader selection goal. Present it as an inspection aid; confirm the desired demo story when deliberately revising scope. If prediction is essential to the pitch, keep one bounded auxiliary prediction experiment rather than relabeling observation as prediction.

### 12. P1: A loaded-only audit cannot discover useful overlooked skills

**Evidence:** `active/specs/agent-trace-extraction/spec.md:49-58`; `active/specs/skill-potency/spec.md:20-32`; `active/proposal.md:9,16`; `docs/research/log-inventory.md:67,71,82`.

The specified records condition on a skill load. They omit decision points where an available skill was never loaded. Installed-skill counts do not establish which versions were available or described to the agent at each decision. No selection opportunity denominator, task relevance labels, or task-success ground truth is supplied. Therefore neither the current predictor nor a model-free audit can distinguish overlooked skills from irrelevant or unavailable ones, or recommend removing a loaded skill because of low matching rates.

**Minimum fix:** Label the output "audit of observed loaded episodes" and disclose its selection bias. Defer missed-invocation/cleanup claims. A future selection study needs task decision points, the contemporaneous available and exposed skill set, and reviewed relevance labels, including non-loads. Do not bolt this dataset reconstruction onto the few-hour core.

### 13. P1: A model-free rule audit still needs applicability and epistemic limits

**Evidence:** `active/specs/agent-trace-extraction/spec.md:50-58`; `active/specs/skill-potency/spec.md:21-29`; `active/design.md:41,53,63`.

Removing BehaviorGPT does not turn code blocks into obligations. Conditional steps may not apply; optional steps may be skipped; negative instructions cannot be assessed by positive command matching; alternative procedures may satisfy the same requirement. Requirements about file contents or outcomes cannot be verified from stripped signatures. A complete ten-call window is only a bounded observation period, not a complete task. A successfully loaded current file is not proof of historical exposure to that version.

**Minimum fix:** For each selected rule, manually record the skill version, source instruction span, obligation type, applicability evidence, allowed alternatives, observable evidence predicate, and window boundary. Support positive mandatory requirements with observable conditions first. Mark negative/optional, ambiguous, content-dependent, or unobservable rules unsupported for this demo. If applicability, historical content, successful exposure, order, or observation completeness is unknown, return insufficient evidence. A failed command attempt can support an attempt requirement, never a successful-result requirement. Keep outcomes at rule/episode level; do not promote one matched step to whole-skill compliance.

### 14. P2: The simple alternative moves the bottleneck into manual review

**Evidence:** `active/tasks.md:14,27-29`; `active/design.md:15,53-54`; `docs/research/log-inventory.md:58,67,82`.

Three to five skills can still contain many conditional requirements. The existing plan's ten-skill spot check plus three loads does not measure labeling effort or accuracy. Frequently loaded cron skills can produce many near-duplicate episodes, while hand-picking easy skills produces an observability-biased showcase. An LLM judge would move, rather than remove, the need for trustworthy relevance/applicability labels.

**Minimum fix:** Timebox the initial audit to 45 minutes, two skills, at most ten episodes, and one or two positive observable rules per skill. Choose cases by a declared deterministic rule before seeing labels; log excluded skills and reasons. Expand to 3-5 skills and at most 20 episodes only if the pilot works within the timebox. Report session/task clusters and duplicate cron templates; no independence assumption or statistical ranking. If the bottleneck is manual adjudication, shrink the scope rather than adding a new judge under deadline pressure. Have a second person inspect a few cases only if one is available; otherwise disclose single-reviewer judgments.

## Three separate questions and their evidence

| Question | Necessary evidence | What this hack can honestly deliver |
|---|---|---|
| Was selection appropriate, including useful skills not selected? | Task/decision context, available and exposed skill versions, relevance labels, selected and non-selected cases | Deferred. A loaded-only corpus has no missed-selection denominator. |
| Were observable requirements followed after loading? | Successful exposure, applicable versioned rule, ordered subsequent trace evidence, explicit observation limits | Small rule-level agreement audit; supported agreement, no observed agreement, or insufficient evidence. |
| Did the skill improve task benefit? | Reviewed task outcomes and a credible comparison with alternatives or no skill | Deferred. A command match or predictor lift is not task-success evidence. |

## Ranked approaches for this hackathon

This is an engineering recommendation given the documented constraints, not measured model performance. All options remain gated on data access and label feasibility. No provider or model is established optimal.

| Rank | Approach | Best use here | Main failure / decision |
|---|---|---|---|
| 1 | Model-free, read-only evidence audit with a small hand-reviewed rule map | Directly inspect observable agreement in loaded episodes; make uncertainty visible | Manual applicability/exposure work is essential. Recommend only after the bounded pilot; no usefulness or selection claims. |
| 2 | Small assessment using an already available text model | Optional assistance with task relevance or proposing rules to a human reviewer | Inferred relevance is a separate proxy. Hallucinated applicability, instruction injection in supplied logs, privacy, and human label cost remain. Do not auto-accept judgments or assume availability/access. |
| 3 | Simple frequency/bigram prediction experiment | Cheap auxiliary baseline if next-command prediction is still interesting | Needs a stable vocabulary and adequate histories; does not assess benefit or compliance. Skip it if the core report consumes the budget. |
| 4 | BehaviorGPT next-command experiment | Optional bounded test of whether this model adds value on agent traces | Requires catalog/API work and retained fixes 1-10, while adding no direct task-benefit evidence. Do not make it the critical path. |

A static inventory/count report is the lower-effort fallback, not a substitute for behavioral evidence. A synthetic fixture demo is the final fallback if no authorized, usable real corpus is ready. Both must state which behavior claims they cannot support.

## Narrow recommended core and acceptance checks

The proposed core is a read-only CLI over a source-local snapshot or explicitly supplied sanitized fixtures. It uses ordinary trace records and a tiny reviewed rule map, without a provider-specific catalog or a new plugin framework. These are proposed checks for a later implementation, not checks performed in this PR.

1. **Data and exposure gate:** Identify the snapshot, stable call/result IDs, source ordering, loaded skill-content hash/version and successful load result. No matching of current skill text to historical episodes without a visible version-mismatch limitation; use insufficient evidence for historical agreement when it changes the rule. Do not broaden data access or copy raw logs to satisfy the demo.
2. **Rule and applicability gate:** Start with the pilot above. For every evaluated rule include instruction location, obligation type, observable condition, permissible alternatives and evidence requirement. Record local trace references supporting applicability; otherwise mark unknown. Select before observing outcomes and list exclusions. Do not infer relevance merely because the agent loaded a skill.
3. **Status contract:** "Supported agreement" requires the particular observable predicate after successful exposure. "No observed agreement" requires known applicability and an intact declared observation window, and means only that its predicate was not found there. "Insufficient evidence" covers missing data, unclear applicability, unsupported rules, historical-version gaps, ordering ambiguity and truncated windows. Never map unknown to failure. Keep applicability/not-applicable exclusions separate from evaluated-status denominators.
4. **Evidence and boundary checks:** Every row includes pseudonymous episode ID, skill/version, rule ID, window, status, reason and stable source references; positive rows cite the observed action/result and applicability evidence. Failed commands, valid alternatives, duplicate/reloaded skills, same-batch calls, session endings and overlapping windows have explicit policies. No automated execution, deletion, or edits to skills.
5. **Small review set:** Manually check at most ten pilot cases against their traces. Include a positive match, applicable no-match, unknown applicability, optional/negative exclusion, alternate valid procedure, failed result, version mismatch, and an incomplete or ambiguous window. These are semantic acceptance scenarios, not a claim that current data contains them. Use labeled fixtures for missing edge cases, clearly separated from real cases. Revise the rules on pilot cases, then check a few reserved cases; report disagreements instead of inventing an accuracy guarantee.
6. **Reproducibility/privacy:** Repeated runs on the same snapshot/rules yield identical substantive rows. Match rows/counts to source-local counts without exposing raw text. Export only reviewed safe fields; keep private source pointers local or pseudonymous. No external inference is needed for this core. The CLI is read-only and source integrity is checked in a manner compatible with other live writers.
7. **Demo outputs:** One machine-readable evidence table, a Markdown report with audited examples and limitations, and one chart of the three statuses per skill with denominators and excluded counts. Show episode/session counts, snapshot/rule hashes and selection rule. No leaderboard, potency ranking, quality score, or precision claims without a separately defined evaluation. The honest result may be mostly unknown or only two auditable skills.

**Supported claims:** "For this version, episode and observable rule, these trace events support agreement"; "no matching evidence was observed within the declared applicable window"; "evidence is insufficient"; and descriptive counts for this selected sample.

**Unsupported claims:** good/bad or useful/useless skill; causal influence; improved task success; instructions were ignored; entire procedure complied with; a useful skill was overlooked; a skill should be deleted; population-wide adherence; model optimality. Any text-model relevance judgment must be labeled a reviewed proxy separately from trace evidence.

## Decision gate for any added model

Do not compare approaches that answer different questions on a common leaderboard. The trace audit is an evidence task; relevance judging is a text-label task; next-command prediction is a ranking task. Define the intended additional output before running a model.

- Reserve no more than 15 minutes and 20 external calls, including retries, for one optional method after the core works. Use no new provider onboarding, training/fine-tuning, temperature-fitting project, or multi-provider bake-off. A method that cannot be evaluated under that cap is deferred, not presumed inferior.
- Fix the model/SDK/settings, sanitized inputs, cases, labels, candidate universe, baseline, metric, stop rule and call budget before looking at results. Do not choose only successful model examples. Logs and skill text are untrusted data, not instructions for the evaluator; allow no tool actions from judged text.
- For next-command prediction use the same held-out steps, temporal cutoff, first-use policy, candidate mask and hit-rate denominator as a bigram/unigram baseline. Explain that richer query/skill text is extra input; report it as a system comparison, or add a matched-input ablation if the cap permits. Never call it intrinsic model superiority. Skip probability/entropy/potency computation entirely if all the optional demo needs is top-k inclusion.
- For relevance/rule proposals use the same task and skill excerpts as a simple keyword/rule baseline and independently reviewed labels. Keep rubric revision cases separate from a small reserved set. A model's own labels cannot serve as ground truth for its evaluation. Abstentions and unsupported confident judgments count visibly.
- Retain a model only if it fixes at least two baseline errors on ten reserved reviewed cases without introducing additional unsupported confident judgments, meets the time/call/privacy cap, and adds a concrete decision/example that the model-free report lacks. This is a proposed hackathon stop rule, not a powered benchmark or evidence of general superiority. If ten credible reserved cases cannot be obtained within the cap, label outputs exploratory or omit the model.
- Report failures, ties, input differences, sample size and elapsed cost. A marginal or unmeasured gain is not a reason to block a finished evidence demo. If there is no added value, ship the evidence report without a predictive model.

## What optional BehaviorGPT lets us delete or defer

If the team accepts the model-free core, remove the following from the critical path when deliberately revising the active specification:

- `active/tasks.md:5-7`: Unbox key, SDK installation and provider-specific filter/timestamp setup.
- Provider-specific parts of `active/tasks.md:13,15-16`: Search/View/ExternalItem mapping, 15-column parquet/schema checks, catalog popularity and cross-machine catalog transfer. Retain sanitized extraction and source integrity; do not implement a universal intermediate format just for hypothetical future backends.
- `active/tasks.md:20-23`: catalog embedding, cached async API scoring, head/tail sampling, temperature/entropy/surprisal and next-command evaluation. A small prediction baseline is optional, not required for the audit.
- Model-specific parts of `active/tasks.md:27-29`: pre/post probability shifts, grouped shift-to-follow-through prediction, potency ranking and the non-positive-shift headline. Replace them with evidence rows, unknowns, reviewed examples and status counts.
- `active/design.md:29,33-39,45,51,56-57`: provider event conventions, embeddings, catalog slots, sampling/calibration, API cache and model-driven repeat exclusions. Commands repeated after loading remain ordinary candidate evidence in an audit.

Retain the hard shared work: a trustworthy snapshot, exposure/version evidence, applicability rules, meaningful command/result matching, privacy, stable references and a reproducible report. Removing the model does not solve these.

## Synchronize the active specification before implementation

This PR changes only this review document. The active OpenSpec still describes the BehaviorGPT experiment and remains the implementation source until deliberately revised. Do not implement the recommendation while leaving contradictory requirements active.

| Artifact | Minimum deliberate revision if the recommendation is accepted |
|---|---|
| `active/proposal.md:5-26,33-36` | State the bounded loaded-episode evidence question, supported/unsupported claims, model-independent outputs and optional experiments. Remove sponsor-model necessity and causal/cleanup wording. |
| `active/design.md:19-63` | Replace provider-first decisions with the snapshot/exposure/rule/status contract, fixed pilot bounds and local-only data flow. Keep any model experiment in a labeled optional section with its own gate. |
| `active/specs/agent-trace-extraction/spec.md:31-65` | Specify neutral evidence records, successful exposure, stable source offsets, sanitization and version uncertainty. Require a temporal split only for a retained predictive evaluation, not as fake validation of descriptive counts. |
| `active/specs/skill-potency/spec.md:5-50` | Replace shift ranking with rule-level agreement evidence, explicit applicability and unknowns, window policies and status-chart/report acceptance. Rename the capability consistently if desired. |
| `active/specs/behavior-scoring/spec.md:5-46` | Explicitly defer it or isolate it as an optional experiment; remove mandatory probability outputs from the core. Do not leave mandatory SHALLs behind an informal "optional" task label. |
| `active/tasks.md:5-33` | Reorder: data/exposure feasibility, two-skill pilot, reviewed rules, evidence CLI/report and acceptance checks; optional model last. Update integration outputs and achievable deadline without pretending any task is completed. |
| `README.md:1-3`; `AGENTS.md:3`; `docs/handoffs/handoff.md:14-19` | Align the public description and active change pointer if renamed; mark superseded handoff choices explicitly. Preserve historical docs as history rather than silently treating them as current scope. |

Validate the revised OpenSpec consistently before coding, as `AGENTS.md` requires. A separate implementation PR should follow the scope decision; this review does not authorize running private-data jobs or inference.

## Remaining limits and fallback

**Unverified shared blockers:** access to an authorized consistent source snapshot, retrievable historical skill content/exposure, adequate task context, reliable call/result alignment, sanitization, and an achievable reviewed sample. The inventory is documentary evidence, not fresh validation of those properties. No current data, API, quota, cost or model-quality claim has been tested here.

If the two-skill pilot cannot support rule evidence within 45 minutes, ship an inventory/observability report and clearly synthetic end-to-end examples. Do not label that fallback an assessment of real skill compliance. If a few real cases are supportable, show those with exclusions and unknowns; do not force five skills or a ranking. Optional prediction may fail or be omitted without making the core demo fail.

Defer usefulness/causal claims, automatic cleanup or edits, overlooked-skill discovery, broad semantic judging, general shell parsing, multi-harness/provider support and production integrations. The recommended demo is useful as an inspection aid for a narrow sample; whether that narrower product is the desired hackathon story is the explicit scope decision still needed before revising the active spec.
