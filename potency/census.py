"""Source machine, stdlib only: outcome-free counts (corpus-intake spec) -> census.json.

The census gates analysis (design D12): it describes what a corpus contains without computing any
adherence, follow-through or lift, so thresholds can be set before outcomes are seen. A load is
*scorable* when it could ever produce an evidence row: not a maintenance or repeat load, with a known
version and at least one rule. Window flags (incomplete, overlap) stay in the census as flags because
they only feed the sensitivity runs, not the main estimate.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from potency import io, normalize, schema


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog='python -m potency.census', description='Source machine, stdlib only: outcome-free counts (corpus-intake spec) -> census.json.')
    p.add_argument('--corpus', required=True, help='corpus name')
    p.add_argument('--data', default=None, help='data dir (default $POTENCY_DATA_DIR or ./data)')
    return p


def _count_into(counter: dict, key, n: int = 1) -> None:
    counter[key] = counter.get(key, 0) + n


def _usable_rules_per_version(rules: list[dict]) -> dict[tuple[str, str], int]:
    """Rules that could ever match a step: a rule with no observable and no alternative never can."""
    counts: dict[tuple[str, str], int] = {}
    for rule in rules:
        if rule.get("observable") or rule.get("alternatives"):
            key = (rule["skill"], rule["version_id"])
            counts[key] = counts.get(key, 0) + 1
    return counts


def _exclusion_reasons(load: dict, rules_by_version: dict[tuple[str, str], int]) -> list[str]:
    flags = load.get("flags") or []
    reasons = []
    if "maintenance" in flags:
        reasons.append("maintenance")
    if "repeat" in flags:
        reasons.append("repeat")
    if load.get("version_source") == "version_unknown" or not load.get("version_id"):
        reasons.append("version_unknown")
    elif not rules_by_version.get((load["skill"], load["version_id"])):
        reasons.append("no_rules")
    return reasons


def build_census(corpus_dir, corpus: str | None = None) -> dict:
    corpus_dir = Path(corpus_dir)
    corpus = corpus or corpus_dir.name
    sessions = io.read_table(corpus_dir, "sessions")
    steps = io.read_table(corpus_dir, "steps")
    loads = io.read_table(corpus_dir, "loads")
    rules = io.read_table(corpus_dir, "rules")
    versions = io.read_table(corpus_dir, "skill_versions")
    provenance = {row["skill"]: row for row in io.read_table(corpus_dir, "provenance")}
    manifest_path = corpus_dir / "manifest.json"
    manifest = io.read_json(manifest_path) if manifest_path.exists() else {}

    rules_by_version = _usable_rules_per_version(rules)
    provenance_group = {skill: row.get("agent_touched") for skill, row in provenance.items()}

    excluded: dict[str, int] = {}
    flagged: dict[str, int] = {}
    triggers: dict[str, int] = {}
    load_sources: dict[str, int] = {}
    skills: dict[str, dict] = {}
    scorable = 0
    for load in loads:
        reasons = _exclusion_reasons(load, rules_by_version)
        for reason in reasons:
            _count_into(excluded, reason)
        for flag in load.get("flags") or []:
            if flag in ("incomplete", "overlap"):
                _count_into(flagged, flag)
        _count_into(triggers, load["trigger"])
        _count_into(load_sources, load["version_source"])
        ok = not reasons
        scorable += int(ok)
        entry = skills.setdefault(load["skill"], {
            "skill": load["skill"],
            "raw_loads": 0,
            "scorable_loads": 0,
            "sessions": set(),
            "clusters": set(),
            "triggers": {},
            "version_sources": {},
            "flags": {},
            "agent_touched": provenance_group.get(load["skill"]),
        })
        entry["raw_loads"] += 1
        entry["scorable_loads"] += int(ok)
        entry["sessions"].add(load["session_id"])
        entry["clusters"].add(load["cluster_key"])
        _count_into(entry["triggers"], load["trigger"])
        _count_into(entry["version_sources"], load["version_source"])
        for flag in load.get("flags") or []:
            _count_into(entry["flags"], flag)

    for entry in skills.values():
        entry["n_sessions"] = len(entry.pop("sessions"))
        entry["n_clusters"] = len(entry.pop("clusters"))
        entry["rule_rows"] = sum(n for (skill, _), n in rules_by_version.items() if skill == entry["skill"])

    programs: dict[str, int] = {}
    tools: dict[str, int] = {}
    step_kinds: dict[str, int] = {}
    step_statuses: dict[str, int] = {}
    for step in steps:
        _count_into(step_kinds, step["kind"])
        _count_into(step_statuses, step["status"])
        if step["kind"] == "shell":
            program = normalize.program_of(step["signature"])
            if program:
                _count_into(programs, program)
        elif step["kind"] == "tool":
            _count_into(tools, step["signature"])

    by_source: dict[str, int] = {}
    by_split: dict[str, int] = {}
    with_task_key = 0
    clusters: set[str] = set()
    for session in sessions:
        _count_into(by_source, session.get("source") or "unknown")
        _count_into(by_split, session["split"])
        clusters.add(session["cluster_key"])
        with_task_key += int(bool(session.get("task_key")))

    version_sources: dict[str, int] = {}
    skills_with_versions: set[str] = set()
    for row in versions:
        _count_into(version_sources, row["version_source"])
        skills_with_versions.add(row["skill"])

    preloaded = [load for load in loads if load["trigger"] == "preloaded"]
    cron_sessions = [session for session in sessions if (session.get("source") or "") == "cron"]
    source_meta = manifest.get("source") or {}

    min_loads = 100
    min_skills = 10
    skills_with_five = sum(1 for entry in skills.values() if entry["scorable_loads"] >= schema.MIN_SUPPORTED_LOADS)
    census = {
        "corpus": corpus,
        "generated_by": "potency.census",
        "outcome_free": True,
        "note": "counts only; no adherence, follow-through or lift is computed here",
        "parameters": {
            "window_n": schema.WINDOW_N,
            "context_k": schema.CONTEXT_K,
            "train_share": schema.TRAIN_SHARE,
            "min_supported_loads": schema.MIN_SUPPORTED_LOADS,
        },
        "snapshot": {
            "max_message_id": manifest.get("max_message_id"),
            "max_timestamp": manifest.get("max_timestamp"),
            "split_cutoff_ts": manifest.get("split_cutoff_ts"),
            "extractor_git_sha": manifest.get("extractor_git_sha"),
            "row_counts": manifest.get("row_counts") or {},
        },
        "sessions": {
            "total": len(sessions),
            "by_source": dict(sorted(by_source.items())),
            "by_split": dict(sorted(by_split.items())),
            "with_task_key": with_task_key,
            "distinct_clusters": len(clusters),
        },
        "steps": {
            "total": len(steps),
            "by_kind": dict(sorted(step_kinds.items())),
            "by_status": dict(sorted(step_statuses.items())),
        },
        "loads": {
            "total": len(loads),
            "scorable": scorable,
            "excluded_by_reason": dict(sorted(excluded.items())),
            "flagged": dict(sorted(flagged.items())),
            "triggers": dict(sorted(triggers.items())),
            "version_sources": dict(sorted(load_sources.items())),
        },
        "skills": [skills[name] for name in sorted(skills)],
        "skill_count": len(skills),
        "rules": {
            "total": len(rules),
            "usable": sum(rules_by_version.values()),
            "versions_with_rules": len(rules_by_version),
            "skills_with_versions": len(skills_with_versions),
            "loads_without_rules": sum(1 for load in loads
                                       if not rules_by_version.get((load["skill"], load["version_id"]))),
        },
        "versions": {
            "rows": len(versions),
            "by_source": dict(sorted(version_sources.items())),
        },
        "preload": {
            "cron_sessions": len(cron_sessions),
            "cron_sessions_mapped": source_meta.get("cron_sessions_mapped"),
            "preloaded_loads": len(preloaded),
            "sessions_with_preload": len({load["session_id"] for load in preloaded}),
            "skills": sorted({load["skill"] for load in preloaded}),
        },
        "ledger": source_meta.get("ledger") or {},
        "programs": [{"program": p, "steps": n} for p, n in sorted(programs.items(), key=lambda kv: (-kv[1], kv[0]))],
        "tools": [{"tool": t, "steps": n} for t, n in sorted(tools.items(), key=lambda kv: (-kv[1], kv[0]))],
        "eligibility": {
            "min_scorable_loads": min_loads,
            "min_skills_with_five_loads": min_skills,
            "scorable_loads": scorable,
            "skills_with_five_loads": skills_with_five,
            "meets_bar": scorable >= min_loads and skills_with_five >= min_skills,
        },
    }
    return census


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    corpus_dir = io.resolve_data_dir(args.data) / args.corpus
    census = build_census(corpus_dir, args.corpus)
    io.write_json(corpus_dir / "census.json", census)
    loads = census["loads"]
    print(f"census\t{corpus_dir / 'census.json'}")
    print(f"loads\t{loads['total']} scorable\t{loads['scorable']} skills\t{census['skill_count']}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
