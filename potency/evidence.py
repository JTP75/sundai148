"""Analysis: D18 evidence layer -> out/evidence.csv.

One row per (scorable load x scored rule). Statuses: ``supported_agreement``,
``no_observed_agreement``, ``insufficient_evidence``, ``not_applicable``; unknown is never mapped to
failure. The window after a load is the next ``N`` steps, never the load's own batch.

Rule map (optional, ``--rule-map``): JSON with ``{"rules": [...]}`` (or a bare list) of rule rows in the
``rules`` table shape. Rules are grouped by ``(skill, version_id)``; a group takes effect only when every
rule in it is approved (``approved: true`` or ``rule_source: "approved"``). An unapproved/draft group is
ignored and the corpus rules stay in force, which is the ``auto`` treatment of design D13.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from potency import io, schema

SCORED_OBLIGATIONS = set(schema.SCORED_OBLIGATIONS)
EXCLUDED_FLAGS = {"maintenance", "repeat"}

_RULE_DEFAULTS = {
    "obligation": "required",
    "applicability": [],
    "observable": [],
    "alternatives": [],
    "location": None,
    "rule_source": "approved",
    "approved": True,
    "in_core": None,
}


def corpus_name(corpus_dir: Path) -> str:
    rows = io.read_table(corpus_dir, "sessions")
    if rows:
        return rows[0]["corpus"]
    return Path(corpus_dir).name


def steps_by_session(corpus_dir: Path) -> dict[str, list[dict]]:
    """Steps grouped by session, keyed by ``(session_id, step)``.

    A repeated key (paired arms that share a session id) keeps the later row: one step number
    identifies one position in one session, and the file order carries that arbitration.
    """
    keyed: dict[tuple[str, int], dict] = {}
    for st in io.read_table(corpus_dir, "steps"):
        keyed[(st["session_id"], st["step"])] = st
    by_sid: dict[str, list[dict]] = {}
    for (sid, _step), st in sorted(keyed.items(), key=lambda item: (item[0][0], item[0][1])):
        by_sid.setdefault(sid, []).append(st)
    return by_sid


def _prescribed(rules: list[dict]) -> frozenset[str]:
    out: set[str] = set()
    for r in rules:
        out.update(r.get("observable") or ())
        out.update(r.get("alternatives") or ())
    return frozenset(out)


def prescribed_sets(corpus_dir) -> dict[tuple[str, str], frozenset[str]]:
    """Prescribed signature set per (skill, version_id), plus a per-skill union under version "*"."""
    by_version: dict[tuple[str, str], list[dict]] = {}
    for r in io.read_table(corpus_dir, "rules"):
        by_version.setdefault((r["skill"], r["version_id"]), []).append(r)
    out = {k: _prescribed(v) for k, v in by_version.items()}
    union: dict[str, set[str]] = {}
    for (skill, _vid), sigs in out.items():
        union.setdefault(skill, set()).update(sigs)
    for skill, sigs in union.items():
        out[(skill, "*")] = frozenset(sigs)
    return out


def rules_by_key(corpus_dir: Path) -> dict[tuple[str, str], list[dict]]:
    out: dict[tuple[str, str], list[dict]] = {}
    for r in io.read_table(corpus_dir, "rules"):
        out.setdefault((r["skill"], r["version_id"]), []).append(r)
    return out


def read_rule_map(path) -> dict[tuple[str, str], list[dict]]:
    """Load an approved rule map; returns only the groups that may override the corpus rules."""
    data = io.read_json(path)
    entries = data.get("rules", []) if isinstance(data, dict) else data
    groups: dict[tuple[str, str], list[dict]] = {}
    for entry in entries:
        row = dict(entry)
        if "approved" in row:
            approved = bool(row["approved"])
        else:
            approved = row.get("rule_source", "approved") == "approved"
        for col, default in _RULE_DEFAULTS.items():
            row.setdefault(col, default)
        row["approved"] = approved
        row["rule_source"] = "approved" if approved else "auto"
        groups.setdefault((row["skill"], row["version_id"]), []).append(row)
    approved = {}
    for key, rows in groups.items():
        if all(r["approved"] for r in rows):
            approved[key] = sorted(rows, key=lambda r: r["rule_id"])
    return approved


def apply_rule_map(rules_by_key, rule_map, corpus: str):
    merged = dict(rules_by_key)
    for (skill, version_id), rows in rule_map.items():
        merged[(skill, version_id)] = [{**r, "corpus": r.get("corpus") or corpus} for r in rows]
    return merged


def _load_batch(step_row: dict | None) -> str | None:
    if step_row is not None and step_row.get("kind") == "load":
        return step_row.get("batch_id")
    return None


def _status_for_rule(rule, *, window, load_batch, complete, prefix_sigs):
    """D18 status contract for one rule. Returns (status, reason, evidence_steps)."""
    if not rule.get("observable"):
        return "insufficient_evidence", "unsupported_rule", []
    obs = set(rule["observable"])
    alt = set(rule.get("alternatives") or ())
    targets = obs | alt
    direct = [st["step"] for st in window if st["signature"] in obs and st["batch_id"] != load_batch]
    alts = [st["step"] for st in window if st["signature"] in alt and st["batch_id"] != load_batch]
    same = [
        st["step"] for st in window
        if st["signature"] in targets and load_batch is not None and st["batch_id"] == load_batch
    ]
    if direct:
        return "supported_agreement", "matched", sorted(direct)
    if alts:
        return "supported_agreement", "matched_alternative", sorted(alts)
    if same:
        return "insufficient_evidence", "same_batch_only", sorted(same)
    applicable: bool | None = True
    if rule["obligation"] == "conditional":
        applicability = rule.get("applicability")
        if applicability is None:
            applicable = None
        elif applicability:
            if prefix_sigs & set(applicability):
                applicable = True
            else:
                applicable = False if complete else None
    if applicable is None:
        return "insufficient_evidence", "applicability_unknown", []
    if applicable is False:
        return "not_applicable", "applicability_false", []
    if not complete:
        return "insufficient_evidence", "incomplete_window", []
    return "no_observed_agreement", "no_match_complete_window", []


def compute_evidence(corpus_dir, window: int = schema.WINDOW_N, rule_map=None) -> list[dict]:
    """D18 evidence rows for one corpus, sorted by (load_id, rule_id)."""
    corpus_dir = Path(corpus_dir)
    corpus = corpus_name(corpus_dir)
    by_sid = steps_by_session(corpus_dir)
    rules_idx = rules_by_key(corpus_dir)
    if rule_map:
        rules_idx = apply_rule_map(rules_idx, rule_map, corpus)

    rows: list[dict] = []
    for ld in io.read_table(corpus_dir, "loads"):
        if set(ld["flags"]) & EXCLUDED_FLAGS or ld["version_source"] == "version_unknown":
            continue
        steps = by_sid.get(ld["session_id"])
        if not steps:
            continue
        t = ld["step"]
        last = max(st["step"] for st in steps)
        w_end = min(t + window, last)
        complete = t + window <= last
        step_row = next((st for st in steps if st["step"] == t), None)
        load_batch = _load_batch(step_row)
        win = [st for st in steps if t < st["step"] <= w_end and st["kind"] != "load"]
        prefix_sigs = {st["signature"] for st in steps if st["step"] <= w_end}
        for rule in sorted(rules_idx.get((ld["skill"], ld["version_id"]), []), key=lambda r: r["rule_id"]):
            if rule["obligation"] not in SCORED_OBLIGATIONS:
                continue
            if ld["version_source"] == "version_core" and rule.get("in_core") is False:
                status, reason, evidence_steps = "insufficient_evidence", "outside_core", []
            else:
                status, reason, evidence_steps = _status_for_rule(
                    rule,
                    window=win,
                    load_batch=load_batch,
                    complete=complete,
                    prefix_sigs=prefix_sigs,
                )
            rows.append({
                "corpus": corpus,
                "load_id": ld["load_id"],
                "session_id": ld["session_id"],
                "cluster_key": ld["cluster_key"],
                "skill": ld["skill"],
                "version_id": ld["version_id"],
                "rule_id": rule["rule_id"],
                "obligation": rule["obligation"],
                "window_start": t + 1,
                "window_end": w_end,
                "status": status,
                "reason": reason,
                "evidence_steps": evidence_steps,
            })
    rows.sort(key=lambda r: (r["load_id"], r["rule_id"]))
    return rows


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m potency.evidence",
        description="Analysis: D18 evidence layer -> out/evidence.csv.",
    )
    p.add_argument("--corpus", default=None, help="corpus (default: every corpus in the data dir)")
    p.add_argument("--data", default=None, help="data dir")
    p.add_argument("--window", type=int, default=schema.WINDOW_N, help="window N")
    p.add_argument("--rule-map", default=None, help="approved rule map JSON (overrides listed skill versions)")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    rule_map = read_rule_map(args.rule_map) if args.rule_map else None
    data_dir = io.resolve_data_dir(args.data)
    for corpus_dir in io.corpus_dirs(data_dir, args.corpus):
        rows = compute_evidence(corpus_dir, window=args.window, rule_map=rule_map)
        io.write_output_csv(corpus_dir / "out" / "evidence.csv", rows)
        print(f"{corpus_dir.name}: {len(rows)} evidence rows -> {corpus_dir / 'out' / 'evidence.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
