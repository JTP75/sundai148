# Spec Delta

## Purpose

A model-free, per-rule evidence layer over loaded episodes. It records what trace evidence supports agreement with each observable rule after a successful skill load, and makes unknowns explicit. It is a complete demo on its own and the input that lift and ranking build on.

## ADDED Requirements

### Requirement: Evidence rows
For every scorable load and every scored rule of that load's skill version, the system SHALL write one row to `evidence.csv` with: pseudonymous episode id, corpus, skill, version id, rule id, obligation type, window start and end, status, reason code, and the step ids of matching evidence.

#### Scenario: Row content
- **WHEN** a load of `gog-cli` with two scored rules is processed
- **THEN** `evidence.csv` has two rows for that load, each with all fields filled (evidence step ids empty when there is no match)

### Requirement: Supported agreement status
A row SHALL have status `supported_agreement` when the rule's observable predicate or an allowed alternative was attempted within the window after a successful load, and not only in the load's own batch.

#### Scenario: Match after load
- **WHEN** `terminal: gog tasks list` is attempted 2 steps after a successful `gog-cli` load whose rule requires it
- **THEN** the row is `supported_agreement` and cites that step id

#### Scenario: Allowed alternative
- **WHEN** the rule allows `terminal: gog tasks get` as an alternative and only that is attempted
- **THEN** the row is `supported_agreement`

### Requirement: No observed agreement status
A row SHALL have status `no_observed_agreement` only when applicability is known to hold, the window is not `incomplete`, and no matching step exists in the window. Reports SHALL describe it as "no matching evidence in the declared window," never as "ignored."

#### Scenario: Applicable and complete
- **WHEN** a `required` rule with no applicability condition has no match in a complete 10-step window
- **THEN** the row is `no_observed_agreement`

### Requirement: Insufficient evidence status
A row SHALL have status `insufficient_evidence`, with a reason code, when any of these holds:
- applicability is `unknown` for a `conditional` rule;
- the window is `incomplete` with no match;
- the only match is `same_batch`;
- the load is `version_core` and the rule is outside the stable core;
- the rule is unsupported.

Unknown SHALL never be mapped to failure.

#### Scenario: Session ends early
- **WHEN** a session ends 3 steps after a load with no match
- **THEN** the row is `insufficient_evidence` with reason `incomplete_window`

### Requirement: Not applicable status
A row SHALL have status `not_applicable` when the rule's applicability predicate is known to be false. These rows SHALL be excluded from all denominators and counted separately.

#### Scenario: Conditional rule without its trigger
- **WHEN** a rule applies only after `terminal: git merge` and no merge occurred in the window
- **THEN** the row is `not_applicable` and is absent from adherence denominators

### Requirement: Status chart and evidence report
The report SHALL include, per skill, a stacked chart of the four statuses with denominators, and a Markdown section listing audited example rows for each status with their reason codes. It SHALL also list excluded loads by exclusion reason.

#### Scenario: Fallback demo
- **WHEN** the expectation model cannot be fitted for a corpus
- **THEN** the status chart and evidence section are still produced for that corpus

### Requirement: Selection-bias disclosure
The report SHALL state that the evidence covers only loaded episodes, and SHALL make no claim about skills that were available but not loaded.

#### Scenario: Disclosure present
- **WHEN** the summary is generated
- **THEN** it contains the loaded-episodes-only disclosure
