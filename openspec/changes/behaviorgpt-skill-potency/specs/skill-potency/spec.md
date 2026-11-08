# Spec Delta

## Purpose

Measures how much loading a skill raises adherence to its prescribed commands **beyond what the agent would have done anyway**. Ranks skills from most influential to "loaded but inert," and guards against potency reducing to popularity or familiarity. The result is reported as agreement with prescribed action, not as skill quality.

## ADDED Requirements

### Requirement: Specificity-weighted prescribed sets
Each prescribed command SHALL carry weight w(c) = −log of its smoothed base rate in train no-load windows. Commands whose base rate exceeds a fixed ceiling SHALL be removed from the set. A skill whose set becomes empty SHALL be flagged `generic-only` and not ranked.

#### Scenario: Ubiquitous command dropped
- **WHEN** a skill prescribes `terminal: ls` and `terminal: gog tasks`, and `ls` appears in more than the ceiling share of no-load windows
- **THEN** its set contains only `terminal: gog tasks`

### Requirement: Per-load lift
For each scorable load (not `maintenance`, `repeat`, or `version_unknown`), the system SHALL compute observed adherence A, the specificity-weighted share of the prescribed set run within the next N calls, and lift = A − Â, where Â comes from the expectation model.

#### Scenario: Skill prescribes habits
- **WHEN** every prescribed command is one the agent runs at the same rate without the skill
- **THEN** lift is near zero even if follow-through is 100%

#### Scenario: Skill introduces a new command
- **WHEN** a prescribed command never appears in no-load windows and runs within N calls after the load
- **THEN** lift is positive and close to that command's weight share

### Requirement: Placebo control
For each scorable load, the system SHALL compute A for K other skills' prescribed sets, matched on set size and familiarity mix, over the same window. It SHALL report placebo lift = A − mean placebo A.

#### Scenario: Busy window after any load
- **WHEN** many unrelated skills' commands also run in the window
- **THEN** placebo lift is lower than A by their mean adherence

### Requirement: Familiarity strata
Each prescribed command SHALL be labeled by in-corpus familiarity (novel, occasional, habitual: from its no-load base rate before the skill's creation date, or in train if unknown) and by prior-knowledge proxy (public or local CLI, from a fixed hand map). Lift SHALL be reported per stratum with load counts. Cells with fewer than 10 loads SHALL be pooled into novel+local vs rest.

#### Scenario: Public habitual command
- **WHEN** a skill prescribes only `terminal: git commit`, which the agent ran regularly before the skill existed
- **THEN** its loads are reported under public/habitual, not under novel+local

### Requirement: Skill ranking with shrinkage and support threshold
The system SHALL rank skills by empirical-Bayes shrunken mean lift with 95% session-bootstrap CIs, reporting load count, follow-through rate, mean lift, placebo lift and stratum mix. Skills with fewer than 5 scorable loads SHALL be listed separately, not ranked. A skill SHALL be called potent only when both lift and placebo lift CIs are above zero.

#### Scenario: Sparse skill
- **WHEN** a skill has 2 scorable loads
- **THEN** it appears in an "insufficient data" list, not in the ranking

### Requirement: Popularity check
The report SHALL state the Spearman correlation between skill potency and (a) load count and (b) mean base rate of the prescribed set, and SHALL flag either correlation with |ρ| ≥ 0.5.

#### Scenario: Potency tracks popularity
- **WHEN** potency correlates with load count at ρ = 0.6
- **THEN** the summary flags that the ranking may reflect popularity

### Requirement: Grouped validation
Any reported test of whether a skill-level score predicts adherence SHALL hold out whole skills (grouped by skill), never individual loads.

#### Scenario: Frequently loaded skill
- **WHEN** one skill accounts for many loads
- **THEN** all its loads fall in the same fold

### Requirement: Pre/post creation comparison
When `created_at` and a recurring-task key exist, the system SHALL report a difference-in-differences of adherence to each skill's commands on recurring tasks before vs after the skill was created, split by `created_by` (agent vs other). Missing inputs SHALL produce an explicit "not computable" note.

#### Scenario: Agent-created skill codifies habit
- **WHEN** an agent-created skill's commands were already run on its recurring task before creation at the same rate as after
- **THEN** its pre/post estimate is near zero regardless of its follow-through

### Requirement: Edit-response
When the curator ledger records which signatures a patch added or removed, the system SHALL report the change in post-load rate of those commands after the patch, relative to unchanged commands in the same skill. Missing inputs SHALL produce an explicit "not computable" note.

#### Scenario: Ledger lacks version text
- **WHEN** the curator ledger has no before/after text
- **THEN** the edit-response section states it was not computable and why

### Requirement: Trigger split
The system SHALL report lift separately for `instructed` and `chosen` loads.

#### Scenario: Both trigger types present
- **WHEN** a skill has both instructed and chosen scorable loads
- **THEN** the report gives lift and load count for each

### Requirement: Demo outputs
The system SHALL produce one chart of ranked skills by shrunken lift with CIs, colored by provenance, and a summary with three headline numbers:
1. median lift on novel+local prescribed commands;
2. agent-created vs other skills' lift (pre/post if computable, else observational);
3. the count of ranked skills whose lift CI includes or is below zero.

The summary SHALL state that observational lift is an upper bound on skill influence because loads are endogenous.

#### Scenario: Report generated
- **WHEN** the pipeline completes
- **THEN** the chart and the summary with all three numbers exist, and the summary says "agreement with prescribed action," not "skill quality"
