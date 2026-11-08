# Spec Delta

## Purpose

Turns an agent's private session log into the inputs BehaviorGPT needs (a command catalog, ordered event histories, and skill-load records), without leaking secrets and without leaking future data into training.

## ADDED Requirements

### Requirement: Read-only access to the session log
The extractor SHALL open the session database read-only and SHALL NOT modify it.

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

### Requirement: Command catalog in BehaviorGPT format
The extractor SHALL emit one catalog parquet file with all 15 BehaviorGPT catalog columns. It SHALL have one row per distinct signature, a unique `id`, a human-readable `name`, `event_type` and `group` set to `product`, and null `image_url`.

#### Scenario: Catalog passes schema check
- **WHEN** the catalog file is produced
- **THEN** it passes the SDK's catalog schema check with no errors

#### Scenario: Popularity uses training data only
- **WHEN** `frequency` is filled for a catalog row
- **THEN** it counts only uses that fall in the training period

### Requirement: Event histories mapped by meaning
Each session SHALL become an ordered (oldest-first) list of events. A command run maps to a view of its catalog item, a search tool call maps to a search with its query text, and a skill load maps to a view of an out-of-catalog item named for the skill.

#### Scenario: Mixed session
- **WHEN** a session greps for "rebase", loads skill `git-workflow`, then runs `git rebase`
- **THEN** its history is `Search("rebase")`, `View(skill git-workflow, out-of-catalog)`, `View("terminal: git rebase")` in that order

### Requirement: Skill-load records with prescribed commands
For every skill load, the extractor SHALL record the session, the position of the load in the history, the skill name, and the set of command signatures its SKILL.md prescribes (taken from its code blocks and normalized with the same rule). A skill with no prescribed command SHALL be recorded with an empty set and flagged.

#### Scenario: Skill with code blocks
- **WHEN** a loaded SKILL.md contains a code block with `gh pr create --fill`
- **THEN** that load's prescribed set contains `terminal: gh pr`

#### Scenario: Skill without commands
- **WHEN** a loaded SKILL.md has no code blocks or recognizable commands
- **THEN** the load is recorded with an empty prescribed set and is flagged as not scorable for potency

### Requirement: Temporal split
Every session and skill load SHALL be assigned to exactly one of `train` or `test` by session start time, using a single cutoff. No random split SHALL be used.

#### Scenario: Cutoff assignment
- **WHEN** a session starts after the cutoff
- **THEN** it and all its skill loads are in `test`, and none of its events contribute to catalog popularity
