"""Analysis: D7 natural experiments -> the ``experiments`` block of out/experiments.json.

Four sections, each reporting ``{"computable": false, "reason": ...}`` when its inputs are missing:

- ``pre_post``      S1: difference-in-differences on keyed tasks before vs after skill creation,
                    split by provenance group;
- ``edit_response`` S2: does a command a change added move up after the change, relative to the
                    skill's unchanged commands?
- ``paired_runs``   S3: observational lift vs the with-minus-without difference on paired sessions,
                    with the gap as the endogeneity bias;
- ``trigger_split`` lift per ``instructed`` / ``chosen`` / ``preloaded`` load.

``run_experiments(corpus_dir)`` reads the corpus itself; ``score.py`` passes its already-loaded inputs,
prescribed sets and per-load scores to avoid a second pass.
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

from potency import io, schema

WINDOW = schema.WINDOW_N
SECTIONS = ("pre_post", "edit_response", "paired_runs", "trigger_split")


def _not_computable(reason: str) -> dict:
    return {"computable": False, "reason": reason}


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


# ------------------------------------------------------------------ shared helpers
def _context(corpus_dir, inputs, scores, sets):
    from potency import score

    if inputs is None:
        inputs = score.read_inputs(corpus_dir)
    if sets is None:
        sets = score.prescribed_sets(inputs, score.BaseRates(inputs))
    if scores is None:
        scores = score.score_loads(inputs, score.BaseRates(inputs))
    return inputs, scores, sets


def _rows(inputs, session_id: str) -> list[dict]:
    return inputs.steps.get(session_id, [])


def window_hit(rows: list[dict], targets: set[str], start: int, n: int = WINDOW) -> float | None:
    """1.0 when a target signature appears in the N steps after ``start``; None if no such steps."""
    if not rows or not targets:
        return None
    last = rows[-1]["step"]
    end = min(start + n, last)
    if end <= start:
        return None
    return 1.0 if any(st["kind"] != "load" and st["signature"] in targets
                      for st in rows if start < st["step"] <= end) else 0.0


def session_rate(rows: list[dict], targets: set[str], n: int = WINDOW) -> float | None:
    """Share of the session's complete N-step windows that contain a target signature."""
    if not rows or not targets:
        return None
    sigs = [st["signature"] for st in rows]
    if len(sigs) <= n:
        return 1.0 if any(sig in targets for sig in sigs) else 0.0
    hits = sum(1 for t in range(len(sigs) - n)
               if any(sig in targets for sig in sigs[t + 1: t + 1 + n]))
    return hits / (len(sigs) - n)


def _provenance(inputs, skill: str) -> str:
    from potency import score

    return score.provenance_group(inputs, skill)


def _loaded_sessions(inputs) -> set[str]:
    return {load["session_id"] for load in inputs.loads.values()}


# ------------------------------------------------------------------ S1: pre/post creation
def _pre_post(inputs, sets: dict[str, set[str]]) -> dict:
    keyed = sorted(sid for sid, s in inputs.sessions.items() if s["task_key"])
    if not keyed:
        return _not_computable("no sessions carry a task_key")
    loaded_sessions = defaultdict(set)
    for load in inputs.loads.values():
        loaded_sessions[load["skill"]].add(load["session_id"])
    skills = sorted(s for s in sets if s and inputs.provenance.get(s, {}).get("created_ts") is not None)
    if not skills:
        return _not_computable("no skill has both a creation date and a prescribed set")

    load_free = _loaded_sessions(inputs)
    rows, skipped = [], []
    for skill in skills:
        created = inputs.provenance[skill]["created_ts"]
        targets = sets[skill]
        tasks = {inputs.sessions[sid]["task_key"] for sid in loaded_sessions.get(skill, ())
                 if sid in inputs.sessions}
        treat = [sid for sid in keyed if inputs.sessions[sid]["task_key"] in tasks]
        # Control: keyed tasks that never got a skill (D7 S1). Their trend is the counterfactual.
        control = [sid for sid in keyed if sid not in treat and sid not in load_free]

        if not treat:
            skipped.append({"skill": skill, "reason": "no keyed session of a task that loads this skill"})
            continue
        pre_treat = _mean([session_rate(_rows(inputs, sid), targets) for sid in treat
                           if inputs.sessions[sid]["start_ts"] < created])
        post_treat = _mean([session_rate(_rows(inputs, sid), targets) for sid in treat
                            if inputs.sessions[sid]["start_ts"] >= created])
        if pre_treat is None or post_treat is None:
            skipped.append({"skill": skill, "reason": "missing pre- or post-creation treatment sessions"})
            continue
        pre_control = _mean([session_rate(_rows(inputs, sid), targets) for sid in control
                             if inputs.sessions[sid]["start_ts"] < created])
        post_control = _mean([session_rate(_rows(inputs, sid), targets) for sid in control
                              if inputs.sessions[sid]["start_ts"] >= created])
        did = None
        if pre_control is not None and post_control is not None:
            did = (post_treat - pre_treat) - (post_control - pre_control)
        rows.append({
            "skill": skill,
            "created_ts": created,
            "provenance_group": _provenance(inputs, skill),
            "pre_treat": pre_treat, "post_treat": post_treat,
            "pre_control": pre_control, "post_control": post_control,
            "n_treat": len(treat), "n_control": len(control),
            "did": did,
        })
    if not rows:
        return _not_computable("no skill has pre and post keyed treatment sessions")
    groups = defaultdict(list)
    for row in rows:
        if row["did"] is not None:
            groups[row["provenance_group"]].append(row["did"])
    payload = {
        "computable": True,
        "by_provenance": [{"provenance_group": g, "n_skills": len(v), "mean_did": _mean(v)}
                          for g, v in sorted(groups.items())],
        "rows": rows,
        "skipped": skipped,
    }
    if not groups:
        payload["note"] = "no keyed control task exists, so only the raw pre/post contrast is reported"
    return payload


# ------------------------------------------------------------------ S2: edit-response
def _edit_response(inputs, sets: dict[str, set[str]]) -> dict:
    changes = []
    for skill in sorted(inputs.provenance):
        for change in inputs.provenance[skill].get("changes") or []:
            added = list(change.get("added") or [])
            removed = list(change.get("removed") or [])
            if added or removed:
                changes.append((skill, change, added, removed))
    if not changes:
        return _not_computable("provenance records no added or removed signatures")

    def rates(skill: str, signature: str, ts: float):
        """Post-load hit rate for one signature before and after the change."""
        buckets = {"pre": [], "post": []}
        for load in inputs.loads.values():
            if load["skill"] != skill or load["ts"] is None:
                continue
            hit = window_hit(_rows(inputs, load["session_id"]), {signature}, load["step"])
            if hit is not None:
                buckets["pre" if load["ts"] < ts else "post"].append(hit)
        return buckets

    rows = []
    for skill, change, added, removed in changes:
        ts = change["ts"]
        touched = set(added) | set(removed)
        unchanged_deltas = []
        for sig in sorted(sets.get(skill, set()) - touched):
            buckets = _with_means(rates(skill, sig, ts))
            if buckets["pre_mean"] is not None and buckets["post_mean"] is not None:
                unchanged_deltas.append(buckets["post_mean"] - buckets["pre_mean"])
        unchanged_delta = _mean(unchanged_deltas)
        for kind, signatures in (("added", added), ("removed", removed)):
            for sig in signatures:
                buckets = _with_means(rates(skill, sig, ts))
                pre, post = buckets["pre_mean"], buckets["post_mean"]
                delta = (post - pre) if pre is not None and post is not None else None
                rows.append({
                    "skill": skill, "signature": sig, "kind": kind, "change_ts": ts,
                    "actor": change.get("actor"), "action": change.get("action"),
                    "pre_rate": pre, "post_rate": post,
                    "n_pre": buckets["n_pre"], "n_post": buckets["n_post"],
                    "delta": delta, "unchanged_delta": unchanged_delta,
                    "relative_delta": (delta - unchanged_delta)
                    if delta is not None and unchanged_delta is not None else None,
                })
    if not rows:
        return _not_computable("no change could be paired with pre and post loads")
    return {"computable": True, "rows": rows, "n_changes": len(changes)}


def _with_means(buckets: dict) -> dict:
    return {
        "pre_mean": _mean(buckets["pre"]), "post_mean": _mean(buckets["post"]),
        "n_pre": len(buckets["pre"]), "n_post": len(buckets["post"]),
    }


# ------------------------------------------------------------------ S3: paired runs
def _pair_arms(inputs) -> dict[str, dict[str, dict]]:
    """``pair_id -> {arm: session row}`` for pairs that hold both arms.

    Uses the sessions table as a list: the frozen fixture gives both arms the same ``session_id``
    (``with_skill`` and ``without_skill`` both truncate to ``with``), so a dict keyed by session id
    would drop one arm. Their step rows collide too and are told apart by timestamp.
    """
    pairs: dict[str, dict[str, dict]] = defaultdict(dict)
    for row in inputs.session_rows:
        if row["pair_id"]:
            pairs[row["pair_id"]][row["pair_arm"]] = row
    return {p: arms for p, arms in pairs.items()
            if "with_skill" in arms and "without_skill" in arms}


def _arm_rows(inputs, arms: dict[str, dict], arm: str) -> list[dict]:
    row, other = arms[arm], arms["without_skill" if arm == "with_skill" else "with_skill"]
    rows = _rows(inputs, row["session_id"])
    if row["session_id"] != other["session_id"]:
        return rows
    starts = sorted((("with_skill", arms["with_skill"]["start_ts"]),
                     ("without_skill", arms["without_skill"]["start_ts"])), key=lambda x: x[1])
    out = []
    for st in rows:
        if st["ts"] is None:
            continue
        owner = None
        for name, start in starts:
            if start <= st["ts"]:
                owner = name
        if owner == arm:
            out.append(st)
    return out


def _paired_runs(inputs, scores, sets: dict[str, set[str]]) -> dict:
    complete = _pair_arms(inputs)
    if not complete:
        return _not_computable("no pair_id with both with_skill and without_skill sessions")
    pair_sids = {arms[arm]["session_id"] for arms in complete.values()
                 for arm in ("with_skill", "without_skill")}
    skills = sorted({load["skill"] for load in inputs.loads.values() if load["session_id"] in pair_sids})
    if not skills:
        return _not_computable("paired sessions carry no skill load")

    out = {}
    for skill in skills:
        targets = sets.get(skill, set())
        if not targets:
            out[skill] = _not_computable("prescribed set is empty after the base-rate ceiling")
            continue
        diffs = []
        for pair_id, arms in sorted(complete.items()):
            with_sid = arms["with_skill"]["session_id"]
            load = next((ld for ld in inputs.loads.values()
                         if ld["skill"] == skill and ld["session_id"] == with_sid), None)
            if load is None:
                continue
            with_hit = window_hit(_arm_rows(inputs, arms, "with_skill"), targets, load["step"])
            without_hit = window_hit(_arm_rows(inputs, arms, "without_skill"), targets, load["step"])
            if with_hit is None or without_hit is None:
                continue
            diffs.append(with_hit - without_hit)
        if not diffs:
            out[skill] = _not_computable("no pair has a scorable window for this skill")
            continue
        experimental = _mean(diffs)
        observational = _mean([s.lift for s in scores.values() if s.skill == skill])
        out[skill] = {
            "computable": True,
            "n_pairs": len(diffs),
            "experimental_difference": experimental,
            "observational_lift": observational,
            "endogeneity_gap": (observational - experimental) if observational is not None else None,
        }
    return {"computable": any(v.get("computable") for v in out.values()), "skills": out}


# ------------------------------------------------------------------ trigger split
def _trigger_split(scores) -> dict:
    by_skill = defaultdict(list)
    by_trigger = defaultdict(list)
    for score in scores.values():
        by_skill[(score.skill, score.trigger)].append(score.lift)
        by_trigger[score.trigger].append(score.lift)
    if not by_skill:
        return _not_computable("no scorable loads")
    return {
        "computable": True,
        "rows": [{"skill": skill, "trigger": trigger, "n_loads": len(v), "lift": _mean(v)}
                 for (skill, trigger), v in sorted(by_skill.items())],
        "by_trigger": [{"trigger": trigger, "n_loads": len(v), "lift": _mean(v)}
                       for trigger, v in sorted(by_trigger.items())],
    }


# ------------------------------------------------------------------ entry point
def run_experiments(corpus_dir, inputs=None, scores=None, sets=None) -> dict:
    """All four D7 sections for one corpus. Never raises on missing inputs."""
    try:
        inputs, scores, sets = _context(corpus_dir, inputs, scores, sets)
    except FileNotFoundError as exc:
        reason = f"{exc}; run evidence and expect first"
        return {"corpus": Path(corpus_dir).name, **{section: _not_computable(reason) for section in SECTIONS}}
    return {
        "corpus": inputs.corpus,
        "pre_post": _pre_post(inputs, sets),
        "edit_response": _edit_response(inputs, sets),
        "paired_runs": _paired_runs(inputs, scores, sets),
        "trigger_split": _trigger_split(scores),
    }


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog='python -m potency.experiments',
                                description='Analysis: D7 natural experiments -> out/experiments.json.')
    p.add_argument('--corpus', default=None, help='corpus (default: every corpus in the data dir)')
    p.add_argument('--data', default=None, help='data dir')
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    data_dir = io.resolve_data_dir(args.data)
    if not data_dir.is_dir():
        print(f"experiments: data dir {data_dir} does not exist", file=sys.stderr)
        return 1
    corpus_dirs = io.corpus_dirs(data_dir, args.corpus)
    if not corpus_dirs:
        print(f"experiments: no corpus with sessions.jsonl under {data_dir}", file=sys.stderr)
        return 1
    for corpus_dir in corpus_dirs:
        payload = run_experiments(Path(corpus_dir))
        io.write_json(Path(corpus_dir) / "out" / "experiments.json", payload)
        print(f"experiments: {Path(corpus_dir).name}: written")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
