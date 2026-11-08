# Spec Delta

## Purpose

Predicts which commands the agent would run in the next N calls without a given skill, as the counterfactual for potency. Also reports whether that prediction beats simple popularity, so we can see whether "next action" prediction here is more than predicting common commands.

## ADDED Requirements

### Requirement: Expectation model fitted on no-load windows
The system SHALL fit a model of P(command c runs in the next N calls | context) using only train-period windows that have no load, within the previous N calls, of any skill whose prescribed set contains c. Context SHALL include the previous k signatures, session source, recurring-task key when available, and position.

#### Scenario: No test leakage
- **WHEN** the expectation model is fitted
- **THEN** no test-period session contributes to its training rows, base rates, or hyperparameters

#### Scenario: Skill-exposed windows excluded
- **WHEN** a train window follows a load of a skill that prescribes c
- **THEN** that window is not a training row for c

### Requirement: Expected adherence per load
For each scorable load, the system SHALL compute expected adherence Â as the specificity-weighted mean over the prescribed set of the model's probability that each command runs in the next N calls, given the context at the load position with the load itself excluded.

#### Scenario: Habitual command
- **WHEN** the prescribed set holds only commands the agent runs in most comparable no-load windows
- **THEN** Â is close to the observed adherence, and lift is near zero

### Requirement: Popularity-only baseline
The evaluation SHALL compare the expectation model against a baseline that predicts each command's train base rate alone, on the same test no-load windows.

#### Scenario: Paired comparison
- **WHEN** the evaluation runs
- **THEN** the report states AUC and Brier score for both the model and the popularity baseline over the same rows, with the row count

### Requirement: Popularity-stratified next-command evaluation
The report SHALL give next-command hit-rate@k (share of scored steps whose true command is in the top k) for k ∈ {1, 5, 10} on test steps for the model and the popularity baseline, overall and by command-frequency decile, with step and session counts. Only first occurrences of a command within a session SHALL be scored. Both methods SHALL use the same candidate universe and the same seen-item mask.

#### Scenario: Tail commands
- **WHEN** hit-rate@5 is reported
- **THEN** it is also reported for commands in the bottom half of train frequency, so a model that only predicts popular commands is visible

#### Scenario: Repeated command
- **WHEN** `terminal: git status` runs three times in one session
- **THEN** only the first run is scored, and the later two still appear in later steps' context

### Requirement: Train-only vocabulary
The candidate vocabulary SHALL be built from train sessions only. The report SHALL state the share of test steps whose command is out of vocabulary, and those steps SHALL count as misses for every method.

#### Scenario: New command in test
- **WHEN** a test step runs a command never seen in train
- **THEN** it is a miss for both the model and the baseline, and is counted in OOV coverage

### Requirement: Bounded target set
Per-command models SHALL be fitted only for every prescribed command plus a fixed number (300) of the most frequent train commands. The same set SHALL be the candidate universe for hit-rate@k for every method, and the report SHALL state both its size and the full train vocabulary size. Test steps whose command is outside the set SHALL count as misses for every method.

#### Scenario: Large real vocabulary
- **WHEN** a corpus has 7,008 distinct train signatures
- **THEN** models are fitted for at most 300 plus the prescribed commands, and `expect_eval.json` reports the candidate count and `full_train_vocabulary: 7008`

#### Scenario: Prescribed rare command
- **WHEN** a prescribed command occurs only twice in train
- **THEN** it is still a target, with a base-rate fallback estimate

### Requirement: Bounded evaluation cost
Window-level AUC, Brier and calibration SHALL be computed on at most 20,000 test windows, chosen by a deterministic even stride, and the report SHALL state windows evaluated and windows total.

#### Scenario: Large test split
- **WHEN** a corpus has 270,286 test windows
- **THEN** the window metrics use 20,000 evenly spaced windows and `expect_eval.json` reports both counts

### Requirement: Per-corpus models
A separate expectation model SHALL be fitted per corpus. Base rates SHALL NOT be pooled across corpora.

#### Scenario: Two corpora
- **WHEN** Hermes and a public corpus are both analyzed
- **THEN** each has its own model, base rates and evaluation block in `expect_eval.json`

### Requirement: Calibration report
The system SHALL report a calibration curve (10 bins) for the expectation model on test no-load windows.

#### Scenario: Calibration output
- **WHEN** the evaluation completes
- **THEN** `expect_eval.json` contains per-bin predicted and observed rates and bin counts
