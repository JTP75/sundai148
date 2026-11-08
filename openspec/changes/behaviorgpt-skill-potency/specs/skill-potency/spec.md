# Spec Delta

## Purpose

Measures whether loading a skill makes its prescribed commands more likely to follow, and ranks skills from most influential to "loaded but inert," reported as agreement with prescribed action rather than as skill quality.

## ADDED Requirements

### Requirement: Per-load shift
For each scorable skill load, the system SHALL compute the probability of the skill's prescribed commands given the history just before the load, and again given the history including the load. The difference in log probability is the load's shift.

#### Scenario: Load raises the prescribed command
- **WHEN** the prescribed command's probability rises after the load
- **THEN** the load's shift is positive

#### Scenario: Several prescribed commands
- **WHEN** a skill prescribes more than one command
- **THEN** the shift uses the combined probability mass of all of them

### Requirement: Observed follow-through
For each scorable load, the system SHALL record whether any prescribed command was actually run within the next N tool calls of the session (N fixed before results are viewed) and, if so, its excess surprisal.

#### Scenario: Prescribed command run
- **WHEN** a prescribed command runs within N calls after the load
- **THEN** the load is marked followed, with that step's excess surprisal

#### Scenario: Loaded and ignored
- **WHEN** no prescribed command runs within N calls
- **THEN** the load is marked not followed

### Requirement: Skill ranking with a support threshold
The system SHALL rank skills by mean per-load shift, reporting each skill's load count and follow rate. Skills with fewer than a minimum number of scorable loads (default 5) SHALL be listed separately, not ranked.

#### Scenario: Sparse skill
- **WHEN** a skill has 2 scorable loads
- **THEN** it appears in an "insufficient data" list, not in the ranking

### Requirement: Grouped validation
Any reported test of whether shift predicts follow-through SHALL hold out whole skills (grouped by skill), never individual loads.

#### Scenario: Frequently loaded skill
- **WHEN** one skill accounts for many loads
- **THEN** all its loads fall in the same fold

### Requirement: Demo outputs
The system SHALL produce one chart of skills ranked by shift and a summary with three headline numbers: BehaviorGPT precision@5 vs baseline, the share of scorable loads followed, and the count of ranked skills with non-positive shift.

#### Scenario: Report generated
- **WHEN** the pipeline completes
- **THEN** the chart file and the summary with all three numbers exist, and the summary says "agreement with prescribed action," not "skill quality"
