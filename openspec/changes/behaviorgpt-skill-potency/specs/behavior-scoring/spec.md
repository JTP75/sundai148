# Spec Delta

## Purpose

Uses BehaviorGPT to score how expected each agent step was given its history, and tests whether a model trained on human behavior predicts an agent's next command better than a simple baseline.

## ADDED Requirements

### Requirement: Per-step scores
For each scored step, the scorer SHALL record the command actually run, its rank in BehaviorGPT's ranking of the catalog given the history before that step, its probability, and its excess surprisal (surprisal minus the entropy of the model's prediction at that step).

#### Scenario: Step scored
- **WHEN** a test-session step runs `terminal: git rebase` after a history of earlier steps
- **THEN** the output row holds that signature's rank, probability, and excess surprisal for that step

#### Scenario: Command outside the top results
- **WHEN** the command run is not in the model's top 100
- **THEN** its rank and probability are still reported, not dropped or treated as missing

### Requirement: Probability estimate method
Probabilities SHALL come from a temperature softmax over the ranking scores. The partition sum SHALL be exact over the top 100 and estimated from a uniform sample for the rest of the catalog. The temperature SHALL be fitted on training sessions only.

#### Scenario: No test leakage in calibration
- **WHEN** the temperature is fitted
- **THEN** no test-period session contributes to the fit

### Requirement: First occurrences only
Only the first use of a command within a session SHALL be scored. Repeat uses SHALL stay in the history as context but SHALL NOT be scored.

#### Scenario: Repeated command
- **WHEN** `terminal: git status` runs three times in one session
- **THEN** only the first run is scored, and the later two still appear in the histories of later steps

### Requirement: Next-command evaluation against a baseline
The evaluation SHALL report precision@k for k ∈ {1, 5, 10} on test sessions for BehaviorGPT and for a session n-gram baseline fitted on training sessions, over the same set of scored steps.

#### Scenario: Paired comparison
- **WHEN** the evaluation runs
- **THEN** both methods are scored on the same steps, and the report states the step count, k values, and both precision values for each k

### Requirement: Nothing recorded at the provider
Scoring calls SHALL send histories inline and SHALL NOT register events or user ids with the provider.

#### Scenario: Inline histories
- **WHEN** a scoring call is made
- **THEN** it carries the history in the request and no user id
