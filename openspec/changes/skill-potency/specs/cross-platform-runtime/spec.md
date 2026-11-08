# Spec Delta

## Purpose

Lets any team member run the analysis stages on Windows, macOS or Linux with the same results. Kris (Windows) takes over from Justin (macOS) at about 18:00 for the 20:00 demo.

## ADDED Requirements

### Requirement: Supported platforms
Every analysis stage (expect, score, report, and the synthetic end-to-end run) SHALL run on Windows 10+, macOS 13+ and Linux with Python ≥3.12. It SHALL need only `pip install -r requirements.txt`, with no WSL, bash, make or SSH.

#### Scenario: Fresh Windows machine
- **WHEN** a user on Windows clones the repo, creates a venv and installs `requirements.txt`
- **THEN** `python -m potency.report --data <dir>` runs to completion on provided derived files

### Requirement: Python module entry points
Each stage SHALL run as `python -m potency.<stage>` with paths taken from CLI arguments or `POTENCY_DATA_DIR`. Shell scripts MAY exist as conveniences but SHALL NOT be required.

#### Scenario: No shell scripts
- **WHEN** a user runs the pipeline in PowerShell
- **THEN** every stage is invokable with documented `python -m` commands

### Requirement: Portable paths and file I/O
Code SHALL use `pathlib` for paths and SHALL NOT hard-code `~`, `/tmp` or path separators. Every text read or write SHALL set `encoding="utf-8"`. Written text files SHALL use `\n` line endings. The repo SHALL include `.gitattributes` with `* text=auto eol=lf`. No symlinks SHALL be committed.

#### Scenario: CRLF checkout
- **WHEN** the repo is cloned on Windows with default git settings
- **THEN** JSONL and CSV files load identically to the macOS checkout

### Requirement: Platform-independent dependencies
`requirements.txt` SHALL pin versions of packages that publish wheels for all three platforms. Plotting SHALL use a non-interactive backend.

#### Scenario: Headless chart
- **WHEN** the report stage runs with no display
- **THEN** `potency.png` is written without error

### Requirement: Deterministic outputs across platforms
With the same inputs, every stage SHALL produce byte-identical CSV and JSON outputs on all three platforms: fixed seeds, sorted iteration and fixed float formatting.

#### Scenario: Cross-platform hash check
- **WHEN** the synthetic end-to-end run executes on Windows and on macOS
- **THEN** the SHA-256 of each CSV and JSON output matches

### Requirement: CI matrix
A GitHub Actions workflow SHALL run unit tests and the synthetic end-to-end run on ubuntu-latest, macos-latest and windows-latest for every pull request, and compare output hashes across platforms.

#### Scenario: Windows-only regression
- **WHEN** a pull request introduces a hard-coded `/tmp` path
- **THEN** the windows-latest job fails

### Requirement: Handover runbook
The repo SHALL contain `docs/runbook.md` with copy-paste setup and run commands for PowerShell and for bash/zsh, how to unpack a derived-data bundle, how to regenerate the report, and the current state of tasks.

#### Scenario: 18:00 handover
- **WHEN** Kris starts on Windows with only the repo and the derived-data location
- **THEN** he can regenerate the chart and summary by following the runbook alone
