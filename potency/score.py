"""Analysis: lift, controls, ranking, experiments -> out/potency.csv, strata.csv, experiments.json.

Implements design D2 (lift over expectation), D4 (specificity weights), D5 (placebo), D6 (strata),
D9 (shrinkage, cluster bootstrap, ranking) and D16 (provenance / bloat). Reads the frozen evidence
layer (``out/evidence.csv``) and the expectation model (``out/expected.csv``); never re-derives either.

Divergences from a naive reading of the design, all recorded in the PR body:
- base rates are Laplace-smoothed as ``(hits + 1) / (windows + 2)`` and counted per no-load window
  (any of the next N steps), over train-period sessions that never loaded a skill;
- a rule with several observables is expanded into one weighted entry per observable that survives the
  ceiling, so a rule never contributes more than its own weight;
- a skill with a single scorable load borrows the pooled per-load variance when shrinking.
"""
from __future__ import annotations

import argparse
import bisect
import math
import random
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from potency import experiments, io, normalize, schema

ALPHA = 1.0  # Laplace pseudo-count for smoothed base rates
FAMILIARITY_OCCASIONAL = schema.FAMILIARITY_CUTOFFS[1]
WINDOW = schema.WINDOW_N
# Avoid rules get evidence rows but never count toward A or the prescribed set (spec: reported separately).
WEIGHTED_OBLIGATIONS = ("required", "conditional")


# ------------------------------------------------------------------ small statistics
# A skill seen in fewer clusters than this gets no directional label: its bootstrap CI is degenerate.
MIN_CI_CLUSTERS = 2


def _mean(xs):
    xs = list(xs)
    return sum(xs) / len(xs) if xs else None


def _variance(xs):
    xs = list(xs)
    if len(xs) < 2:
        return 0.0
    m = sum(xs) / len(xs)
    return sum((x - m) ** 2 for x in xs) / (len(xs) - 1)


def _percentile(values, q):
    values = sorted(values)
    if not values:
        return None
    i = (len(values) - 1) * q
    lo = int(i)
    hi = min(lo + 1, len(values) - 1)
    return values[lo] * (1 - (i - lo)) + values[hi] * (i - lo)


def _ranks(values):
    """Tie-averaged ranks (1-based), Spearman-ready."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def spearman(xs, ys):
    """Spearman rho with tie correction, or None when either side is constant."""
    if len(xs) < 2 or len(xs) != len(ys):
        return None
    rx, ry = _ranks(xs), _ranks(ys)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))
    return None if den == 0 else num / den


# ------------------------------------------------------------------ inputs
@dataclass
class Inputs:
    corpus: str
    corpus_dir: Path
    sessions: dict[str, dict]
    loads: dict[str, dict]
    rules: dict[tuple[str, str], dict]
    provenance: dict[str, dict]
    steps: dict[str, list[dict]]
    evidence: list[dict]
    expected: dict[tuple[str, str], float]
    program_map: dict[str, str]


def _require(path: Path) -> Path:
    if not path.exists():
        raise FileNotFoundError(f"{path} is missing; run the evidence and expectation stages first")
    return path


def read_inputs(corpus_dir, program_map: dict[str, str] | None = None) -> Inputs:
    corpus_dir = Path(corpus_dir)
    out = corpus_dir / "out"
    sessions = {s["session_id"]: s for s in io.read_table(corpus_dir, "sessions")}
    loads = {ld["load_id"]: ld for ld in io.read_table(corpus_dir, "loads")}
    rules = {(r["version_id"], r["rule_id"]): r for r in io.read_table(corpus_dir, "rules")}
    provenance = {p["skill"]: p for p in io.read_table(corpus_dir, "provenance")}
    steps: dict[str, list[dict]] = defaultdict(list)
    for st in io.read_table(corpus_dir, "steps"):
        steps[st["session_id"]].append(st)
    for rows in steps.values():
        rows.sort(key=lambda s: s["step"])
    evidence = io.read_csv(_require(out / "evidence.csv"))
    expected = {}
    for row in io.read_csv(_require(out / "expected.csv")):
        if row["p_hat"] != "":
            expected[(row["load_id"], row["rule_id"])] = float(row["p_hat"])
    return Inputs(
        corpus=corpus_dir.name,
        corpus_dir=corpus_dir,
        sessions=sessions,
        loads=loads,
        rules=rules,
        provenance=provenance,
        steps=dict(steps),
        evidence=evidence,
        expected=expected,
        program_map=dict(program_map or {}),
    )


# ------------------------------------------------------------------ base rates (D4, D6)
class BaseRates:
    """Command base rates from train-period no-load windows of one corpus."""

    def __init__(self, inputs: Inputs):
        loaded = {ld["session_id"] for ld in inputs.loads.values()}
        self.windows: list[tuple[float, frozenset[str]]] = []
        for sid, rows in sorted(inputs.steps.items()):
            session = inputs.sessions.get(sid)
            if sid in loaded or session is None or session["split"] != "train":
                continue
            sigs = [st["signature"] for st in rows]
            for t in range(len(sigs) - WINDOW):
                start_ts = rows[t]["ts"] if rows[t]["ts"] is not None else session["start_ts"]
                self.windows.append((float(start_ts), frozenset(sigs[t + 1: t + 1 + WINDOW])))
        self.total = len(self.windows)
        self.hits: dict[str, int] = defaultdict(int)
        sig_ts: dict[str, list[float]] = defaultdict(list)
        for ts, sigs in self.windows:
            for sig in sigs:
                self.hits[sig] += 1
                sig_ts[sig].append(ts)
        # Sorted start times, overall and per signature, so raw_before is two binary searches, not a scan.
        self._all_ts = sorted(ts for ts, _ in self.windows)
        self._sig_ts = {sig: sorted(v) for sig, v in sig_ts.items()}

    def rate(self, sig: str) -> float:
        """Smoothed per-window hit rate; the exact zero of a never-seen command becomes ALPHA/(n+2)."""
        return (self.hits.get(sig, 0) + ALPHA) / (self.total + 2 * ALPHA)

    def weight(self, sig: str) -> float:
        return -math.log(self.rate(sig))

    def above_ceiling(self, sig: str) -> bool:
        return self.rate(sig) > schema.BASE_RATE_CEILING

    def raw_before(self, sig: str, cutoff_ts: float | None) -> float:
        """Raw (unsmoothed) rate over windows that start before the skill's creation date."""
        if not self._all_ts:
            return 0.0
        mine = self._sig_ts.get(sig, ())
        n = len(self._all_ts) if cutoff_ts is None else bisect.bisect_left(self._all_ts, cutoff_ts)
        if n == 0:  # no window before the cutoff: fall back to every window
            return len(mine) / len(self._all_ts)
        k = len(mine) if cutoff_ts is None else bisect.bisect_left(mine, cutoff_ts)
        return k / n


def familiarity_label(rate: float) -> str:
    if rate <= 0.0:
        return "novel"
    return "occasional" if rate <= FAMILIARITY_OCCASIONAL else "habitual"


def prior_knowledge(sig: str, program_map: dict[str, str]) -> str:
    """Public (known from pretraining) vs local; unmapped programs default to local (D6)."""
    program = normalize.program_of(sig)
    if program is None:
        return "local"
    return program_map.get(program, "local")


# ------------------------------------------------------------------ per-load scoring (D2, D4)
@dataclass
class Entry:
    signature: str
    weight: float
    observed: float
    expected: float


@dataclass
class LoadScore:
    load_id: str
    skill: str
    cluster_key: str
    trigger: str
    flags: list[str]
    entries: list[Entry] = field(default_factory=list)
    avoid: int = 0

    @property
    def total_weight(self) -> float:
        return sum(e.weight for e in self.entries)

    @property
    def observed(self) -> float:
        w = self.total_weight
        return sum(e.weight * e.observed for e in self.entries) / w

    @property
    def expected(self) -> float:
        w = self.total_weight
        return sum(e.weight * e.expected for e in self.entries) / w

    @property
    def lift(self) -> float:
        return self.observed - self.expected

    @property
    def n_supported(self) -> int:
        return sum(1 for e in self.entries if e.observed >= 0.5)


def surviving_observables(rule: dict, rates: BaseRates) -> list[str]:
    return [sig for sig in rule["observable"] if not rates.above_ceiling(sig)]


def score_loads(inputs: Inputs, rates: BaseRates) -> dict[str, LoadScore]:
    """One LoadScore per load with at least one determinate row after the ceiling filter."""
    scores: dict[str, LoadScore] = {}
    for row in inputs.evidence:
        load = inputs.loads.get(row["load_id"])
        if load is None:
            continue
        score = scores.get(row["load_id"])
        if score is None:
            score = LoadScore(
                load_id=row["load_id"], skill=load["skill"], cluster_key=load["cluster_key"],
                trigger=load["trigger"], flags=list(load["flags"]),
            )
            scores[row["load_id"]] = score
        if row["obligation"] == "avoid":
            if row["status"] == "supported_agreement":
                score.avoid += 1
            continue
        if row["status"] not in ("supported_agreement", "no_observed_agreement"):
            continue
        rule = inputs.rules.get((row["version_id"], row["rule_id"]))
        if rule is None:
            continue
        p_hat = inputs.expected.get((row["load_id"], row["rule_id"]))
        if p_hat is None:
            continue
        observable = surviving_observables(rule, rates)
        if not observable:
            continue
        observed = 1.0 if row["status"] == "supported_agreement" else 0.0
        share = 1.0 / len(observable)
        for sig in observable:
            score.entries.append(Entry(sig, rates.weight(sig) * share, observed, p_hat))
    return {lid: s for lid, s in scores.items() if s.entries}


def prescribed_sets(inputs: Inputs, rates: BaseRates) -> dict[str, set[str]]:
    """Post-ceiling prescribed signatures per skill, union over its versions."""
    sets: dict[str, set[str]] = defaultdict(set)
    for rule in inputs.rules.values():
        if rule["obligation"] not in WEIGHTED_OBLIGATIONS:
            continue
        sets[rule["skill"]].update(surviving_observables(rule, rates))
    return dict(sets)


def skill_created_ts(inputs: Inputs, skill: str) -> float | None:
    prov = inputs.provenance.get(skill)
    return prov["created_ts"] if prov else None


def familiarity_of(inputs: Inputs, rates: BaseRates, skill: str, sig: str) -> str:
    return familiarity_label(rates.raw_before(sig, skill_created_ts(inputs, skill)))


# ------------------------------------------------------------------ placebo control (D5)
def _window_signatures(inputs: Inputs, load: dict) -> list[str]:
    rows = inputs.steps.get(load["session_id"], [])
    if not rows:
        return []
    last = rows[-1]["step"]
    start = load["step"]
    end = min(start + WINDOW, last)
    return [st["signature"] for st in rows if start < st["step"] <= end and st["kind"] != "load"]


def _set_adherence(sigset: set[str], weights: dict[str, float], window: list[str]) -> float:
    total = sum(weights[s] for s in sigset)
    if total <= 0:
        return 0.0
    seen = set(window)
    return sum(weights[s] for s in sigset if s in seen) / total


def placebo_lift(
    inputs: Inputs,
    rates: BaseRates,
    score: LoadScore,
    sets: dict[str, set[str]],
    weights: dict[str, float],
    familiarity: dict[tuple[str, str], str],
) -> float | None:
    """A(L) - mean A over K=20 other skills matched on set size and familiarity mix, seed 148."""
    own = sets.get(score.skill, set())
    if not own:
        return None
    load = inputs.loads[score.load_id]
    window = _window_signatures(inputs, load)
    # Familiarity mix of a candidate set, computed for the *candidate's* own creation date.
    mix = {s: tuple(sorted(familiarity[(s, c)] for c in cs)) for s, cs in sets.items() if cs}
    mine = mix.get(score.skill, ())
    candidates = [s for s in sorted(sets) if s != score.skill and sets[s]]
    tiers = [
        [s for s in candidates if abs(len(sets[s]) - len(own)) <= 1 and mix.get(s) == mine],
        [s for s in candidates if abs(len(sets[s]) - len(own)) <= 1],
        candidates,
    ]
    picks = next((tier for tier in tiers if tier), [])
    if not picks:
        return None
    rng = random.Random(schema.SEED + int(score.load_id, 16))
    draws = [_set_adherence(sets[rng.choice(picks)], weights, window) for _ in range(schema.PLACEBO_K)]
    return score.observed - (sum(draws) / len(draws))


# ------------------------------------------------------------------ shrinkage (D9)
@dataclass
class SkillStats:
    skill: str
    lifts: list[float]

    @property
    def n_loads(self) -> int:
        return len(self.lifts)

    @property
    def mean(self) -> float:
        return _mean(self.lifts)


def _fit_prior(stats: dict[str, SkillStats]) -> tuple[float, float, dict[str, float]]:
    """Normal-normal empirical Bayes: pooled mean, between-skill variance, per-skill sampling variance.

    The prior is fitted on ranked skills only (>= MIN_RANKED_LOADS scorable loads). A single-load
    skill's lift is too noisy to set the prior, but it is still shrunk toward it.
    """
    base = {sk: s for sk, s in stats.items() if s.n_loads >= schema.MIN_RANKED_LOADS} or stats
    per_load_var = {sk: _variance(s.lifts) for sk, s in base.items()}
    pooled = _mean(per_load_var.values())
    if pooled is None:
        pooled = _variance([s.mean for s in base.values()])
    var_i = {
        sk: (per_load_var[sk] / s.n_loads if s.n_loads >= schema.MIN_RANKED_LOADS else pooled)
        for sk, s in stats.items()
    }
    mu = _mean([s.mean for s in base.values()])
    tau2 = 0.0
    if len(base) >= 2:
        tau2 = max(0.0, _variance([s.mean for s in base.values()]) - _mean(var_i[sk] for sk in base))
    return mu, tau2, var_i


def _shrink(stats: dict[str, SkillStats]) -> tuple[dict[str, float], float, float]:
    mu, tau2, var_i = _fit_prior(stats)
    out = {}
    for sk, s in stats.items():
        vi = var_i[sk]
        out[sk] = (tau2 * s.mean + vi * mu) / (tau2 + vi) if (tau2 + vi) > 0 else mu
    return out, mu, tau2


def _bootstrap(
    stats: dict[str, SkillStats], clusters: dict[str, list[tuple[str, float]]]
) -> dict[str, tuple[float, float]]:
    """95% percentile CIs for the shrunken mean, resampling whole cluster keys (1,000 draws, seed 148)."""
    keys = sorted(clusters)
    rng = random.Random(schema.SEED)
    draws: dict[str, list[float]] = defaultdict(list)
    for _ in range(schema.BOOTSTRAP_RESAMPLES):
        resampled: dict[str, list[float]] = defaultdict(list)
        for _ in keys:
            for skill, value in clusters[rng.choice(keys)]:
                resampled[skill].append(value)
        subset = {sk: SkillStats(sk, vals) for sk, vals in resampled.items() if vals}
        if not subset:
            continue
        shrunk, _, _ = _shrink(subset)
        for sk, value in shrunk.items():
            draws[sk].append(value)
    out = {}
    for sk in stats:
        values = draws.get(sk)
        if values:
            out[sk] = (_percentile(values, 0.025), _percentile(values, 0.975))
    return out


# ------------------------------------------------------------------ familiarity strata (D6)
def _strata_rows(
    inputs: Inputs,
    rates: BaseRates,
    scores: dict[str, LoadScore],
    clusters_of: dict[str, str],
) -> list[dict]:
    cells: dict[tuple[str, str], list[tuple[str, float, float]]] = defaultdict(list)  # (load, w, a-p)
    loads_in_cell: dict[tuple[str, str], set[str]] = defaultdict(set)
    for lid, score in scores.items():
        for e in score.entries:
            fam = familiarity_of(inputs, rates, score.skill, e.signature)
            prior = prior_knowledge(e.signature, inputs.program_map)
            cells[(fam, prior)].append((lid, e.weight, e.observed - e.expected))
            loads_in_cell[(fam, prior)].add(lid)

    def aggregate(keys: set[tuple[str, str]]) -> tuple[float, int, list[tuple[str, float, float]]]:
        rows = [r for key in sorted(keys) for r in cells.get(key, [])]
        total = sum(w for _, w, _ in rows)
        value = sum(w * v for _, w, v in rows) / total if total else None
        n_loads = len({lid for lid, _, _ in rows})
        return value, n_loads, rows

    thin = any(len(loads_in_cell.get(key, ())) < schema.STRATUM_MIN_LOADS for key in cells)
    groups: list[tuple[str, str, set[tuple[str, str]]]] = []
    if thin:
        novel_local = {k for k in cells if k == ("novel", "local")}
        groups = [
            ("novel+local", "all", novel_local),
            ("rest", "all", set(cells) - novel_local),
        ]
    else:
        for key in sorted(cells):
            groups.append((key[0], key[1], {key}))

    rows_out = []
    for label, prior, keys in groups:
        if not keys:
            continue
        value, n_loads, rows = aggregate(keys)
        if value is None:
            continue
        ci = _bootstrap_rows(rows, clusters_of)
        rows_out.append({
            "corpus": inputs.corpus, "familiarity": label, "prior_knowledge": prior,
            "n_loads": n_loads, "lift": value, "ci_low": ci[0], "ci_high": ci[1], "pooled": thin,
        })
    return rows_out


def _bootstrap_rows(rows: list[tuple[str, float, float]], clusters_of: dict[str, str]):
    by_cluster: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for lid, weight, value in rows:
        by_cluster[clusters_of[lid]].append((weight, value))
    keys = sorted(by_cluster)
    if not keys:
        return (None, None)
    rng = random.Random(schema.SEED + 1)
    draws = []
    for _ in range(schema.BOOTSTRAP_RESAMPLES):
        pairs = [p for _ in keys for p in by_cluster[rng.choice(keys)]]
        total = sum(w for w, _ in pairs)
        if total:
            draws.append(sum(w * v for w, v in pairs) / total)
    return (_percentile(draws, 0.025), _percentile(draws, 0.975))


# ------------------------------------------------------------------ provenance, bloat (D16)
def provenance_group(inputs: Inputs, skill: str) -> str:
    prov = inputs.provenance.get(skill)
    if prov is None:
        return "no-agent-trace"
    touched = bool(prov["agent_touched"]) or prov["created_by"] in ("agent", "learn")
    if not touched:
        touched = any(
            c.get("actor") in ("agent", "curator") and c.get("action") in ("create", "patch", "write_file")
            for c in (prov.get("changes") or [])
        )
    return "agent-touched" if touched else "no-agent-trace"


def _bloat(inputs: Inputs, supported: set[str]) -> dict:
    agent = sorted(s for s in inputs.provenance if provenance_group(inputs, s) == "agent-touched")
    loaded = {ld["skill"] for ld in inputs.loads.values()}
    if not agent:
        return {"computable": False, "reason": "no agent-touched skills in provenance"}
    never = [s for s in agent if s not in loaded]
    loaded_unsupported = [s for s in agent if s in loaded and s not in supported]
    return {
        "computable": True,
        "n_agent_touched": len(agent),
        "n_never_loaded": len(never),
        "share_never_loaded": len(never) / len(agent),
        "n_loaded_unsupported": len(loaded_unsupported),
        "share_loaded_unsupported": len(loaded_unsupported) / len(agent),
        "never_loaded": never,
        "loaded_unsupported": loaded_unsupported,
    }


# ------------------------------------------------------------------ assembly
def _set_size(sets: dict[str, set[str]], skill: str) -> int:
    return len(sets.get(skill, ()))


def build_potency(
    inputs: Inputs,
    rates: BaseRates,
    sets: dict[str, set[str]] | None = None,
    scores: dict[str, LoadScore] | None = None,
) -> tuple[list[dict], list[dict], dict]:
    sets = prescribed_sets(inputs, rates) if sets is None else sets
    scores = score_loads(inputs, rates) if scores is None else scores
    weights = {sig: rates.weight(sig) for cs in sets.values() for sig in cs}
    familiarity = {
        (skill, sig): familiarity_of(inputs, rates, skill, sig)
        for skill, cs in sets.items() for sig in cs
    }
    avoid_by_skill: dict[str, int] = defaultdict(int)
    for row in inputs.evidence:
        load = inputs.loads.get(row["load_id"])
        if load is not None and row["obligation"] == "avoid" and row["status"] == "supported_agreement":
            avoid_by_skill[load["skill"]] += 1
    rule_sources: dict[str, set[str]] = defaultdict(set)
    for rule in inputs.rules.values():
        rule_sources[rule["skill"]].add(rule["rule_source"])
    by_skill: dict[str, list[LoadScore]] = defaultdict(list)
    for score in scores.values():
        by_skill[score.skill].append(score)

    stats = {sk: SkillStats(sk, [s.lift for s in sorted(v, key=lambda s: s.load_id)])
             for sk, v in by_skill.items()}
    shrunk, mu, tau2 = _shrink(stats)
    clusters_of = {lid: s.cluster_key for lid, s in scores.items()}
    clusters: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for lid, s in scores.items():
        clusters[s.cluster_key].append((s.skill, s.lift))
    ci = _bootstrap(stats, clusters)

    # Popularity check (D9)
    ranked_skills = sorted(sk for sk, s in stats.items() if s.n_loads >= schema.MIN_RANKED_LOADS)
    rho_loads = spearman([shrunk[sk] for sk in ranked_skills],
                         [stats[sk].n_loads for sk in ranked_skills])
    rho_rate = spearman(
        [shrunk[sk] for sk in ranked_skills],
        [_mean([rates.raw_before(sig, None) for sig in sets.get(sk, ())]) if sets.get(sk) else 0.0
         for sk in ranked_skills],
    )
    popularity = {
        "n_skills": len(ranked_skills),
        "load_count_rho": rho_loads,
        "mean_base_rate_rho": rho_rate,
        "threshold": schema.POPULARITY_FLAG_RHO,
        "flagged": any(r is not None and abs(r) >= schema.POPULARITY_FLAG_RHO for r in (rho_loads, rho_rate)),
    }

    # Sensitivity: drop incomplete and overlap windows (D8)
    stable = {sk: SkillStats(sk, [s.lift for s in sorted(v, key=lambda s: s.load_id)
                                  if not (set(s.flags) & {"incomplete", "overlap"})])
              for sk, v in by_skill.items()}
    stable = {sk: s for sk, s in stable.items() if s.n_loads}
    stable_shrunk, _, _ = _shrink(stable) if stable else ({}, None, None)
    sensitivity = {
        "excluded_flags": ["incomplete", "overlap"],
        "rows": [
            {"skill": sk, "n_loads": stats[sk].n_loads, "lift": stats[sk].mean,
             "n_loads_stable": stable[sk].n_loads if sk in stable else 0,
             "lift_shrunk_stable": stable_shrunk.get(sk)}
            for sk in sorted(stats)
        ],
    }

    rows = []
    for skill in sorted(by_skill):
        s = stats[skill]
        scores_here = by_skill[skill]
        set_ = sets.get(skill, set())
        generic_only = not set_
        placebo = [p for p in (placebo_lift(inputs, rates, sc, sets, weights, familiarity)
                               for sc in scores_here) if p is not None]
        lo, hi = ci.get(skill, (None, None))
        label = None
        if lo is not None and hi is not None:
            label = "positive" if lo > 0 else "negative" if hi < 0 else "inconclusive"
            if len({sc.cluster_key for sc in scores_here}) < MIN_CI_CLUSTERS:
                label = "inconclusive"  # a cluster bootstrap over one cluster has no variance to estimate
        determinate = sum(len(sc.entries) for sc in scores_here)
        n_supported = sum(sc.n_supported for sc in scores_here)
        rows.append({
            "corpus": inputs.corpus,
            "skill": skill,
            "n_loads": s.n_loads,
            "n_clusters": len({sc.cluster_key for sc in scores_here}),
            "set_size": _set_size(sets, skill),
            "follow_rate": (n_supported / determinate) if determinate else None,
            "mean_a": _mean(sc.observed for sc in scores_here),
            "mean_a_hat": _mean(sc.expected for sc in scores_here),
            "lift": s.mean,
            "lift_shrunk": shrunk.get(skill),
            "ci_low": lo,
            "ci_high": hi,
            "placebo_lift": _mean(placebo),
            "avoid_matches": avoid_by_skill.get(skill, 0),
            "label": label,
            "supported": (s.n_loads >= schema.MIN_SUPPORTED_LOADS
                          and len({sc.cluster_key for sc in scores_here}) >= schema.MIN_SUPPORTED_CLUSTERS
                          and not generic_only),
            "ranked": s.n_loads >= schema.MIN_RANKED_LOADS and not generic_only,
            "generic_only": generic_only,
            "auto": rule_sources.get(skill, {"auto"}) == {"auto"},
            "provenance_group": provenance_group(inputs, skill),
        })
    rows.sort(key=lambda r: (not r["ranked"], -(r["lift_shrunk"] if r["lift_shrunk"] is not None else -math.inf),
                             r["skill"]))

    # Skills whose whole prescribed set is empty never enter the ranking but are reported.
    reported = {r["skill"] for r in rows}
    for skill in sorted(set(sets) | {ld["skill"] for ld in inputs.loads.values()}):
        if skill in by_skill or skill in reported:
            continue
        rows.append({
            "corpus": inputs.corpus, "skill": skill, "n_loads": 0, "n_clusters": 0,
            "set_size": _set_size(sets, skill), "follow_rate": None, "mean_a": None, "mean_a_hat": None,
            "lift": None, "lift_shrunk": None, "ci_low": None, "ci_high": None, "placebo_lift": None,
            "avoid_matches": avoid_by_skill.get(skill, 0), "label": None, "supported": False,
            "ranked": False, "generic_only": _set_size(sets, skill) == 0,
            "auto": rule_sources.get(skill, {"auto"}) == {"auto"},
            "provenance_group": provenance_group(inputs, skill),
        })

    strata = _strata_rows(inputs, rates, scores, clusters_of)
    supported = {r["skill"] for r in rows if r["supported"]}
    evidenced = {row["load_id"] for row in inputs.evidence}
    detail = {
        "prior": {"mean": mu, "tau2": tau2, "n_skills": len(stats),
                  "n_prior_skills": sum(1 for s in stats.values() if s.n_loads >= schema.MIN_RANKED_LOADS)},
        "popularity": popularity,
        "sensitivity": sensitivity,
        "bloat": _bloat(inputs, supported),
        "n_ranked": sum(1 for r in rows if r["ranked"]),
        "n_supported": len(supported),
        "n_insufficient_loads": len(evidenced - set(scores)),
    }
    return rows, strata, detail


# ------------------------------------------------------------------ CLI
def load_program_map(path, data_dir=None, corpus_dir=None) -> dict[str, str]:
    candidates = [Path(path)] if path else []
    if not path:
        if data_dir is not None:
            candidates.append(Path(data_dir) / "program_map.json")
        if corpus_dir is not None:
            candidates.append(Path(corpus_dir) / "program_map.json")
    for candidate in candidates:
        if candidate.exists():
            mapping = io.read_json(candidate)
            return {str(k): str(v) for k, v in mapping.items()}
    return {}


def run_corpus(corpus_dir, program_map: dict[str, str] | None = None) -> dict:
    """Score one corpus, write out/potency.csv, out/strata.csv and out/experiments.json."""
    corpus_dir = Path(corpus_dir)
    inputs = read_inputs(corpus_dir, program_map)
    rates = BaseRates(inputs)
    sets = prescribed_sets(inputs, rates)
    scores = score_loads(inputs, rates)
    rows, strata, detail = build_potency(inputs, rates, sets, scores)
    out = corpus_dir / "out"
    io.write_output_csv(out / "potency.csv", rows)
    io.write_output_csv(out / "strata.csv", strata)
    payload = {
        "corpus": inputs.corpus,
        "experiments": experiments.run_experiments(corpus_dir, inputs=inputs, scores=scores, sets=sets),
        "ranking": {k: detail[k] for k in ("prior", "n_ranked", "n_supported")},
        "popularity": detail["popularity"],
        "sensitivity": detail["sensitivity"],
        "bloat": detail["bloat"],
    }
    io.write_json(out / "experiments.json", payload)
    return {"corpus": inputs.corpus, "skills": len(rows), "ranked": detail["n_ranked"],
            "supported": detail["n_supported"]}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog='python -m potency.score',
                                description='Analysis: lift, controls, ranking, experiments -> '
                                            'out/potency.csv, strata.csv, experiments.json.')
    p.add_argument('--corpus', default=None, help='corpus (default: every corpus in the data dir)')
    p.add_argument('--data', default=None, help='data dir')
    p.add_argument('--program-map', default=None, help='public/local program map JSON')
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    data_dir = io.resolve_data_dir(args.data)
    if not data_dir.is_dir():
        print(f"score: data dir {data_dir} does not exist", file=sys.stderr)
        return 1
    corpus_dirs = io.corpus_dirs(data_dir, args.corpus)
    if not corpus_dirs:
        print(f"score: no corpus with sessions.jsonl under {data_dir}", file=sys.stderr)
        return 1
    for corpus_dir in corpus_dirs:
        program_map = load_program_map(args.program_map, data_dir, corpus_dir)
        try:
            summary = run_corpus(corpus_dir, program_map)
        except FileNotFoundError as exc:
            print(f"score: {exc}", file=sys.stderr)
            return 1
        print(f"score: {summary['corpus']}: {summary['skills']} skills, "
              f"{summary['ranked']} ranked, {summary['supported']} supported")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
