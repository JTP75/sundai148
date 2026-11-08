# Spec Delta

## Purpose

Turns an agent's private session log into inputs for expectation and potency analysis: command signatures, ordered histories, skill-load records with the prescribed set in force at load time, no-load control windows and skill provenance. It must not leak secrets or future data into training.

## ADDED Requirements

### Requirement: Read-only access to the session log
The extractor SHALL open the session database and skill metadata files read-only and SHALL NOT modify them.

#### Scenario: Extraction leaves the source unchanged
- **WHEN** the extractor runs against `state.db`
- **THEN** the database file's contents and modification time are unchanged afterwards

### Requirement: Command signature normalization
Each tool call SHALL be reduced to a command signature: the tool name plus, for shell commands, the program and its subcommand (if any). Arguments, paths, flag values, and quoted strings SHALL be dropped from the signature.

#### Scenario: Shell command with arguments
- **WHEN** a terminal tool call runs `git rebase -i HEAD~3`
- **THEN** its signature is `terminal: git rebase`

#### Scenario: Non-shell tool
- **WHEN** a `read_file` tool call reads `/home/x/notes.md`
- **THEN** its signature is `read_file` and contains no path

#### Scenario: Secret-bearing command
- **WHEN** a command contains a token, key, or URL with credentials
- **THEN** none of that text appears in any extracted artifact

### Requirement: Ordered session histories
Each session SHALL become an ordered (oldest-first) list of steps, each with its signature, position, and, for skill loads, the skill name.

#### Scenario: Mixed session
- **WHEN** a session searches for "rebase", loads skill `git-workflow`, then runs `git rebase`
- **THEN** its history holds a `search_files` step, a load step for `git-workflow`, and a `terminal: git rebase` step, in that order

### Requirement: Prescribed set from the skill version at load time
For every skill load, the extractor SHALL record the session, the load position, the skill name, and the set of command signatures prescribed by the skill text **in force at the load's timestamp**, normalized with the same rule. When that version cannot be rebuilt, the load SHALL be flagged `version_unknown`, and the current text SHALL be used only if the load falls after the skill's last recorded change.

#### Scenario: Command added by a later patch
- **WHEN** a patch after the load adds `gh pr create` to the skill
- **THEN** that load's prescribed set does not contain `terminal: gh pr`

#### Scenario: Version not recoverable before last patch
- **WHEN** a load precedes the last patch and the earlier text cannot be rebuilt
- **THEN** the load is flagged `version_unknown` and excluded from potency scoring

#### Scenario: Skill without commands
- **WHEN** a loaded SKILL.md has no code blocks or recognizable commands
- **THEN** the load is recorded with an empty prescribed set and flagged as not scorable

### Requirement: Maintenance and repeat loads flagged
A load SHALL be flagged `maintenance` when `skill_manage` or a write to that skill's files on the same skill follows within N tool calls. A load SHALL be flagged `repeat` when the same skill was already loaded earlier in the session.

#### Scenario: Load in order to edit
- **WHEN** a session loads `job-tracker` and then calls `skill_manage` on `job-tracker` 3 calls later
- **THEN** that load is flagged `maintenance` and is not scored for potency

### Requirement: Load trigger label
Each load SHALL be labeled `instructed` when the skill name appears in the user or cron prompt that precedes it in the same turn, and `chosen` otherwise. Only the label SHALL be emitted, not the prompt text.

#### Scenario: Cron prompt names the skill
- **WHEN** a cron session's prompt mentions `manage-google-tasks` and the agent then loads it
- **THEN** that load is labeled `instructed`

### Requirement: No-load control windows
The extractor SHALL emit, for every step position, the window of the next N signatures, the previous k signatures, the session source, the recurring-task key when available, and the set of skills loaded in the previous N calls, so that controls without a given skill can be selected.

#### Scenario: Window excludes a recent load
- **WHEN** skill `gog-cli` was loaded 4 calls before a position
- **THEN** that position's window lists `gog-cli` among recent loads and is not used as a no-load control for `gog-cli`

### Requirement: Skill provenance
The extractor SHALL emit per skill: `created_at`, `created_by` (as recorded, with the caveat that it is not proof of authorship), patch count, and the dated list of signatures added or removed by each recorded change.

#### Scenario: Agent-created skill
- **WHEN** `.usage.json` records `created_by: agent` for a skill
- **THEN** the provenance output carries that value and its `created_at`

### Requirement: Temporal split
Every session and skill load SHALL be assigned to exactly one of `train` or `test` by session start time, using a single cutoff. No random split SHALL be used.

#### Scenario: Cutoff assignment
- **WHEN** a session starts after the cutoff
- **THEN** it and all its skill loads are in `test`, and none of its steps contribute to base rates, weights, strata, or model fitting
