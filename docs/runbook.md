# Runbook: run the potency pipeline on any OS

Covers the three platforms in the `cross-platform-runtime` spec: Windows 10+, macOS 13+ and Linux, with
Python >= 3.12. No WSL, bash, make or SSH is needed: every stage is a `python -m` command (design D17).
Kris takes over on Windows at about 18:00; the 18:00 handover section is at the bottom.

Replace `hermes-orin` with your corpus name (`swechat-v1`, `synth`, ...) and `derived-hermes-orin-ab12cd34.zip`
with the bundle you were given.

## 0. Prerequisites

- Python 3.12 or newer (`python --version`, or `py -3.12 --version` on Windows). The pinned numpy and scipy
  publish no Python 3.11 wheels.
- `git`.
- About 2 GB of free disk and a short path for the clone (`C:\h148`, not a deep `Documents` path).

## 1. Setup

### PowerShell (Windows)

```powershell
git clone https://github.com/JTP75/sundai148.git C:\h148
cd C:\h148
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

If activation is blocked, see [Execution policy](#execution-policy) below.

### bash / zsh (macOS, Linux)

```bash
git clone https://github.com/JTP75/sundai148.git ~/h148
cd ~/h148
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Everything below assumes the venv is active in the repo root. `python -m pytest -q` should pass before you
touch any data.

## 2. Unpack the derived-data bundle into `data\`

The data session packs one corpus per bundle: `derived-<corpus>-<manifest hash>.zip`, containing the
harness-neutral JSONL tables, `manifest.json` and a `checksums.sha256` list. Raw private logs and skill text
are never in it.

### PowerShell

```powershell
# put the zip next to the repo first, e.g. Downloads\derived-hermes-orin-ab12cd34.zip
Expand-Archive -Path .\derived-hermes-orin-ab12cd34.zip -DestinationPath .\data -Force

# expected end state: data\<corpus>\sessions.jsonl
Get-ChildItem .\data
Test-Path .\data\hermes-orin\sessions.jsonl
```

`Expand-Archive` cannot overwrite a file it has open; close any viewer first. It also rejects paths longer
than 260 characters, so unzip into `C:\h148\data` rather than a deep folder.

### bash / zsh

```bash
unzip -o derived-hermes-orin-ab12cd34.zip -d data
# expected end state: data/<corpus>/sessions.jsonl
ls data
test -f data/hermes-orin/sessions.jsonl && echo ok
```

Some bundles carry the corpus directory inside the archive root. If `data/sessions.jsonl` appears instead of
`data/<corpus>/sessions.jsonl`, move it: `mv data/sessions.jsonl data/hermes-orin/` (PowerShell:
`New-Item -ItemType Directory data\hermes-orin; Move-Item data\sessions.jsonl data\hermes-orin\`).

## 3. Verify the checksums

`run_all` verifies `data/<corpus>/checksums.sha256` automatically and stops on the first bad file name, so
this step is optional. Run it explicitly only when you want to check before the pipeline.

### PowerShell

```powershell
$dir = ".\data\hermes-orin"
Get-Content "$dir\checksums.sha256" | ForEach-Object {
  $digest, $name = $_ -split '  ', 2
  $actual = (Get-FileHash -Algorithm SHA256 -Path (Join-Path $dir $name)).Hash.ToLower()
  if ($actual -ne $digest) { Write-Host "MISMATCH $name" } else { Write-Host "ok $name" }
}
```

### bash / zsh

```bash
cd data/hermes-orin && sha256sum -c checksums.sha256; cd ../..
```

A mismatch means the copy is damaged or was edited. Re-download the bundle; do not "fix" the checksum list.

## 4. Run the pipeline

```powershell
python -m potency.run_all --data data --corpus hermes-orin
```

```bash
python -m potency.run_all --data data --corpus hermes-orin
```

Omit `--corpus` to process every corpus directory in `data/`. `run_all` verifies the checksums, then runs
`evidence -> expect -> score -> report` in one process and prints one line per stage. It exits non-zero when a
stage is missing its inputs, is still a stub, or fails: a partial run never looks green.

Single stage, when you only want to regenerate the chart and summary:

```powershell
python -m potency.report --data data --corpus hermes-orin
```

```bash
python -m potency.report --data data --corpus hermes-orin
```

Other stages are the same shape: `python -m potency.evidence`, `potency.expect`, `potency.score`. Pass
`--program-map <file>` to `score`/`report` once Justin's public/local program map is committed.

All stages read `--data`, else `$env:POTENCY_DATA_DIR` / `$POTENCY_DATA_DIR`, else `./data`.

## 5. Where the outputs land, and how to open them

Per corpus, under `data\<corpus>\out\`:

| File | What |
|---|---|
| `potency.png` | Ranked skills by shrunken lift with 95% CI bars, colored by provenance, `*` = supported |
| `status.png` | Per-skill stacked bars of the four evidence statuses, `n=` excludes `not_applicable` |
| `summary.md` | Three headline numbers, caveats, ranking table, example evidence rows, experiments, appendix |
| `evidence.csv`, `expected.csv`, `potency.csv`, `strata.csv`, `experiments.json`, `expect_eval.json` | Stage outputs, byte-identical across platforms |

### PowerShell

```powershell
Start-Process .\data\hermes-orin\out\potency.png
Start-Process .\data\hermes-orin\out\status.png
Get-Content .\data\hermes-orin\out\summary.md -Raw
```

### macOS / Linux

```bash
open data/hermes-orin/out/potency.png        # macOS
xdg-open data/hermes-orin/out/potency.png    # Linux
less data/hermes-orin/out/summary.md
```

The demo needs three numbers, all in the `## Headline numbers` table at the top of `summary.md`:
median lift on novel+local prescribed commands, agent-touched vs no-agent-trace lift, and the count of ranked
skills whose CI includes or is below zero. Read them with the endogeneity caveat directly below them.

## 6. Troubleshooting

### `Activate.ps1 cannot be loaded because running scripts is disabled`

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

`-Scope Process` affects only this window. Do not change the machine-wide policy for the demo.

### CRLF / "JSON decode error" / checksum mismatch after editing a file

The repo pins LF with `.gitattributes` (`* text=auto eol=lf`). Symptoms are usually a file edited with an
editor that saved CRLF, or a checkout made with `core.autocrlf=true` before `.gitattributes` existed:

```powershell
git config core.autocrlf false
git rm --cached -r . ; git reset --hard
```

Never hand-edit files in `data\`: re-download the bundle instead. `git diff --exit-code tests/fixtures` is the
same check CI runs, and it must print nothing.

### `Expand-Archive`: path too long

Clone shallow into a short root (`C:\h148`), and unpack into `C:\h148\data`. If long paths are still an issue:

```powershell
git config --system core.longpaths true   # needs an elevated shell
```

### `python` opens the Microsoft Store or is not found

Use the launcher: `py -3.12 -m venv .venv`, then `py -3.12 -m pip install -r requirements.txt`. After
activation, `python` points at the venv again.

### Matplotlib warnings about fonts, or no display

`potency.report` forces the Agg backend, so a headless machine is fine. "findfont" warnings are harmless.
If a PNG looks empty, confirm the run wrote `out/evidence.csv` first: the chart has no data without it.

### A stage says "is still a stub" and `run_all` exits 1

The merged branch has real `evidence`, `expect` and `score` stages, so this message means you are on an older
checkout or a branch that has not merged W3/W4 yet. Pull `main` (or the branch you were given) and re-run. If a
stage genuinely has no inputs, `run_all` names the missing files and exits 1 by design.

### `report: ... missing out/evidence.csv`

The report needs an evidence table before it can draw anything. Run `python -m potency.evidence --data data`
first (or the full `run_all`).

## 7. Current task state

The authoritative checklist is
[`openspec/changes/skill-potency/tasks.md`](../openspec/changes/skill-potency/tasks.md); only the orchestrator
ticks boxes there, at merge time. As of this runbook:

| Group | State |
|---|---|
| 0. Data gathering | 0.1-0.2 done; 0.3 (run the source stages on orin) and 0.4 (census gate) pending |
| 1. Foundation | Done and frozen (`schema`, `io`, `normalize`, fixtures) |
| 2. Hermes source stages (W1) | Merged to `main`: `extract`, `census`, `draft_rules`, `bundle`, `privacy` |
| 3. Claude Code adapter (W2) | Merged to `main`: adapter plus `corpora.yaml` |
| 4. Evidence and expectation (W3) | Merged to `main`: `evidence.py`, `expect.py` |
| 5. Scoring and experiments (W4) | Merged to `main`: `score.py` |
| 6. Report, CI, runbook (W5) | This PR: `report.py`, `run_all.py`, the CI matrix and this file |
| 7. Integration and real data | Pending: merge this PR, real-data run, approved maps, Windows reproduction |

The merged pipeline is complete: `run_all` verifies checksums, runs `evidence -> expect -> score -> report`,
and exits 0. The report's optional inputs still degrade to "not computable" notes, so a partial bundle (for
example evidence only) writes the status chart and the evidence section instead of failing. Re-run `run_all`
after each merge or bundle refresh.
