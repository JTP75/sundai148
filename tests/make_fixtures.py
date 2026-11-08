"""Generate the frozen synthetic fixtures (design D19). Deterministic: seed 148, byte-identical on every OS.

    python tests/make_fixtures.py            # writes tests/fixtures/synthetic/ and tests/fixtures/claude_code_sample/

Outputs
- tests/fixtures/synthetic/synth/*.jsonl          D12 tables for corpus "synth"
- tests/fixtures/synthetic/golden/evidence.csv    reference D18 evidence for every scorable load x scored rule
- tests/fixtures/synthetic/golden/expected.csv    true no-skill probability p_hat for each evidence row
- tests/fixtures/synthetic/golden/potency_expect.json   known effects (habit ~0, novel > 0, ...)
- tests/fixtures/synthetic/golden/cases.json      handcrafted session -> expected (rule, status, reason)
- tests/fixtures/claude_code_sample/              raw Claude Code JSONL + sessions.csv + expected.json

The generative model: background agent behavior is a categorical distribution over signatures with a few
strong first-order transitions. A skill load changes behavior only by inserting its prescribed command with
probability q (habit q=0, mid q=0.5, novel q=0.85). So the true lift is known per skill.
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from potency import io, schema  # noqa: E402

SEED = schema.SEED
N = schema.WINDOW_N
CORPUS = "synth"
T0 = 1767225600.0  # 2026-01-01T00:00:00Z
DAY = 86400.0

# ------------------------------------------------------------------ background behavior
BACKGROUND = [
    ("terminal: ls", 10), ("terminal: cat", 8), ("terminal: git status", 8), ("terminal: grep", 6),
    ("read_file", 8), ("write_file", 4), ("terminal: python", 6), ("terminal: git add", 0.6),
    ("terminal: git diff", 4), ("web_search", 3), ("terminal: git commit", 0.3), ("terminal: docker compose up", 0.6),
    ("terminal: npm test", 2), ("terminal: pytest", 2), ("terminal: make", 1), ("terminal: git merge", 0.6),
    ("terminal: git push", 0.6),
]
TRANSITIONS = {  # prev -> (next, prob)
    "terminal: git add": ("terminal: git commit", 0.3),
    "terminal: git merge": ("terminal: git push", 0.5),
    "terminal: git diff": ("terminal: git add", 0.6),
}
VOCAB = [s for s, _ in BACKGROUND]
_TOTAL = sum(w for _, w in BACKGROUND)
P_BG = {s: w / _TOTAL for s, w in BACKGROUND}


def next_prob(prev: str | None) -> dict[str, float]:
    """True no-skill next-step distribution given the previous signature."""
    t = TRANSITIONS.get(prev or "")
    if not t:
        return dict(P_BG)
    target, p = t
    d = {s: (1 - p) * q for s, q in P_BG.items()}
    d[target] += p
    return d


def p_hit_within(prev: str | None, targets: set[str], n: int) -> float:
    """Exact P(any target among the next n steps | previous signature) under the background model."""
    if n <= 0 or not targets:
        return 0.0
    # f[k][s] = P(no hit in next k steps | prev = s)
    f = {s: 1.0 for s in VOCAB + ["<none>"]}
    for _ in range(n):
        g = {}
        for s in f:
            d = next_prob(None if s == "<none>" else s)
            g[s] = sum(p * f[t] for t, p in d.items() if t not in targets)
        f = g
    return 1.0 - f[prev if prev in f else "<none>"]


def bg_step(rng: random.Random, prev: str | None) -> str:
    d = next_prob(prev)
    r, acc = rng.random(), 0.0
    for s in VOCAB:
        acc += d[s]
        if r < acc:
            return s
    return VOCAB[-1]


# ------------------------------------------------------------------ skills, versions, rules
def rule(skill, vid, rid, obligation, observable, applicability=(), alternatives=(), in_core=None,
         source="auto", approved=False, location=None):
    return {
        "corpus": CORPUS, "skill": skill, "version_id": vid, "rule_id": rid, "obligation": obligation,
        "applicability": None if applicability is None else list(applicability), "observable": list(observable),
        "alternatives": list(alternatives), "location": location, "rule_source": source, "approved": approved,
        "in_core": in_core,
    }


EDIT_TS = T0 + 60 * DAY  # mid-skill v2 adds `make`
CREATE_NOVEL_TS = T0 + 30 * DAY

SKILLS = {
    # skill: (q insert prob, prescribed signature, provenance)
    "habit-skill": (0.0, "terminal: git commit"),
    "novel-skill": (0.85, "terminal: gog tasks list"),
    "mid-skill": (0.5, "terminal: docker compose up"),
}

VERSIONS = [
    ("habit-skill", "habit-v1", "injected", T0),
    ("novel-skill", "novel-v1", "injected", CREATE_NOVEL_TS),
    ("mid-skill", "mid-v1", "injected", T0),
    ("mid-skill", "mid-v2", "injected", EDIT_TS),
    ("alt-skill", "alt-v1", "injected", T0),
    ("cond-skill", "cond-v1", "approved_map", T0),
    ("avoid-skill", "avoid-v1", "injected", T0),
    ("empty-skill", "empty-v1", "injected", T0),
    ("core-skill", "core-cur", "version_core", T0),
]

RULES = [
    rule("habit-skill", "habit-v1", "habit-1", "required", ["terminal: git commit"]),
    rule("habit-skill", "habit-v1", "habit-ex", "example", ["terminal: git log"]),
    rule("novel-skill", "novel-v1", "novel-1", "required", ["terminal: gog tasks list"]),
    rule("mid-skill", "mid-v1", "mid-1", "required", ["terminal: docker compose up"]),
    rule("mid-skill", "mid-v2", "mid-1", "required", ["terminal: docker compose up"]),
    rule("mid-skill", "mid-v2", "mid-2", "required", ["terminal: make"]),
    rule("alt-skill", "alt-v1", "alt-1", "required", ["terminal: npm test"], alternatives=["terminal: pytest"]),
    rule("cond-skill", "cond-v1", "cond-1", "conditional", ["terminal: git push"], applicability=["terminal: git merge"],
         source="approved", approved=True, location="section 1"),
    rule("cond-skill", "cond-v1", "cond-2", "conditional", ["terminal: make"], applicability=None,
         source="approved", approved=True, location="section 2"),
    rule("cond-skill", "cond-v1", "cond-opt", "optional", ["terminal: git diff"], source="approved", approved=True),
    rule("avoid-skill", "avoid-v1", "avoid-1", "avoid", ["terminal: git push"]),
    rule("empty-skill", "empty-v1", "empty-1", "required", []),
    rule("core-skill", "core-cur", "core-1", "required", ["terminal: make"], in_core=True),
    rule("core-skill", "core-cur", "core-2", "required", ["terminal: npm test"], in_core=False),
]
RULES_BY_VERSION: dict[str, list[dict]] = {}
for r in RULES:
    RULES_BY_VERSION.setdefault(r["version_id"], []).append(r)

PROVENANCE = [
    {"corpus": CORPUS, "skill": "habit-skill", "created_ts": T0 - 10 * DAY, "created_by": "agent", "agent_touched": True,
     "changes": []},
    {"corpus": CORPUS, "skill": "novel-skill", "created_ts": CREATE_NOVEL_TS, "created_by": None, "agent_touched": False,
     "changes": []},
    {"corpus": CORPUS, "skill": "mid-skill", "created_ts": T0 - 20 * DAY, "created_by": None, "agent_touched": True,
     "changes": [{"ts": EDIT_TS, "actor": "curator", "action": "patch", "added": ["terminal: make"], "removed": []}]},
    {"corpus": CORPUS, "skill": "alt-skill", "created_ts": None, "created_by": None, "agent_touched": False, "changes": []},
    {"corpus": CORPUS, "skill": "cond-skill", "created_ts": None, "created_by": "learn", "agent_touched": True, "changes": []},
    {"corpus": CORPUS, "skill": "avoid-skill", "created_ts": None, "created_by": None, "agent_touched": False, "changes": []},
    {"corpus": CORPUS, "skill": "empty-skill", "created_ts": None, "created_by": None, "agent_touched": False, "changes": []},
    {"corpus": CORPUS, "skill": "core-skill", "created_ts": None, "created_by": None, "agent_touched": False, "changes": []},
    {"corpus": CORPUS, "skill": "never-loaded-skill", "created_ts": T0, "created_by": "agent", "agent_touched": True,
     "changes": []},
]


def version_for(skill: str, ts: float) -> tuple[str, str]:
    cands = sorted((v for v in VERSIONS if v[0] == skill and v[3] <= ts), key=lambda v: v[3])
    if not cands:
        cands = sorted((v for v in VERSIONS if v[0] == skill), key=lambda v: v[3])
    _, vid, src, _ = cands[-1]
    return vid, ("injected" if src == "approved_map" else src)


# ------------------------------------------------------------------ session builder
class Session:
    def __init__(self, sid: str, start_ts: float, cluster: str, task_key=None, pair_id=None, pair_arm=None, source="cli"):
        self.sid, self.start_ts, self.cluster = sid, start_ts, cluster
        self.task_key, self.pair_id, self.pair_arm, self.source = task_key, pair_id, pair_arm, source
        self.steps: list[dict] = []
        self.loads: list[dict] = []  # {skill, step, trigger}

    def add(self, signature: str, kind: str | None = None, batch: str | None = None, status: str = "ok") -> int:
        step = len(self.steps)
        kind = kind or ("shell" if signature.startswith("terminal: ") else "tool")
        self.steps.append({
            "corpus": CORPUS, "session_id": self.sid, "step": step, "source_offset": step * 2,
            "call_id": f"{self.sid}-c{step}", "batch_id": batch or f"{self.sid}-b{step}",
            "ts": self.start_ts + 30.0 * step, "kind": kind, "signature": signature, "status": status,
            "attribution_skill": None,
        })
        return step

    def load(self, skill: str, batch: str | None = None, trigger: str = "chosen") -> int:
        step = self.add(f"load: {skill}", kind="load", batch=batch)
        self.loads.append({"skill": skill, "step": step, "trigger": trigger})
        return step

    def last_sig(self) -> str | None:
        for s in reversed(self.steps):
            if s["kind"] != "load":
                return s["signature"]
        return None


def build_stochastic(rng: random.Random) -> list[Session]:
    sessions = []
    n_sessions = 420
    for i in range(n_sessions):
        start = T0 + (120 * DAY) * i / n_sessions
        task_key = "task-1" if i % 8 == 0 else None
        s = Session(f"s{i:04d}", start, f"repo-{i % 25:02d}", task_key=task_key, source="cron" if task_key else "cli")
        length = rng.randint(15, 40)
        plan_load = None
        if rng.random() < 0.6:
            skills = ["habit-skill", "novel-skill", "mid-skill"]
            if start < CREATE_NOVEL_TS:
                skills = ["habit-skill", "mid-skill"]
            if task_key and start >= CREATE_NOVEL_TS:
                skills = ["novel-skill"]
            plan_load = (rng.choice(skills), rng.randint(2, max(2, length - N - 2)))
        inserted = {}
        while len(s.steps) < length:
            if plan_load and len(s.steps) == plan_load[1]:
                skill = plan_load[0]
                s.load(skill)
                q, sig = SKILLS[skill]
                if rng.random() < q:
                    inserted[len(s.steps) + rng.randint(0, 5)] = sig
                vid, _ = version_for(skill, s.start_ts)
                if skill == "mid-skill" and vid == "mid-v2" and rng.random() < 0.5:
                    inserted.setdefault(len(s.steps) + rng.randint(0, 5), "terminal: make")
                continue
            sig = inserted.pop(len(s.steps), None) or bg_step(rng, s.last_sig())
            s.add(sig)
        sessions.append(s)
    # paired runs: same task with and without novel-skill
    for j in range(20):
        start = CREATE_NOVEL_TS + DAY * (1 + j)
        for arm in ("with_skill", "without_skill"):
            s = Session(f"p{j:02d}-{arm[:4]}", start + (0 if arm == "with_skill" else 600), f"repo-p{j % 5}",
                        task_key="task-pair", pair_id=f"pair-{j:02d}", pair_arm=arm)
            for _ in range(3):
                s.add(bg_step(rng, s.last_sig()))
            if arm == "with_skill":
                s.load("novel-skill")
                if rng.random() < SKILLS["novel-skill"][0]:
                    s.add("terminal: gog tasks list")
            while len(s.steps) < 20:
                s.add(bg_step(rng, s.last_sig()))
            sessions.append(s)
    return sessions


def build_cases() -> tuple[list[Session], list[dict]]:
    """Handcrafted sessions covering every status and reason code. Returns sessions + expectations."""
    cases, expect = [], []
    base = T0 + 150 * DAY
    filler = ["terminal: ls", "terminal: cat", "read_file", "terminal: grep", "terminal: git status"]

    def new(name, k):
        return Session(f"case-{name}", base + k * 3600, f"repo-case-{k % 4}")

    def pad(s, n):
        for i in range(n):
            s.add(filler[i % len(filler)])

    k = 0
    # matched
    s = new("matched", k); pad(s, 2); s.load("novel-skill"); pad(s, 1); s.add("terminal: gog tasks list"); pad(s, 12)
    cases.append(s); expect.append({"session_id": s.sid, "rule_id": "novel-1", "status": "supported_agreement", "reason": "matched"}); k += 1
    # matched_alternative
    s = new("alternative", k); pad(s, 2); s.load("alt-skill"); s.add("terminal: pytest"); pad(s, 12)
    cases.append(s); expect.append({"session_id": s.sid, "rule_id": "alt-1", "status": "supported_agreement", "reason": "matched_alternative"}); k += 1
    # no match, complete window
    s = new("nomatch", k); pad(s, 2); s.load("novel-skill"); pad(s, 14)
    cases.append(s); expect.append({"session_id": s.sid, "rule_id": "novel-1", "status": "no_observed_agreement", "reason": "no_match_complete_window"}); k += 1
    # incomplete window
    s = new("incomplete", k); pad(s, 5); s.load("novel-skill"); pad(s, 3)
    cases.append(s); expect.append({"session_id": s.sid, "rule_id": "novel-1", "status": "insufficient_evidence", "reason": "incomplete_window"}); k += 1
    # same batch only
    s = new("samebatch", k); pad(s, 2); s.load("novel-skill", batch="case-samebatch-bX"); s.add("terminal: gog tasks list", batch="case-samebatch-bX"); pad(s, 12)
    cases.append(s); expect.append({"session_id": s.sid, "rule_id": "novel-1", "status": "insufficient_evidence", "reason": "same_batch_only"}); k += 1
    # conditional: applicability holds and matched / false / unknown
    s = new("cond-applies", k); pad(s, 2); s.load("cond-skill"); s.add("terminal: git merge"); s.add("terminal: git push"); pad(s, 12)
    cases.append(s)
    expect.append({"session_id": s.sid, "rule_id": "cond-1", "status": "supported_agreement", "reason": "matched"})
    expect.append({"session_id": s.sid, "rule_id": "cond-2", "status": "insufficient_evidence", "reason": "applicability_unknown"}); k += 1
    s = new("cond-false", k); pad(s, 2); s.load("cond-skill"); pad(s, 14)
    cases.append(s)
    expect.append({"session_id": s.sid, "rule_id": "cond-1", "status": "not_applicable", "reason": "applicability_false"})
    expect.append({"session_id": s.sid, "rule_id": "cond-2", "status": "insufficient_evidence", "reason": "applicability_unknown"}); k += 1
    # unsupported rule (empty observable)
    s = new("unsupported", k); pad(s, 2); s.load("empty-skill"); pad(s, 12)
    cases.append(s); expect.append({"session_id": s.sid, "rule_id": "empty-1", "status": "insufficient_evidence", "reason": "unsupported_rule"}); k += 1
    # version_core: in-core rule scored, outside-core rule insufficient
    s = new("core", k); pad(s, 2); s.load("core-skill"); s.add("terminal: make"); pad(s, 12)
    cases.append(s)
    expect.append({"session_id": s.sid, "rule_id": "core-1", "status": "supported_agreement", "reason": "matched"})
    expect.append({"session_id": s.sid, "rule_id": "core-2", "status": "insufficient_evidence", "reason": "outside_core"}); k += 1
    # avoid rule: the avoided command was attempted
    s = new("avoid", k); pad(s, 2); s.load("avoid-skill"); s.add("terminal: git push"); pad(s, 12)
    cases.append(s); expect.append({"session_id": s.sid, "rule_id": "avoid-1", "status": "supported_agreement", "reason": "matched"}); k += 1
    # maintenance load (no evidence rows), repeat load (no rows), overlap flag (rows as usual)
    s = new("maintenance", k); pad(s, 2); s.load("novel-skill"); s.add("skill_manage"); pad(s, 12)
    cases.append(s); expect.append({"session_id": s.sid, "rule_id": "novel-1", "status": None, "reason": "excluded_maintenance"}); k += 1
    s = new("repeat-overlap", k); pad(s, 2); s.load("alt-skill"); s.add("terminal: npm test"); pad(s, 1); s.load("alt-skill"); pad(s, 12)
    cases.append(s); expect.append({"session_id": s.sid, "rule_id": "alt-1", "status": "supported_agreement", "reason": "matched", "flags": ["overlap"]}); k += 1
    # preloaded (cron) load at step 0
    s = Session("case-preloaded", base + k * 3600, "repo-case-0", task_key="task-cron", source="cron")
    s.loads.append({"skill": "novel-skill", "step": 0, "trigger": "preloaded"})
    s.add("terminal: ls"); s.add("terminal: gog tasks list"); pad(s, 12)
    cases.append(s); expect.append({"session_id": s.sid, "rule_id": "novel-1", "status": "supported_agreement", "reason": "matched"}); k += 1
    return cases, expect


# ------------------------------------------------------------------ derived tables
def load_rows(sessions: list[Session], split_of: dict[str, str]) -> list[dict]:
    rows = []
    for s in sessions:
        seen = set()
        last = len(s.steps) - 1
        load_steps = [ld["step"] for ld in s.loads]
        for ld in s.loads:
            step, skill = ld["step"], ld["skill"]
            flags = []
            if skill in seen:
                flags.append("repeat")
            seen.add(skill)
            window = [st for st in s.steps if step < st["step"] <= step + N]
            if any(st["signature"] == "skill_manage" for st in window):
                flags.append("maintenance")
            if step + N > last:
                flags.append("incomplete")
            if any(step < o <= step + N for o in load_steps if o != step):
                flags.append("overlap")
            ts = s.start_ts + 30.0 * step
            vid, vsrc = version_for(skill, ts)
            rows.append({
                "corpus": CORPUS, "session_id": s.sid, "load_id": schema.episode_id(CORPUS, s.sid, step),
                "skill": skill, "step": step, "ts": ts, "trigger": ld["trigger"], "version_id": vid,
                "version_source": vsrc, "flags": sorted(flags), "cluster_key": s.cluster, "split": split_of[s.sid],
            })
    return rows


def reference_evidence(sessions: list[Session], loads: list[dict]) -> list[dict]:
    """Reference implementation of the D18 status contract (the oracle W3's evidence.py must match)."""
    by_sid = {s.sid: s for s in sessions}
    rows = []
    for ld in loads:
        if set(ld["flags"]) & {"maintenance", "repeat"} or ld["version_source"] == "version_unknown":
            continue
        s = by_sid[ld["session_id"]]
        t, last = ld["step"], len(s.steps) - 1
        load_batch = s.steps[t]["batch_id"] if s.steps[t]["kind"] == "load" else None
        w_end = min(t + N, last)
        complete = t + N <= last
        window = [st for st in s.steps if t < st["step"] <= w_end and st["kind"] != "load"]
        for r in RULES_BY_VERSION.get(ld["version_id"], []):
            if r["obligation"] not in schema.SCORED_OBLIGATIONS:
                continue
            status, reason, ev = None, None, []
            if ld["version_source"] == "version_core" and r["in_core"] is False:
                status, reason = "insufficient_evidence", "outside_core"
            elif not r["observable"]:
                status, reason = "insufficient_evidence", "unsupported_rule"
            else:
                obs, alt = set(r["observable"]), set(r["alternatives"])
                direct = [st["step"] for st in window if st["signature"] in obs and st["batch_id"] != load_batch]
                alts = [st["step"] for st in window if st["signature"] in alt and st["batch_id"] != load_batch]
                same = [st["step"] for st in window if st["signature"] in obs | alt and st["batch_id"] == load_batch]
                if direct:
                    status, reason, ev = "supported_agreement", "matched", direct
                elif alts:
                    status, reason, ev = "supported_agreement", "matched_alternative", alts
                elif same:
                    status, reason, ev = "insufficient_evidence", "same_batch_only", same
                else:
                    applicable = True
                    if r["obligation"] == "conditional":
                        if r["applicability"] is None:
                            applicable = None
                        elif r["applicability"]:
                            prefix = {st["signature"] for st in s.steps if st["step"] <= w_end}
                            if prefix & set(r["applicability"]):
                                applicable = True
                            else:
                                applicable = False if complete else None
                    if applicable is None:
                        status, reason = "insufficient_evidence", "applicability_unknown"
                    elif applicable is False:
                        status, reason = "not_applicable", "applicability_false"
                    elif not complete:
                        status, reason = "insufficient_evidence", "incomplete_window"
                    else:
                        status, reason = "no_observed_agreement", "no_match_complete_window"
            rows.append({
                "corpus": CORPUS, "load_id": ld["load_id"], "session_id": ld["session_id"],
                "cluster_key": ld["cluster_key"], "skill": ld["skill"], "version_id": ld["version_id"],
                "rule_id": r["rule_id"], "obligation": r["obligation"], "window_start": t + 1, "window_end": w_end,
                "status": status, "reason": reason, "evidence_steps": ev,
            })
    rows.sort(key=lambda r: (r["load_id"], r["rule_id"]))
    return rows


def reference_expected(sessions: list[Session], loads: list[dict], evidence: list[dict]) -> list[dict]:
    by_sid = {s.sid: s for s in sessions}
    by_load = {ld["load_id"]: ld for ld in loads}
    rules = {(r["version_id"], r["rule_id"]): r for r in RULES}
    out = []
    for ev in evidence:
        ld = by_load[ev["load_id"]]
        s = by_sid[ld["session_id"]]
        r = rules[(ld["version_id"], ev["rule_id"])]
        prev = None
        for st in reversed(s.steps[: ld["step"]]):
            if st["kind"] != "load":
                prev = st["signature"]
                break
        n = ev["window_end"] - ld["step"]
        p = p_hit_within(prev, set(r["observable"]) | set(r["alternatives"]), n)
        out.append({"corpus": CORPUS, "load_id": ev["load_id"], "rule_id": ev["rule_id"], "p_hat": p})
    return out


def known_effects(evidence: list[dict], expected: list[dict]) -> dict:
    """Unweighted per-skill lift from the golden inputs, plus the sign each must have."""
    exp = {(e["load_id"], e["rule_id"]): e["p_hat"] for e in expected}
    per_load: dict[tuple[str, str], list[tuple[float, float]]] = {}
    for ev in evidence:
        if ev["obligation"] == "avoid" or ev["status"] not in ("supported_agreement", "no_observed_agreement"):
            continue
        a = 1.0 if ev["status"] == "supported_agreement" else 0.0
        per_load.setdefault((ev["skill"], ev["load_id"]), []).append((a, exp[(ev["load_id"], ev["rule_id"])]))
    per_skill: dict[str, list[float]] = {}
    for (skill, _), pairs in per_load.items():
        a = sum(x for x, _ in pairs) / len(pairs)
        ah = sum(y for _, y in pairs) / len(pairs)
        per_skill.setdefault(skill, []).append(a - ah)
    lifts = {k: sum(v) / len(v) for k, v in per_skill.items()}
    return {
        "unweighted_mean_lift": dict(sorted(lifts.items())),
        "n_loads": {k: len(v) for k, v in sorted(per_skill.items())},
        "expect": {
            "habit-skill": {"sign": "zero", "abs_max": 0.12},
            "novel-skill": {"sign": "positive", "min": 0.4},
            "mid-skill": {"sign": "positive", "min": 0.15},
        },
        "notes": "habit-skill: high follow-through possible but lift ~ 0; novel-skill: command never seen without the skill.",
    }


def write_synthetic(out_dir: Path) -> None:
    rng = random.Random(SEED)
    sessions = build_stochastic(rng)
    cases, case_expect = build_cases()
    sessions = sessions + cases
    ordered = sorted(sessions, key=lambda s: (s.start_ts, s.sid))
    cut = int(len(ordered) * schema.TRAIN_SHARE)
    split_of = {s.sid: ("train" if i < cut else "test") for i, s in enumerate(ordered)}
    corpus_dir = out_dir / CORPUS
    sess_rows = [{
        "corpus": CORPUS, "session_id": s.sid, "start_ts": s.start_ts, "source": s.source, "task_key": s.task_key,
        "cluster_key": s.cluster, "model": "synthetic-model", "harness_version": "0.0", "pair_id": s.pair_id,
        "pair_arm": s.pair_arm, "split": split_of[s.sid],
    } for s in sorted(sessions, key=lambda s: s.sid)]
    step_rows = [st for s in sorted(sessions, key=lambda s: s.sid) for st in s.steps]
    loads = load_rows(sorted(sessions, key=lambda s: s.sid), split_of)
    ver_rows = [{"corpus": CORPUS, "skill": sk, "version_id": vid,
                 "version_source": ("injected" if src == "approved_map" else src), "valid_from_ts": ts,
                 "content_sha256": None} for sk, vid, src, ts in VERSIONS]
    io.write_table(corpus_dir, "sessions", sess_rows)
    io.write_table(corpus_dir, "steps", step_rows)
    io.write_table(corpus_dir, "loads", loads)
    io.write_table(corpus_dir, "skill_versions", ver_rows)
    io.write_table(corpus_dir, "rules", RULES)
    io.write_table(corpus_dir, "provenance", PROVENANCE)
    io.write_json(corpus_dir / "manifest.json", {"corpus": CORPUS, "generator": "tests/make_fixtures.py", "seed": SEED,
                                                  "row_counts": {"sessions": len(sess_rows), "steps": len(step_rows),
                                                                 "loads": len(loads)}})
    evidence = reference_evidence(sessions, loads)
    expected = reference_expected(sessions, loads, evidence)
    golden = out_dir / "golden"
    io.write_output_csv(golden / "evidence.csv", evidence)
    io.write_output_csv(golden / "expected.csv", expected)
    io.write_json(golden / "potency_expect.json", known_effects(evidence, expected))
    io.write_json(golden / "cases.json", case_expect)
    io.write_json(out_dir / "program_map.json", {
        "git": "public", "docker": "public", "npm": "public", "pytest": "public", "make": "public",
        "python": "public", "ls": "public", "cat": "public", "grep": "public", "gog": "local",
    })


# ------------------------------------------------------------------ Claude Code sample
def write_claude_code_sample(out_dir: Path) -> None:
    """Small raw Claude Code transcripts mirroring the SWE-chat v1 layout (keys verified on real files)."""
    tdir = out_dir / "transcripts"
    tdir.mkdir(parents=True, exist_ok=True)

    def line(sid, typ, uuid, ts, message=None, **extra):
        d = {"type": typ, "sessionId": sid, "uuid": uuid, "parentUuid": None, "timestamp": ts, "cwd": "/repo",
             "version": "2.1.0", "isSidechain": False, "userType": "external"}
        if message is not None:
            d["message"] = message
        d.update(extra)
        return d

    def assistant(sid, uuid, ts, tool_uses, model="claude-opus-4-6", attribution=None):
        content = [{"type": "tool_use", "id": tid, "name": name, "input": inp} for tid, name, inp in tool_uses]
        extra = {"attributionSkill": attribution} if attribution else {}
        return line(sid, "assistant", uuid, ts, {"role": "assistant", "model": model, "content": content}, **extra)

    def result(sid, uuid, ts, tid, text, is_error=False):
        item = {"type": "tool_result", "tool_use_id": tid, "content": text}
        if is_error:
            item["is_error"] = True
        return line(sid, "user", uuid, ts, {"role": "user", "content": [item]}, toolUseResult={})

    def injected(sid, uuid, ts, tid, body):
        return line(sid, "user", uuid, ts, {"role": "user", "content": [{"type": "text", "text": body}]},
                    isMeta=True, sourceToolUseID=tid)

    skill_body = ("Base directory for this skill: /home/u/.claude/skills/commit\n\n# Commit\n\n"
                  "```bash\ngit status\ngit commit -m \"msg\"\n```\nThen run `gh pr create --fill`.\n")
    sessions = {
        "sess-a": [  # load via `skill`, injected body, parallel calls in one batch, attribution, listing attachment
            line("sess-a", "attachment", "a0", "2026-02-01T10:00:00Z",
                 attachment={"type": "skill_listing", "skills": ["commit", "review"]}),
            line("sess-a", "user", "a1", "2026-02-01T10:00:01Z", {"role": "user", "content": "please commit my work"}),
            assistant("sess-a", "a2", "2026-02-01T10:00:02Z", [("t1", "Skill", {"skill": "commit"})]),
            result("sess-a", "a3", "2026-02-01T10:00:03Z", "t1", "Launching skill: commit"),
            injected("sess-a", "a4", "2026-02-01T10:00:03Z", "t1", skill_body),
            assistant("sess-a", "a5", "2026-02-01T10:00:04Z",
                      [("t2", "Bash", {"command": "git status"}), ("t3", "Read", {"file_path": "/repo/x.py"})],
                      attribution="commit"),
            result("sess-a", "a6", "2026-02-01T10:00:05Z", "t2", "clean"),
            result("sess-a", "a7", "2026-02-01T10:00:05Z", "t3", "..."),
            assistant("sess-a", "a8", "2026-02-01T10:00:06Z",
                      [("t4", "Bash", {"command": "git add -A && git commit -m 'x' && git push"})], attribution="commit"),
            result("sess-a", "a9", "2026-02-01T10:00:07Z", "t4", "ok"),
        ],
        "sess-b": [  # variant name keys, an errored load, invoked_skills attachment (not a load)
            line("sess-b", "user", "b1", "2026-02-02T09:00:00Z", {"role": "user", "content": "review this"}),
            assistant("sess-b", "b2", "2026-02-02T09:00:01Z", [("u1", "Skill", {"skill": "nope"})]),
            result("sess-b", "b3", "2026-02-02T09:00:02Z", "u1", "<tool_use_error>Unknown skill: nope</tool_use_error>",
                   is_error=True),
            assistant("sess-b", "b4", "2026-02-02T09:00:03Z", [("u2", "Skill", {"skillName": "review", "args": "pr 3"})]),
            result("sess-b", "b5", "2026-02-02T09:00:04Z", "u2", "Launching skill: review"),
            injected("sess-b", "b6", "2026-02-02T09:00:04Z", "u2", "# Review\n\nRun `gh pr diff 3` first.\n"),
            line("sess-b", "attachment", "b7", "2026-02-02T09:00:05Z",
                 attachment={"type": "invoked_skills", "skills": ["review"]}),
            assistant("sess-b", "b8", "2026-02-02T09:00:06Z", [("u3", "Bash", {"command": "gh pr diff 3"})]),
            result("sess-b", "b9", "2026-02-02T09:00:07Z", "u3", "diff..."),
            assistant("sess-b", "b10", "2026-02-02T09:00:08Z", [("u4", "Skill", {"skill_name": "review"})]),
            result("sess-b", "b11", "2026-02-02T09:00:09Z", "u4", "Launching skill: review"),
            assistant("sess-b", "b12", "2026-02-02T09:00:10Z", [("u5", "Skill", {"name": "commit"})]),
            result("sess-b", "b13", "2026-02-02T09:00:11Z", "u5", "Launching skill: commit"),
        ],
        "sess-c": [  # no skills at all; secret-bearing command
            line("sess-c", "user", "c1", "2026-02-03T08:00:00Z", {"role": "user", "content": "deploy"}),
            assistant("sess-c", "c2", "2026-02-03T08:00:01Z",
                      [("v1", "Bash", {"command": "curl -H 'Authorization: Bearer sk-secret-123' https://api.x.io"})],
                      model="claude-sonnet-4-6"),
            result("sess-c", "c3", "2026-02-03T08:00:02Z", "v1", "ok"),
        ],
    }
    for sid, lines in sessions.items():
        io.write_jsonl(tdir / f"{sid}.jsonl", lines)
    io.write_csv(out_dir / "sessions.csv", [
        {"session_id": "sess-a", "repo_id": "org/repo-1", "user_id": "u1", "agent": "claude-code",
         "created_at": "2026-02-01T10:00:00Z", "cli_version": "2.1.0"},
        {"session_id": "sess-b", "repo_id": "org/repo-1", "user_id": "u2", "agent": "claude-code",
         "created_at": "2026-02-02T09:00:00Z", "cli_version": "2.1.0"},
        {"session_id": "sess-c", "repo_id": "org/repo-2", "user_id": "u1", "agent": "claude-code",
         "created_at": "2026-02-03T08:00:00Z", "cli_version": "1.0.0"},
    ], ["session_id", "repo_id", "user_id", "agent", "created_at", "cli_version"])
    io.write_json(out_dir / "expected.json", {
        "sessions": 3,
        "cluster_keys": {"sess-a": "org/repo-1", "sess-b": "org/repo-1", "sess-c": "org/repo-2"},
        "loads": [  # successful loads only, in order; errored `nope` is dropped
            {"session_id": "sess-a", "skill": "commit", "version_source": "injected", "flags": []},
            {"session_id": "sess-b", "skill": "review", "version_source": "injected", "flags": []},
            {"session_id": "sess-b", "skill": "review", "version_source": "version_unknown", "flags": ["repeat"]},
            {"session_id": "sess-b", "skill": "commit", "version_source": "version_unknown", "flags": []},
        ],
        "same_batch": {"sess-a": ["terminal: git status", "read"]},
        "signatures_sess_a": ["load: commit", "terminal: git status", "read", "terminal: git add",
                              "terminal: git commit", "terminal: git push"],
        "commit_rules_auto": ["terminal: git status", "terminal: git commit", "terminal: gh pr create"],
        "must_not_appear_anywhere": ["sk-secret-123", "Authorization", "api.x.io"],
        "attribution_skill_steps": {"sess-a": "commit"},
        "notes": "Load step = the Skill call; the injected body (isMeta + sourceToolUseID) gives version_source "
                 "'injected'. A second load of the same skill in a session is flagged 'repeat'. A load with no "
                 "injected body and no other source is 'version_unknown'.",
    })


def main() -> None:
    fixtures = ROOT / "tests" / "fixtures"
    write_synthetic(fixtures / "synthetic")
    write_claude_code_sample(fixtures / "claude_code_sample")
    print("fixtures written to", fixtures)


if __name__ == "__main__":
    main()
