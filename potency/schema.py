"""Single source of truth for the intermediate tables, outputs and enums (design D12, D18, D19, D21).

Stdlib only: imported by source-machine stages.

Data-dir layout (one directory per corpus):

    <data_dir>/<corpus>/
        sessions.jsonl  steps.jsonl  loads.jsonl  skill_versions.jsonl  rules.jsonl  provenance.jsonl
        manifest.json  census.json  checksums.sha256          (source stages)
        out/evidence.csv  out/expected.csv  out/expect_eval.json
        out/potency.csv  out/strata.csv  out/experiments.json
        out/potency.png  out/status.png  out/summary.md      (analysis stages)

Conventions:
- Timestamps are epoch seconds (float). Steps are 0-based within a session.
- ``load_id`` is the pseudonymous episode id: ``episode_id(corpus, session_id, step)``.
- ``null`` applicability on a rule means "unknown"; an empty list means "always applies".
"""
from __future__ import annotations

import hashlib

# ---------------------------------------------------------------- parameters (design D10)
WINDOW_N = 10
SENSITIVITY_N = (5, 20)
CONTEXT_K = 3
PLACEBO_K = 20
SEED = 148
BASE_RATE_CEILING = 0.2
FAMILIARITY_CUTOFFS = (0.0, 0.02)  # novel == 0, occasional <= 0.02, habitual > 0.02
MIN_RANKED_LOADS = 2
MIN_SUPPORTED_LOADS = 5
MIN_SUPPORTED_CLUSTERS = 3
TRAIN_SHARE = 0.7
BOOTSTRAP_RESAMPLES = 1000
POPULARITY_FLAG_RHO = 0.5
STRATUM_MIN_LOADS = 10

# ---------------------------------------------------------------- enums
SPLITS = ("train", "test")
PAIR_ARMS = ("with_skill", "without_skill")
PRIVACY_CLASSES = ("private", "public")
STEP_KINDS = ("shell", "tool", "load")
STEP_STATUSES = ("ok", "error", "unknown")
TRIGGERS = ("preloaded", "instructed", "chosen")
VERSION_SOURCES = ("injected", "ledger", "skill_manage", "version_core", "version_unknown")
LOAD_FLAGS = ("maintenance", "repeat", "incomplete", "overlap")
OBLIGATIONS = ("required", "conditional", "optional", "example", "avoid")
SCORED_OBLIGATIONS = ("required", "conditional", "avoid")  # optional/example never get evidence rows
RULE_SOURCES = ("approved", "draft", "auto")
STATUSES = ("supported_agreement", "no_observed_agreement", "insufficient_evidence", "not_applicable")
REASONS = {
    "supported_agreement": ("matched", "matched_alternative"),
    "no_observed_agreement": ("no_match_complete_window",),
    "insufficient_evidence": (
        "applicability_unknown",
        "incomplete_window",
        "same_batch_only",
        "outside_core",
        "unsupported_rule",
    ),
    "not_applicable": ("applicability_false",),
}
FAMILIARITY = ("novel", "occasional", "habitual")
PRIOR_KNOWLEDGE = ("public", "local")
PROVENANCE_GROUPS = ("agent-touched", "no-agent-trace")
LIFT_LABELS = ("positive", "inconclusive", "negative")

# ---------------------------------------------------------------- tables
# Each table: ordered {column: type}. Types: str, int, float, bool, list[str], json, and "|None" for nullable.
TABLES: dict[str, dict[str, str]] = {
    "sessions": {
        "corpus": "str",
        "session_id": "str",
        "start_ts": "float",
        "source": "str|None",  # e.g. cron, telegram, cli; None when unknown
        "task_key": "str|None",  # D15
        "cluster_key": "str",  # D21
        "model": "str|None",
        "harness_version": "str|None",
        "pair_id": "str|None",  # paired with/without-skill runs (D7 S3); None when unpaired
        "pair_arm": "str|None",  # PAIR_ARMS when pair_id is set
        "split": "str",  # SPLITS
    },
    "steps": {
        "corpus": "str",
        "session_id": "str",
        "step": "int",  # 0-based step offset within the session (after compound-command expansion)
        "source_offset": "int",  # offset of the originating record in the source log
        "call_id": "str",
        "batch_id": "str",  # same value for calls issued in one assistant message
        "ts": "float|None",
        "kind": "str",  # STEP_KINDS
        "signature": "str",  # normalize.py output; for kind=load: "load: <skill>"
        "status": "str",  # STEP_STATUSES
        "attribution_skill": "str|None",  # Claude Code attributionSkill hint, else None
    },
    "loads": {
        "corpus": "str",
        "session_id": "str",
        "load_id": "str",  # episode_id(corpus, session_id, step)
        "skill": "str",
        "step": "int",  # step of the load (0 for preloaded)
        "ts": "float|None",
        "trigger": "str",  # TRIGGERS
        "version_id": "str|None",
        "version_source": "str",  # VERSION_SOURCES
        "flags": "list[str]",  # LOAD_FLAGS, sorted
        "cluster_key": "str",
        "split": "str",
    },
    "skill_versions": {
        "corpus": "str",
        "skill": "str",
        "version_id": "str",
        "version_source": "str",
        "valid_from_ts": "float|None",
        "content_sha256": "str|None",
    },
    "rules": {
        "corpus": "str",
        "skill": "str",
        "version_id": "str",
        "rule_id": "str",
        "obligation": "str",  # OBLIGATIONS
        "applicability": "list[str]|None",  # None = unknown, [] = always
        "observable": "list[str]",  # acceptable signatures (or tool names)
        "alternatives": "list[str]",
        "location": "str|None",  # e.g. "section 2"
        "rule_source": "str",  # RULE_SOURCES
        "approved": "bool",
        "in_core": "bool|None",  # for version_core loads: False => evidence reason outside_core; None if n/a
    },
    "provenance": {
        "corpus": "str",
        "skill": "str",
        "created_ts": "float|None",
        "created_by": "str|None",
        "agent_touched": "bool",
        "changes": "json",  # list of {"ts", "actor", "action", "added": [sig], "removed": [sig]}
    },
}

# ---------------------------------------------------------------- outputs
OUTPUT_COLUMNS: dict[str, list[str]] = {
    "evidence.csv": [
        "corpus", "load_id", "session_id", "cluster_key", "skill", "version_id", "rule_id", "obligation",
        "window_start", "window_end", "status", "reason", "evidence_steps",  # evidence_steps: space-joined ints
    ],
    "expected.csv": ["corpus", "load_id", "rule_id", "p_hat"],
    "potency.csv": [
        "corpus", "skill", "n_loads", "n_clusters", "set_size", "follow_rate", "mean_a", "mean_a_hat",
        "lift", "lift_shrunk", "ci_low", "ci_high", "placebo_lift", "avoid_matches", "label",
        "supported", "ranked", "generic_only", "auto", "provenance_group",
    ],
    "strata.csv": ["corpus", "familiarity", "prior_knowledge", "n_loads", "lift", "ci_low", "ci_high", "pooled"],
}
OUTPUT_FILES = (
    "evidence.csv", "expected.csv", "expect_eval.json", "potency.csv", "strata.csv",
    "experiments.json", "potency.png", "status.png", "summary.md",
)
SOURCE_FILES = tuple(f"{t}.jsonl" for t in TABLES) + ("manifest.json", "census.json")
CHECKSUMS_FILE = "checksums.sha256"


def episode_id(corpus: str, session_id: str, step: int) -> str:
    """Pseudonymous, deterministic load id."""
    return hashlib.sha256(f"{corpus}\x1f{session_id}\x1f{step}".encode("utf-8")).hexdigest()[:16]


def content_id(text: str) -> str:
    """Version id for a skill body (sha256 prefix of its utf-8 text)."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _type_ok(value, typ: str) -> bool:
    nullable = typ.endswith("|None")
    base = typ[: -len("|None")] if nullable else typ
    if value is None:
        return nullable
    if base == "str":
        return isinstance(value, str)
    if base == "int":
        return isinstance(value, int) and not isinstance(value, bool)
    if base == "float":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if base == "bool":
        return isinstance(value, bool)
    if base == "list[str]":
        return isinstance(value, list) and all(isinstance(x, str) for x in value)
    if base == "json":
        return True
    raise ValueError(f"unknown type {typ}")


_ENUM_COLUMNS = {
    ("sessions", "split"): SPLITS,
    ("sessions", "pair_arm"): PAIR_ARMS + (None,),
    ("steps", "kind"): STEP_KINDS,
    ("steps", "status"): STEP_STATUSES,
    ("loads", "trigger"): TRIGGERS,
    ("loads", "version_source"): VERSION_SOURCES,
    ("loads", "split"): SPLITS,
    ("skill_versions", "version_source"): VERSION_SOURCES,
    ("rules", "obligation"): OBLIGATIONS,
    ("rules", "rule_source"): RULE_SOURCES,
}


def validate_row(table: str, row: dict) -> list[str]:
    """Return a list of problems (empty when the row matches the table contract)."""
    cols = TABLES[table]
    problems = []
    missing = [c for c in cols if c not in row]
    extra = [c for c in row if c not in cols]
    if missing:
        problems.append(f"missing {missing}")
    if extra:
        problems.append(f"extra {extra}")
    for c, typ in cols.items():
        if c in row and not _type_ok(row[c], typ):
            problems.append(f"{c}: {row[c]!r} is not {typ}")
        enum = _ENUM_COLUMNS.get((table, c))
        if enum and c in row and row[c] not in enum:
            problems.append(f"{c}: {row[c]!r} not in {enum}")
    if table == "loads" and isinstance(row.get("flags"), list):
        bad = [f for f in row["flags"] if f not in LOAD_FLAGS]
        if bad:
            problems.append(f"flags: {bad} not in {LOAD_FLAGS}")
    return problems


def validate_rows(table: str, rows) -> None:
    """Raise ValueError on the first invalid row."""
    for i, row in enumerate(rows):
        p = validate_row(table, row)
        if p:
            raise ValueError(f"{table} row {i}: {'; '.join(p)}")
