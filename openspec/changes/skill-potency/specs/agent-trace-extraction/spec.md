# Spec Delta

## Purpose

Turns one corpus's session logs into the intermediate format: ordered steps with command signatures, skill-load records with the prescribed set in force at load time, no-load control windows and skill provenance. It must not leak secrets or future data into training. Corpus registration, privacy classes, snapshots and the census are in `corpus-intake`.

## ADDED Requirements

### Requirement: Command signature normalization
Each tool call SHALL be reduced to a command signature: the tool name plus, for shell commands, the program and its subcommand. Programs on a fixed known-CLI list SHALL keep up to two subcommand levels. Arguments, paths, flag values and quoted strings SHALL be dropped. Compound shell commands SHALL yield one signature per segment.

#### Scenario: Shell command with arguments
- **WHEN** a terminal tool call runs `git rebase -i HEAD~3`
- **THEN** its signature is `terminal: git rebase`

#### Scenario: Multi-level CLI
- **WHEN** a terminal call runs `gh pr create --fill`
- **THEN** its signature is `terminal: gh pr create`, and a later `gh pr view` does not match it

#### Scenario: Compound command
- **WHEN** a terminal call runs `cd repo && pytest -q`
- **THEN** it yields `terminal: cd` and `terminal: pytest` as consecutive steps

#### Scenario: Non-shell tool
- **WHEN** a `read_file` tool call reads `/home/x/notes.md`
- **THEN** its signature is `read_file` and contains no path

#### Scenario: Secret-bearing command
- **WHEN** a command contains a token, key, or URL with credentials
- **THEN** none of that text appears in any extracted artifact

### Requirement: Stable step ordering
Steps SHALL be ordered by source sequence (message order, then position within the tool-call list) and SHALL carry a stable call id, the source offset, the step offset and the assistant batch id. Each request SHALL be joined to its result. Shell steps SHALL be recorded as command attempts, with exit status when available.

#### Scenario: Parallel calls in one batch
- **WHEN** one assistant message issues three tool calls
- **THEN** they become three consecutive steps sharing one batch id, in list order

### Requirement: Successful loads only
A skill load SHALL count only when its result is non-error. Commands in the same assistant batch as the load SHALL be flagged `same_batch` and SHALL NOT count toward that load's adherence.

#### Scenario: Load fails
- **WHEN** a `skill_view` result reports that the skill was not found
- **THEN** no load is recorded

#### Scenario: Same-batch command
- **WHEN** `skill_view gog-cli` and `gog tasks list` are issued in the same assistant message
- **THEN** the `gog tasks list` step is flagged `same_batch` for that load

### Requirement: Prescribed set from the skill version at load time
Each load SHALL record the version id of the skill text in force at its timestamp. Version sources SHALL be tried in this order:
1. curator-ledger replay with full text;
2. replay of `skill_manage` calls in the session log;
3. the stable core, flagged `version_core`: commands present in both the earliest known and the current version.

A load SHALL be flagged `version_unknown` only when no source applies.

#### Scenario: Command added by a later patch
- **WHEN** a patch after the load adds `gh pr create` to the skill
- **THEN** that load's prescribed set does not contain `terminal: gh pr create`

#### Scenario: Load before the ledger existed
- **WHEN** a load predates 2026-10-01 and an earlier `skill_manage` call recorded the skill's text
- **THEN** the load uses the text replayed from that call

#### Scenario: No version text anywhere
- **WHEN** neither replay applies
- **THEN** the prescribed set is the stable core and the load is flagged `version_core`

### Requirement: Rule map with obligation types
Each rule SHALL carry: rule id, skill, version id, obligation type (`required`, `conditional`, `optional`, `example`, `avoid`), applicability predicate (or `unknown`), observable predicate, and allowed alternatives. Rules SHALL come from the approved rule map when one exists, and otherwise from auto-extraction (see scenarios).

#### Scenario: Example block in an approved map
- **WHEN** the approved map types `terminal: gog auth login` as `example` for `gog-cli`
- **THEN** that rule is not scored for `gog-cli` loads

#### Scenario: Skill without commands
- **WHEN** an unaudited SKILL.md has no code blocks or recognizable commands
- **THEN** the load is recorded with an empty rule set and flagged not scorable

#### Scenario: Unaudited skill
- **WHEN** a skill has no approved map
- **THEN** rules come from its code blocks and inline backticks, each typed `required` with applicability `unknown`, and the skill is flagged `auto`

### Requirement: Agent-drafted, human-approved rule map
A drafting stage on the source machine SHALL produce a draft rule map from versioned skill text, exporting no skill text. A human reviewer SHALL approve or edit each rule, and the approval SHALL be recorded in the map file. No adherence SHALL be computed from unapproved rules, except as `auto` rules.

#### Scenario: Draft not yet approved
- **WHEN** the scoring stage runs and a drafted rule lacks approval
- **THEN** the rule is treated as `auto` and the skill is flagged `auto`

### Requirement: Maintenance and repeat loads flagged
A load SHALL be flagged `maintenance` when `skill_manage` or a write to that skill's files on the same skill follows within N steps. It SHALL be flagged `repeat` when the same skill was already loaded earlier in the session.

#### Scenario: Load in order to edit
- **WHEN** a session loads `job-tracker` and then calls `skill_manage` on `job-tracker` 3 steps later
- **THEN** that load is flagged `maintenance` and is not scored for potency

### Requirement: Load trigger label
Each load SHALL be labeled:
- `preloaded`, when the harness put the skill in context without a load call;
- `instructed`, when the skill name appears in the user or cron prompt before it;
- `chosen`, otherwise.

For private corpora, the prompt scan SHALL run on the source machine and only the label SHALL be exported.

#### Scenario: Cron prompt names the skill
- **WHEN** a cron session's prompt mentions `manage-google-tasks` and the agent then loads it
- **THEN** that load is labeled `instructed`

#### Scenario: Detectable preload
- **WHEN** a cron job's configuration attaches skill `job-tracker`
- **THEN** each of that job's sessions has a `preloaded` load at step 0

### Requirement: Window flags
Each load's window SHALL be flagged `incomplete` when the session ends before N steps, and `overlap` when another skill load occurs inside it. Another load SHALL NOT close the window.

#### Scenario: Overlapping loads
- **WHEN** skill B loads 4 steps after skill A
- **THEN** A's window still spans N steps and is flagged `overlap`

### Requirement: No-load control windows
The extractor SHALL emit, for every step position, the next N signatures, the previous k signatures, the session source, the task key and the set of skills loaded or preloaded in the previous N steps.

#### Scenario: Window excludes a recent load
- **WHEN** skill `gog-cli` was loaded 4 steps before a position
- **THEN** that position's window lists `gog-cli` among recent loads and is not a no-load control for `gog-cli`

### Requirement: Task key
Each session SHALL carry a task key from the first available source:
1. a cron job id;
2. a hash of the normalized first user or cron prompt (digits and dates stripped), computed on the source machine;
3. none.

#### Scenario: Cron session without a job id
- **WHEN** a cron session has no job id
- **THEN** its task key is the prompt hash, and no prompt text is exported

### Requirement: Skill provenance
The extractor SHALL emit per skill: the creation date, `created_by` as recorded (with the caveat that it is not proof of authorship), the agent-touched flag, and the dated list of signatures added or removed by each recorded change.

#### Scenario: Agent-created skill
- **WHEN** `.usage.json` records `created_by: agent` for a skill
- **THEN** the provenance output carries that value, its creation date, and `agent-touched: true`

### Requirement: Temporal split
Within each corpus, every session and load SHALL be assigned to exactly one of `train` or `test` by session start time, using a single cutoff. No random split SHALL be used.

#### Scenario: Cutoff assignment
- **WHEN** a session starts after the cutoff
- **THEN** it and its loads are in `test`, and none of its steps contribute to base rates, weights, strata, vocabulary or model fitting
