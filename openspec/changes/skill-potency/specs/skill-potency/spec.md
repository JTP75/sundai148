# Spec Delta

## Purpose

Measures how much loading a skill raises adherence to its prescribed commands **beyond what the agent would have done anyway**. Ranks skills within each corpus, and guards against potency reducing to popularity or familiarity. The result is reported as agreement with prescribed action, not as skill quality, usefulness or a pruning recommendation.

## ADDED Requirements

### Requirement: Specificity-weighted prescribed sets
Each `required` prescribed command SHALL carry weight w(c) = −log of its smoothed base rate in train no-load windows of the same corpus. Commands whose base rate exceeds a fixed ceiling SHALL be removed from the set. A skill whose set becomes empty SHALL be flagged `generic-only` and not ranked.

#### Scenario: Ubiquitous command dropped
- **WHEN** a skill prescribes `terminal: ls` and `terminal: gog tasks list`, and `ls` appears in more than the ceiling share of no-load windows
- **THEN** its set contains only `terminal: gog tasks list`

### Requirement: Per-load lift
For each scorable load (not `maintenance`, `repeat`, or `version_unknown`), the system SHALL compute observed adherence A as the specificity-weighted share of the load's evidence rows with status `supported_agreement`, among rows with status `supported_agreement` or `no_observed_agreement`. It SHALL compute lift = A − Â, where Â comes from the same corpus's expectation model over the same rules. A load with no determinate rows SHALL have no lift and SHALL be counted as insufficient.

#### Scenario: Skill prescribes habits
- **WHEN** every prescribed command is one the agent runs at the same rate without the skill
- **THEN** lift is near zero even if follow-through is 100%

#### Scenario: Skill introduces a new command
- **WHEN** a prescribed command never appears in no-load windows and is attempted within N steps after the load
- **THEN** lift is positive and close to that command's weight share

### Requirement: Agreement wording
Reports SHALL describe a load with no matching command as "no agreement observed" and SHALL NOT call it "ignored." Loads with `incomplete` or `overlap` windows SHALL be included in the primary result and excluded in a reported sensitivity run.

#### Scenario: Session ends early
- **WHEN** a session ends 3 steps after a load with no match
- **THEN** the load is reported as "no agreement observed (incomplete window)" and is absent from the sensitivity run

### Requirement: Avoided commands reported separately
Commands tagged `avoid` in the audit map SHALL NOT count toward A. Their attempts within the window SHALL be reported as a separate per-skill rate.

#### Scenario: Agent runs an avoided command
- **WHEN** a skill marks `terminal: git push --force` as `avoid` and the agent attempts `terminal: git push` after the load
- **THEN** A is unchanged and the skill's avoid-match count increases

### Requirement: Placebo control
For each scorable load, the system SHALL compute A for K other skills' prescribed sets, drawn with a fixed seed and matched on set size and familiarity mix, over the same window. It SHALL report placebo lift = A − mean placebo A.

#### Scenario: Busy window after any load
- **WHEN** many unrelated skills' commands also run in the window
- **THEN** placebo lift is lower than A by their mean adherence

### Requirement: Familiarity strata
Each prescribed command SHALL be labeled by in-corpus familiarity (novel, occasional, habitual: from its no-load base rate before the skill's creation date, or in train if unknown) and by prior-knowledge proxy (public or local CLI, from the committed hand map). Lift SHALL be reported per stratum and per corpus with load counts. Cells with fewer than 10 loads SHALL be pooled into novel+local vs rest.

#### Scenario: Public habitual command
- **WHEN** a skill prescribes only `terminal: git commit`, which the agent ran regularly before the skill existed
- **THEN** its loads are reported under public/habitual, not under novel+local

### Requirement: Ranking with shrinkage and support marking
Within each corpus, the system SHALL rank every skill with ≥2 scorable loads by empirical-Bayes shrunken mean lift, with 95% bootstrap CIs. Each row SHALL report load count, independent session count, prescribed-set size, follow-through rate, lift, placebo lift and stratum mix. A skill SHALL be marked **supported** only with ≥5 scorable loads and ≥3 independent sessions. An empty supported set SHALL be a valid outcome. A CI that spans zero SHALL be labeled "inconclusive."

#### Scenario: Sparse skill
- **WHEN** a skill has 3 scorable loads from 1 session
- **THEN** it is ranked with a wide CI and is not marked supported

#### Scenario: Single-load skill
- **WHEN** a skill has 1 scorable load
- **THEN** it appears in an "insufficient data" list, not in the ranking

#### Scenario: No supported skills
- **WHEN** no skill meets the support rule
- **THEN** the report shows the full shrunken ranking, states that zero skills are supported, and draws no skill-level conclusions

### Requirement: Popularity check
The report SHALL state the Spearman correlation between skill potency and (a) load count and (b) mean base rate of the prescribed set, and SHALL flag either correlation with |ρ| ≥ 0.5.

#### Scenario: Potency tracks popularity
- **WHEN** potency correlates with load count at ρ = 0.6
- **THEN** the summary flags that the ranking may reflect popularity

### Requirement: Grouped resampling and validation
Bootstrap resampling and any validation SHALL group by session and task key, so that related loads never split across resamples or folds. Predictive validation SHALL also hold out whole skills.

#### Scenario: Recurring cron task
- **WHEN** one cron task key accounts for 12 loads across 12 sessions
- **THEN** those loads are resampled together as one group

### Requirement: Provenance grouping
A skill SHALL be `agent-touched` when `created_by` is `agent` or `learn`, or when any ledger create, patch or write_file entry has actor `agent` or `curator`. Otherwise it SHALL be `no-agent-trace`. Reports SHALL compare lift between these groups and SHALL show the `created_by` split as secondary.

#### Scenario: Curator-patched skill
- **WHEN** a skill has `created_by` null and one curator patch
- **THEN** it is `agent-touched`

### Requirement: Bloat statistic
From the census, the report SHALL give the share of agent-touched skills never loaded, and the share loaded but never supported, as supporting numbers rather than headlines.

#### Scenario: Unloaded auto-created skills
- **WHEN** 56 of 72 agent-created skills have no loads
- **THEN** the report states that 78% of agent-created skills were never loaded

### Requirement: Pre/post creation comparison
When a creation date and task keys exist, the system SHALL report a difference-in-differences of adherence to each skill's commands on keyed tasks before vs after the skill was created, split by provenance group. Missing inputs SHALL produce an explicit "not computable" note.

#### Scenario: Agent-created skill codifies habit
- **WHEN** an agent-touched skill's commands were already run on its task before creation at the same rate as after
- **THEN** its pre/post estimate is near zero regardless of its follow-through

### Requirement: Edit-response
When version sources record which signatures a change added or removed, the system SHALL report the change in post-load rate of those commands after the change, relative to unchanged commands in the same skill. Missing inputs SHALL produce an explicit "not computable" note.

#### Scenario: No version text
- **WHEN** neither the ledger nor `skill_manage` replay yields version text
- **THEN** the edit-response section states it was not computable and why

### Requirement: Paired-run validation
When a corpus contains runs of the same task with and without a skill, the system SHALL compare the observational lift for that skill with the experimental difference in adherence, and report the gap as the estimated endogeneity bias.

#### Scenario: Paired corpus available
- **WHEN** a public corpus has 10 paired runs for a skill
- **THEN** the report shows observational lift, experimental difference and their gap for that skill

### Requirement: Trigger split
The system SHALL report lift separately for `instructed`, `chosen` and `preloaded` loads.

#### Scenario: Both trigger types present
- **WHEN** a skill has both instructed and chosen scorable loads
- **THEN** the report gives lift and load count for each

### Requirement: Endogeneity caveat
The summary SHALL state that observational lift is an upper bound on skill influence because loads are endogenous.

#### Scenario: Caveat present
- **WHEN** the summary is generated
- **THEN** it contains the upper-bound statement next to the headline numbers

### Requirement: Demo outputs
The system SHALL produce, per eligible corpus, a ranking chart (shrunken lift with CIs, colored by provenance, supported skills marked) and a summary with three headline numbers:
1. median lift on novel+local prescribed commands;
2. agent-touched vs no-agent-trace lift (pre/post if computable, else observational);
3. the count of ranked skills whose lift CI includes or is below zero.

#### Scenario: Report generated
- **WHEN** the pipeline completes
- **THEN** the chart and the summary with all three numbers exist, and the summary says "agreement with prescribed action," not "skill quality"
