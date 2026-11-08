# Spec Delta

## Purpose

Makes data gathering part of the pipeline. Agent logs from any harness, private or public, enter through adapters into one harness-neutral intermediate format. The source is read as a consistent snapshot, private text stays on its source machine, and an outcome-free census decides what is analyzable before any adherence is computed.

## ADDED Requirements

### Requirement: Corpus registry
Every corpus SHALL have an entry in `corpora.yaml` stating its name, harness, agent model(s) when known, date range, privacy class (`private` or `public`), source location, and, for public corpora, license and URL.

#### Scenario: Public corpus added
- **WHEN** the data session adds a public trajectory dataset
- **THEN** its registry entry includes license and URL before any of its data is used

### Requirement: Harness-neutral intermediate format
Each adapter SHALL emit the same tables (`sessions`, `steps`, `loads`, `skill_versions`, `provenance`) with the same columns and types. Analysis stages SHALL read only these tables and SHALL contain no harness-specific code.

#### Scenario: Second harness
- **WHEN** an OpenCode adapter is added
- **THEN** expectation, potency and report stages run on its output unchanged

### Requirement: Read-only consistent snapshot
Adapters SHALL open sources read-only and read each SQLite source in a single read transaction. Each extraction SHALL write `manifest.json` with max row ids, max timestamp, per-table row counts, split cutoff, and extractor git sha.

#### Scenario: Live database being written
- **WHEN** the source database receives new rows during extraction
- **THEN** the output reflects only rows visible at the transaction start, and the manifest records that state

### Requirement: Private-field allowlist
For `private` corpora, exported files SHALL contain only allowlisted fields: signatures, skill names, labels, flags, ids, hashes, counts and timestamps. Prompts, queries, skill descriptions, tool arguments and outputs SHALL NOT be exported. Sanitization SHALL run on the source machine, and a regex scan for tokens, URLs and paths SHALL run on outputs as a backstop.

#### Scenario: Search query
- **WHEN** a private session runs `search_files` with a query
- **THEN** the exported step is `search_files` with no query text

#### Scenario: Debug printing
- **WHEN** an operator inspects extraction during development
- **THEN** only signatures and counts are printed, never decoded arguments

### Requirement: Outcome-free census
Before analysis, each corpus SHALL produce `census.json` with:
- raw and scorable loads per skill;
- independent sessions per skill;
- exclusion counts by reason;
- version-source coverage;
- ledger `before`/`after` content type and sizes;
- task-key coverage;
- trigger counts;
- preload detection result;
- the program frequency list.

The census SHALL NOT compute adherence, follow-through or lift.

#### Scenario: Census reviewed
- **WHEN** the census is produced
- **THEN** it contains no field derived from matching prescribed commands to later steps

### Requirement: Eligibility bar
A corpus SHALL be ranked on its own only if it has ≥100 scorable loads and ≥10 skills with ≥5 scorable loads, or if it contains paired with/without-skill runs. Other corpora SHALL appear in the census and in pooled descriptive tables, labeled by corpus.

#### Scenario: Small corpus
- **WHEN** a corpus has 44 loads
- **THEN** it appears in the census and descriptive tables but gets no ranking chart
