"""Analysis: charts and summary -> out/potency.png, out/status.png, out/summary.md (tasks 6.1).

Reads only derived files under ``<data>/<corpus>/``: the analysis-stage outputs in ``out/`` plus the D12
tables (used for the appendix, the excluded-load counts and the bloat statistic). Every optional input
degrades to a "not computable" note instead of an error, so the evidence table and the status chart stay
a complete demo when the expectation model or the ranking is missing (design D18).

Determinism (D17): every file is written with utf-8 and ``\\n``, skills are sorted by value then name,
no timestamps enter the output, and matplotlib uses the Agg backend with a fixed dpi. PNG bytes are not
promised to match across platforms: CI compares CSV/JSON hashes only.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # non-interactive backend (D17); must precede the pyplot import
import matplotlib.pyplot as plt  # noqa: E402

from potency import io, schema  # noqa: E402

DPI = 100
FIGSIZE = (11.0, 6.5)
MAX_RANKED_BARS = 40
MAX_STATUS_BARS = 24
MISSING = "not computable"
# Written by this stage; excluded from the input listing so a rerun is byte-identical.
REPORT_OUTPUTS = ("potency.png", "status.png", "summary.md")

STATUS_COLORS = {
    "supported_agreement": "#2a7f62",
    "no_observed_agreement": "#c46a3b",
    "insufficient_evidence": "#8a8a8a",
    "not_applicable": "#d9d9d9",
}
PROVENANCE_COLORS = {
    "agent-touched": "#b5651d",
    "no-agent-trace": "#2b6cb0",
}
EXPERIMENT_SECTIONS = (
    ("pre_post_creation", "Pre/post creation (S1)"),
    ("edit_response", "Edit-response (S2)"),
    ("paired_runs", "Paired-run validation (S3)"),
    ("trigger_split", "Trigger split"),
)
CAVEAT_ENDGENEITY = (
    "Observational lift is an upper bound on skill influence because loads are endogenous: an agent "
    "loads a skill when it already intends the task, so part of the measured lift would have happened "
    "anyway. The natural experiments (S1-S3) and the trigger split are the only causal reads, and they "
    "are reported as such."
)
DISCLOSURE_LOADED_ONLY = (
    "The evidence covers loaded episodes only. Skills that were available but never loaded are not "
    "observed, so this report makes no claim about them."
)


# ---------------------------------------------------------------- small numeric helpers
def _f(value, default=None):
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _i(value, default=0):
    number = _f(value)
    return default if number is None else int(number)


def _truthy(value) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in ("1", "true", "t", "yes", "y")


def fmt(value, digits: int = 3, missing: str = MISSING) -> str:
    number = _f(value)
    return missing if number is None else f"{number:.{digits}f}"


def _median(values):
    values = sorted(values)
    if not values:
        return None
    mid = len(values) // 2
    if len(values) % 2:
        return values[mid]
    return (values[mid - 1] + values[mid]) / 2.0


def _rank(values):
    """Average ranks, 1-based, with ties shared."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def _pearson(xs, ys):
    n = len(xs)
    if n < 2:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx <= 0 or syy <= 0:
        return None
    return sxy / (sxx * syy) ** 0.5


def spearman(xs, ys):
    if len(xs) != len(ys):
        return None
    return _pearson(_rank(xs), _rank(ys))


# ---------------------------------------------------------------- inputs
def _display(path: Path, base: Path | None) -> str:
    if base is not None:
        try:
            return Path(path).resolve().relative_to(Path(base).resolve()).as_posix()
        except ValueError:
            pass
    return Path(path).as_posix()


def load_inputs(corpus_dir: Path) -> dict:
    """Read one corpus's derived files; optional files come back empty or None."""
    corpus_dir = Path(corpus_dir)
    out = corpus_dir / "out"
    inputs: dict = {"evidence": io.read_csv(out / "evidence.csv")}
    inputs["present"] = (sorted(p.name for p in out.iterdir()
                                if p.is_file() and p.name not in REPORT_OUTPUTS)
                         if out.is_dir() else [])
    for key, name in (("potency", "potency.csv"), ("strata", "strata.csv"), ("expected", "expected.csv")):
        path = out / name
        inputs[key] = io.read_csv(path) if path.exists() else []
    for key, name in (("experiments", "experiments.json"), ("expect_eval", "expect_eval.json")):
        path = out / name
        inputs[key] = io.read_json(path) if path.exists() else None
    for table in ("rules", "provenance", "loads", "sessions"):
        inputs[table] = io.read_table(corpus_dir, table)
    inputs["corpus"] = _corpus_name(inputs["evidence"], corpus_dir)
    return inputs


def _corpus_name(evidence: list[dict], corpus_dir: Path) -> str:
    for row in evidence:
        if row.get("corpus"):
            return str(row["corpus"])
    return Path(corpus_dir).name


def _ranked(potency: list[dict]) -> list[dict]:
    return [row for row in potency if _truthy(row.get("ranked"))]


def _lift_sort_key(row: dict):
    lift = _f(row.get("lift_shrunk"))
    return (-(lift if lift is not None else float("-inf")), str(row.get("skill", "")))


# ---------------------------------------------------------------- headline numbers
def headline_novel_local(strata: list[dict]) -> tuple:
    """Headline 1: median lift on novel+local prescribed commands (D6/D9)."""
    pooled, novel = [], []
    for row in strata:
        if str(row.get("prior_knowledge", "")).strip() != "local":
            continue
        lift = _f(row.get("lift"))
        if lift is None:
            continue
        if _truthy(row.get("pooled")):
            pooled.append((lift, _i(row.get("n_loads"))))
        elif str(row.get("familiarity", "")).strip() == "novel":
            novel.append((lift, _i(row.get("n_loads"))))
    chosen, basis = (pooled, "pooled novel+local cells") if pooled else (novel, "novel+local cells")
    if not chosen:
        return None, 0, "no novel+local row in `strata.csv`"
    return _median([c[0] for c in chosen]), sum(c[1] for c in chosen), basis


def headline_provenance(potency: list[dict], experiments) -> dict:
    """Headline 2: agent-touched vs no-agent-trace lift, pre/post when computable (D16)."""
    pre = _experiment(experiments, "pre_post_creation")
    if isinstance(pre, dict) and _truthy(pre.get("computable")):
        groups = pre.get("groups")
        if not isinstance(groups, dict):
            result = pre.get("result")
            groups = result.get("groups") if isinstance(result, dict) else None
        if isinstance(groups, dict):
            touched = _f(_group_lift(groups.get("agent-touched")))
            untouched = _f(_group_lift(groups.get("no-agent-trace")))
            if touched is not None and untouched is not None:
                return {"agent_touched": touched, "no_agent_trace": untouched,
                        "basis": "pre/post creation, difference-in-differences"}
    sums = {group: [0.0, 0] for group in schema.PROVENANCE_GROUPS}
    for row in _ranked(potency):
        group = str(row.get("provenance_group", "")).strip()
        lift = _f(row.get("lift_shrunk"))
        if lift is None or group not in sums:
            continue
        weight = max(_i(row.get("n_loads")), 1)
        sums[group][0] += lift * weight
        sums[group][1] += weight
    return {
        "agent_touched": sums["agent-touched"][0] / sums["agent-touched"][1]
        if sums["agent-touched"][1] else None,
        "no_agent_trace": sums["no-agent-trace"][0] / sums["no-agent-trace"][1]
        if sums["no-agent-trace"][1] else None,
        "basis": "observational, load-weighted over ranked skills",
    }


def _group_lift(group):
    if isinstance(group, dict):
        return group.get("lift")
    return group


def headline_ci_zero(potency: list[dict]) -> tuple:
    """Headline 3: ranked skills whose CI includes or is below zero (D9)."""
    ranked = _ranked(potency)
    without_ci = 0
    count = 0
    for row in ranked:
        low = _f(row.get("ci_low"))
        if low is None:
            without_ci += 1
        elif low <= 0.0:
            count += 1
    return count, len(ranked), without_ci


# ---------------------------------------------------------------- popularity + experiments
def _experiment(experiments, key):
    if isinstance(experiments, dict):
        return experiments.get(key)
    return None


def popularity_check(potency: list[dict], experiments) -> list[dict]:
    """Spearman of potency vs load count and vs the set's mean base rate (D9)."""
    reported = _experiment(experiments, "popularity_check")
    reported = reported if isinstance(reported, dict) else {}
    out = []
    loads_rho = _f(reported.get("spearman_load_count"))
    source = "`experiments.json`"
    if loads_rho is None:
        lifts, counts = [], []
        for row in _ranked(potency):
            lift, count = _f(row.get("lift_shrunk")), _f(row.get("n_loads"))
            if lift is None or count is None:
                continue
            lifts.append(lift)
            counts.append(count)
        loads_rho = spearman(lifts, counts)
        source = "computed here from `potency.csv`"
    out.append({"label": "potency vs load count", "rho": loads_rho, "source": source})

    base_rho = _f(reported.get("spearman_base_rate"))
    out.append({"label": "potency vs mean base rate of the prescribed set", "rho": base_rho,
                "source": "`experiments.json`" if base_rho is not None
                else "the score stage does not export the mean base rate per skill"})
    return out


def _experiment_lines(experiments) -> list[str]:
    lines: list[str] = []
    available = isinstance(experiments, dict)
    for key, title in EXPERIMENT_SECTIONS:
        entry = _experiment(experiments, key)
        lines += [f"### {title}", ""]
        if entry is None:
            reason = "no `experiments.json`" if not available else f"`experiments.json` has no `{key}` entry"
            lines.append(f"Not computable: {reason}.")
        elif isinstance(entry, dict) and "computable" in entry and not _truthy(entry.get("computable")):
            lines.append(f"Not computable: {entry.get('reason') or entry.get('note') or 'inputs missing'}.")
        elif isinstance(entry, dict):
            result = entry.get("result")
            if isinstance(result, dict):
                lines.extend(_kv_lines(result))
            else:
                lines.extend(_kv_lines({k: v for k, v in entry.items() if k != "computable"}))
        else:
            lines.append("Not computable: unexpected `experiments.json` shape.")
        lines.append("")
    return lines


def _kv_lines(mapping: dict) -> list[str]:
    lines = []
    for key in sorted(mapping, key=str):
        value = mapping[key]
        if isinstance(value, dict):
            pairs = ", ".join(f"{k}={_scalar(value[k])}" for k in sorted(value, key=str))
            lines.append(f"- `{key}`: {pairs}")
        else:
            lines.append(f"- `{key}`: {_scalar(value)}")
    return lines or ["- no entries"]


def _scalar(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return f"{value:.3f}"
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    return str(value)


# ---------------------------------------------------------------- charts
def plot_potency(corpus: str, potency: list[dict], path: Path) -> None:
    """Ranked skills by shrunken lift with 95% CI bars, colored by provenance (D9)."""
    ranked = sorted(_ranked(potency), key=_lift_sort_key)
    shown = ranked[:MAX_RANKED_BARS]
    fig, ax = plt.subplots(figsize=FIGSIZE, dpi=DPI)
    if not shown:
        ax.text(0.5, 0.5, "no ranked skills (potency.csv missing or empty)",
                ha="center", va="center", transform=ax.transAxes, fontsize=12)
        ax.set_axis_off()
    else:
        order = list(reversed(shown))  # best skill at the top
        labels, values, lows, highs, colors, edges, widths = [], [], [], [], [], [], []
        for row in order:
            lift = _f(row.get("lift_shrunk"), 0.0)
            low, high = _f(row.get("ci_low")), _f(row.get("ci_high"))
            low = lift if low is None else low
            high = lift if high is None else high
            labels.append(str(row.get("skill", "")))
            values.append(lift)
            lows.append(max(lift - low, 0.0))
            highs.append(max(high - lift, 0.0))
            colors.append(PROVENANCE_COLORS.get(str(row.get("provenance_group", "")).strip(), "#999999"))
            supported = _truthy(row.get("supported"))
            edges.append("black" if supported else "none")
            widths.append(1.4 if supported else 0.0)
        y = list(range(len(order)))
        ax.barh(y, values, color=colors, edgecolor=edges, linewidth=widths)
        ax.errorbar(values, y, xerr=[lows, highs], fmt="none", ecolor="black", elinewidth=1.0, capsize=3)
        ax.set_yticks(y)
        ax.set_yticklabels([f"{label} *" if _truthy(row.get("supported")) else label
                            for label, row in zip(labels, order)], fontsize=9)
        ax.axvline(0.0, color="black", linewidth=0.8, linestyle="--")
        ax.set_xlabel("shrunken lift (observed minus expected agreement)")
        ax.legend(handles=[plt.Rectangle((0, 0), 1, 1, color=color) for color in PROVENANCE_COLORS.values()]
                  + [plt.Rectangle((0, 0), 1, 1, facecolor="none", edgecolor="black")],
                  labels=list(PROVENANCE_COLORS) + ["supported (>=5 loads, >=3 clusters)"],
                  loc="lower right", fontsize=8, frameon=False)
        title = f"{corpus}: shrunken lift with 95% CI"
        if len(ranked) > len(shown):
            title += f" (top {len(shown)} of {len(ranked)})"
        ax.set_title(title)
        ax.grid(axis="x", color="#dddddd", linewidth=0.6)
        ax.set_axisbelow(True)
    fig.tight_layout()
    fig.savefig(path, dpi=DPI, facecolor="white")
    plt.close(fig)


def plot_status(corpus: str, evidence: list[dict], path: Path) -> None:
    """Per-skill stacked bars of the four evidence statuses, with denominators (D18)."""
    counts: dict[str, dict[str, int]] = {}
    for row in evidence:
        status = str(row.get("status", ""))
        if status not in schema.STATUSES:
            continue
        skill = str(row.get("skill", ""))
        counts.setdefault(skill, {name: 0 for name in schema.STATUSES})[status] += 1
    skills = sorted(counts, key=lambda s: (-sum(counts[s].values()), s))[:MAX_STATUS_BARS]

    fig, ax = plt.subplots(figsize=FIGSIZE, dpi=DPI)
    if not skills:
        ax.text(0.5, 0.5, "no evidence rows", ha="center", va="center",
                transform=ax.transAxes, fontsize=12)
        ax.set_axis_off()
    else:
        x = list(range(len(skills)))
        bottoms = [0] * len(skills)
        for status in schema.STATUSES:
            values = [counts[skill][status] for skill in skills]
            ax.bar(x, values, bottom=bottoms, color=STATUS_COLORS[status], label=status,
                   edgecolor="white", linewidth=0.6)
            bottoms = [b + v for b, v in zip(bottoms, values)]
        ax.set_xticks(x)
        ax.set_xticklabels([f"{skill}\nn={_denominator(counts[skill])}" for skill in skills],
                           rotation=30, ha="right", fontsize=8)
        ax.set_ylabel("evidence rows (load x rule)")
        title = f"{corpus}: evidence status per skill"
        if len(counts) > len(skills):
            title += f" (top {len(skills)} of {len(counts)})"
        ax.set_title(title)
        ax.legend(fontsize=8, frameon=False, ncol=2)
        ax.grid(axis="y", color="#dddddd", linewidth=0.6)
        ax.set_axisbelow(True)
    fig.tight_layout()
    fig.savefig(path, dpi=DPI, facecolor="white")
    plt.close(fig)


def _denominator(counts: dict[str, int]) -> int:
    """Rows that enter adherence denominators: everything except not_applicable (D18)."""
    return sum(v for status, v in counts.items() if status != "not_applicable")


# ---------------------------------------------------------------- summary sections
def _inputs_line(corpus_dir: Path, inputs: dict) -> str:
    base = Path(corpus_dir).parent
    out = Path(corpus_dir) / "out"
    parts = [f"`{_display(out / 'evidence.csv', base)}` ({len(inputs['evidence'])} rows)"]
    for key, name in (("potency", "potency.csv"), ("strata", "strata.csv"), ("expected", "expected.csv")):
        if name in inputs["present"]:
            parts.append(f"`{_display(out / name, base)}` ({len(inputs[key])} rows)")
    for key, name in (("experiments", "experiments.json"), ("expect_eval", "expect_eval.json")):
        if inputs[key] is not None:
            parts.append(f"`{_display(out / name, base)}`")
    for table in ("rules", "provenance", "loads", "sessions"):
        if inputs[table]:
            parts.append(f"`{_display(Path(corpus_dir) / (table + '.jsonl'), base)}` ({len(inputs[table])} rows)")
    return "Inputs read: " + ", ".join(parts) + "."


def _headline_lines(inputs: dict) -> list[str]:
    lift_nl, nl_loads, nl_basis = headline_novel_local(inputs["strata"])
    provenance = headline_provenance(inputs["potency"], inputs["experiments"])
    ci_zero, n_ranked, no_ci = headline_ci_zero(inputs["potency"])
    touched, untouched = provenance["agent_touched"], provenance["no_agent_trace"]
    difference = None if touched is None or untouched is None else touched - untouched
    lines = [
        "## Headline numbers",
        "",
        "| # | Number | Value |",
        "| --- | --- | --- |",
        f"| 1 | Median lift on novel+local prescribed commands | **{fmt(lift_nl)}**"
        f" ({nl_basis}, {nl_loads} loads) |",
        f"| 2 | Lift, agent-touched vs no-agent-trace | **{fmt(touched)}** vs **{fmt(untouched)}**"
        f" (difference {fmt(difference)}; {provenance['basis']}) |",
        f"| 3 | Ranked skills whose 95% CI includes or is below zero | **{ci_zero} of {n_ranked}**"
        + (f" ({no_ci} without a CI)" if no_ci else "") + " |",
        "",
    ]
    return lines


def _ranking_lines(inputs: dict) -> list[str]:
    potency = inputs["potency"]
    ranked = sorted(_ranked(potency), key=_lift_sort_key)
    lines = ["## Ranking", ""]
    if not potency:
        lines += ["Not computable: `out/potency.csv` is missing or empty, so this corpus has no lift or "
                  "ranking. The evidence section below still stands on its own.", ""]
        return lines
    if not ranked:
        lines += ["No skill has enough scorable loads to be ranked (`ranked` is false for every row).", ""]
        lines += _insufficient_block(inputs)
        return lines
    supported = sum(1 for row in ranked if _truthy(row.get("supported")))
    lines += [
        f"{len(ranked)} ranked skills (>=2 scorable loads); **{supported} marked supported** "
        f"(>=5 loads and >=3 distinct cluster keys). A CI that spans zero is reported as inconclusive.",
        "",
        "| skill | loads | clusters | set | follow | lift | shrunken | 95% CI | placebo | label | "
        "supported | provenance |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: | --- | :---: | --- |",
    ]
    for row in ranked:
        low, high = _f(row.get("ci_low")), _f(row.get("ci_high"))
        ci = f"[{low:.3f}, {high:.3f}]" if low is not None and high is not None else MISSING
        lines.append("| " + " | ".join([
            str(row.get("skill", "")),
            str(_i(row.get("n_loads"))),
            str(_i(row.get("n_clusters"))),
            str(_i(row.get("set_size"))),
            fmt(row.get("follow_rate")),
            fmt(row.get("lift")),
            fmt(row.get("lift_shrunk")),
            ci,
            fmt(row.get("placebo_lift")),
            str(row.get("label", "")),
            "yes" if _truthy(row.get("supported")) else "no",
            str(row.get("provenance_group", "")),
        ]) + " |")
    lines.append("")
    if supported == 0:
        lines += ["Zero skills are supported in this corpus. An empty supported set is a valid outcome; "
                  "draw no skill-level conclusions from the ranking above.", ""]
    generic = sorted(str(row.get("skill", "")) for row in potency if _truthy(row.get("generic_only")))
    if generic:
        lines += [f"Generic-only (every prescribed command above the base-rate ceiling): "
                  f"{', '.join(generic)}.", ""]
    lines += _insufficient_block(inputs)
    return lines


def _insufficient_block(inputs: dict) -> list[str]:
    missing = _insufficient_skills(inputs)
    if not missing:
        return []
    lines = ["### Insufficient data", "",
             "Skills with too few scorable loads for the ranking (reported, not ranked):", ""]
    for skill, load_count in missing:
        lines.append(f"- `{skill}`: {load_count} scorable load{'' if load_count == 1 else 's'}")
    lines.append("")
    return lines


def _insufficient_skills(inputs: dict) -> list:
    ranked_skills = {str(row.get("skill", "")) for row in _ranked(inputs["potency"])}
    scored = {str(row.get("skill", "")) for row in inputs["potency"]}
    counts: dict[str, int] = {}
    for row in inputs["loads"]:
        flags = set(row.get("flags") or [])
        if flags & {"maintenance", "repeat"} or row.get("version_source") == "version_unknown":
            continue
        skill = str(row.get("skill", ""))
        counts[skill] = counts.get(skill, 0) + 1
    missing = [(skill, counts[skill]) for skill in counts
               if skill not in ranked_skills and skill not in scored]
    return sorted(missing)


def _popularity_lines(inputs: dict) -> list[str]:
    checks = popularity_check(inputs["potency"], inputs["experiments"])
    flagged = [c["label"] for c in checks
               if c["rho"] is not None and abs(c["rho"]) >= schema.POPULARITY_FLAG_RHO]
    lines = ["## Popularity check", ""]
    if all(c["rho"] is None for c in checks):
        lines += [f"Not computable: neither `potency.csv` nor `experiments.json` supplies a correlation.",
                  ""]
        return lines
    if flagged:
        lines.append(f"**Flagged**: |rho| >= {schema.POPULARITY_FLAG_RHO} for "
                     + ", ".join(f"`{label}`" for label in flagged)
                     + ". Part of the ranking may reflect popularity rather than influence.")
    else:
        lines.append(f"Not flagged: every |rho| is below {schema.POPULARITY_FLAG_RHO}.")
    lines.append("")
    for check in checks:
        if check["rho"] is None:
            lines.append(f"- {check['label']}: not computable ({check['source']})")
        else:
            mark = "flagged" if abs(check["rho"]) >= schema.POPULARITY_FLAG_RHO else "not flagged"
            lines.append(f"- {check['label']}: rho = {check['rho']:.3f} ({mark}; {check['source']})")
    lines.append("")
    return lines


def _evidence_lines(inputs: dict) -> list[str]:
    evidence = inputs["evidence"]
    counts = {status: 0 for status in schema.STATUSES}
    for row in evidence:
        status = str(row.get("status", ""))
        if status in counts:
            counts[status] += 1
    denominator = sum(v for status, v in counts.items() if status != "not_applicable")
    lines = ["## Evidence status", "",
             f"{len(evidence)} evidence rows (one per load x scored rule). Denominators exclude "
             f"`not_applicable` rows and contain **{denominator}** rows.", "",
             "| status | rows | share of denominator |", "| --- | ---: | ---: |"]
    for status in schema.STATUSES:
        if status == "not_applicable":
            share = "excluded"
        elif denominator:
            share = f"{100.0 * counts[status] / denominator:.1f}%"
        else:
            share = "n/a"
        lines.append(f"| `{status}` | {counts[status]} | {share} |")
    lines.append("")

    examples: dict = {}
    for row in sorted(evidence, key=lambda r: (str(r.get("load_id", "")), str(r.get("rule_id", "")))):
        examples.setdefault((str(row.get("status", "")), str(row.get("reason", ""))), row)
    if examples:
        lines += ["### Example rows by status and reason code", ""]
        for status in schema.STATUSES:
            keys = sorted(k for k in examples if k[0] == status)
            if not keys:
                continue
            lines += [f"`{status}`", ""]
            for _, reason in keys:
                row = examples[(status, reason)]
                steps = str(row.get("evidence_steps", "")).strip() or "none"
                lines.append(
                    f"- reason `{reason}`: skill `{row.get('skill', '')}`, rule `{row.get('rule_id', '')}` "
                    f"({row.get('obligation', '')}), episode `{row.get('load_id', '')}`, window "
                    f"{row.get('window_start', '')}-{row.get('window_end', '')}, evidence steps {steps}"
                )
            lines.append("")
    lines += ["A load with no matching command is described as **no agreement observed**. It is never read "
              "as a failure of the skill, and unknowns are never mapped to failure.", ""]
    return lines


def _excluded_lines(inputs: dict) -> list[str]:
    loads = inputs["loads"]
    lines = ["## Excluded loads by reason", ""]
    if not loads:
        lines += ["Not computable: no `loads.jsonl` in this corpus.", ""]
        return lines
    reasons = {"maintenance": 0, "repeat": 0, "version_unknown": 0}
    kept = {"incomplete": 0, "overlap": 0}
    scorable = 0
    for row in loads:
        flags = set(row.get("flags") or [])
        excluded = False
        for reason in ("maintenance", "repeat"):
            if reason in flags:
                reasons[reason] += 1
                excluded = True
        if row.get("version_source") == "version_unknown":
            reasons["version_unknown"] += 1
            excluded = True
        if excluded:
            continue
        scorable += 1
        for flag in kept:
            if flag in flags:
                kept[flag] += 1
    lines += ["| reason | loads |", "| --- | ---: |"]
    for reason in sorted(reasons):
        lines.append(f"| `{reason}` | {reasons[reason]} |")
    lines += ["", f"{scorable} of {len(loads)} loads are scorable and enter the primary result.", ""]
    if kept["incomplete"] or kept["overlap"]:
        lines.append(f"Flagged but included in the primary result: `incomplete` {kept['incomplete']}, "
                     f"`overlap` {kept['overlap']}. The sensitivity run excludes both.")
    else:
        lines.append("No scorable load carries an `incomplete` or `overlap` flag, so the sensitivity run "
                     "and the primary result cover the same loads.")
    lines.append("")
    triggers = {"chosen": 0, "instructed": 0, "preloaded": 0}
    for row in loads:
        trigger = str(row.get("trigger", ""))
        if trigger in triggers:
            triggers[trigger] += 1
    lines += [f"Trigger mix over all loads: chosen {triggers['chosen']}, instructed "
              f"{triggers['instructed']}, preloaded {triggers['preloaded']}.", ""]
    return lines


def _supporting_lines(inputs: dict) -> list[str]:
    provenance, loads, potency = inputs["provenance"], inputs["loads"], inputs["potency"]
    lines = ["## Supporting numbers", ""]
    if not provenance:
        lines += ["Bloat statistic not computable: no `provenance.jsonl` in this corpus.", ""]
        return lines
    agent = sorted(str(row.get("skill", "")) for row in provenance if _truthy(row.get("agent_touched")))
    loaded = {str(row.get("skill", "")) for row in loads}
    supported = {str(row.get("skill", "")) for row in potency if _truthy(row.get("supported"))}
    if not agent:
        lines += ["No skill in this corpus is agent-touched, so the bloat statistic is empty.", ""]
        return lines
    never_loaded = [skill for skill in agent if skill not in loaded]
    touched_loaded = [skill for skill in agent if skill in loaded]
    loaded_unsupported = [skill for skill in touched_loaded if skill not in supported]
    lines.append(f"- Agent-touched skills never loaded: {len(never_loaded)} of {len(agent)} "
                 f"({100.0 * len(never_loaded) / len(agent):.0f}%).")
    share = f"{100.0 * len(loaded_unsupported) / len(touched_loaded):.0f}%" if touched_loaded else "n/a"
    lines.append(f"- Agent-touched skills loaded but never supported: {len(loaded_unsupported)} of "
                 f"{len(touched_loaded)} ({share}).")
    lines += ["", "These are supporting counts, not headline numbers.", ""]
    return lines


def _model_lines(inputs: dict) -> list[str]:
    evaluation = inputs["expect_eval"]
    lines = ["## Expectation model", ""]
    if not isinstance(evaluation, dict):
        lines += ["Not computable: `out/expect_eval.json` is missing, so lift is measured against base "
                  "rates and no hit-rate comparison is available.", ""]
        return lines
    beats = evaluation.get("beats_popularity", evaluation.get("model_beats_popularity"))
    if beats is True:
        lines.append("The expectation model beats the popularity-only baseline on the held-out windows.")
    elif beats is False:
        lines.append("The model does **not** beat the popularity-only baseline, so read lift as the amount "
                     "above base rate rather than as model-predicted surprise.")
    else:
        lines.append("`expect_eval.json` does not report the popularity comparison.")
    hits = []
    for key in sorted(evaluation, key=str):
        if "hit_rate" in str(key) and _f(evaluation[key]) is not None:
            hits.append(f"`{key}`={fmt(evaluation[key])}")
    if hits:
        lines += ["", "Reported hit rates: " + ", ".join(hits) + "."]
    lines.append("")
    return lines


def _appendix_lines(corpus_dir: Path, inputs: dict, program_map) -> list[str]:
    base = Path(corpus_dir).parent
    rules = inputs["rules"]
    lines = ["## Appendix: maps and inputs used", ""]
    rule_path = Path(corpus_dir) / "rules.jsonl"
    if rules:
        approved = sum(1 for row in rules if _truthy(row.get("approved")))
        sources: dict[str, int] = {}
        for row in rules:
            source = str(row.get("rule_source", ""))
            sources[source] = sources.get(source, 0) + 1
        mix = ", ".join(f"{name}={sources[name]}" for name in sorted(sources))
        versions = {str(row.get("version_id", "")) for row in rules}
        lines.append(f"- Rule map: `{_display(rule_path, base)}` - {len(rules)} rules over "
                     f"{len(versions)} skill versions, {approved} approved; rule sources: {mix}.")
    else:
        lines.append(f"- Rule map: `{_display(rule_path, base)}` missing, so every skill fell back to "
                     f"auto-extraction (the `auto` flag).")
    if program_map:
        lines.append(f"- Program map (public/local prior-knowledge proxy): `{_path_or_raw(program_map)}`.")
    else:
        lines.append("- Program map (public/local prior-knowledge proxy): not supplied to this stage; "
                     "unmapped programs default to local (design D6).")
    present = ", ".join(f"`{name}`" for name in inputs["present"]) or "none"
    lines.append(f"- Files present in `out/`: {present}.")
    manifest = Path(corpus_dir) / "manifest.json"
    if manifest.exists():
        lines.append(f"- Snapshot manifest: `{_display(manifest, base)}`.")
    lines.append("")
    return lines


def _path_or_raw(value) -> str:
    try:
        return Path(value).as_posix()
    except TypeError:
        return str(value)


# ---------------------------------------------------------------- summary
def summary_markdown(corpus_dir: Path, inputs: dict, program_map=None) -> str:
    lines = [f"# Skill potency report: `{inputs['corpus']}`", "",
             _inputs_line(corpus_dir, inputs), "",
             "Every number below describes **agreement with prescribed action** in the traces that were "
             "observed. The unit is a loaded episode x scored rule, not a whole procedure.", ""]
    lines += _headline_lines(inputs)
    lines += ["## Caveats and disclosures", "",
              "- **Endogeneity.** " + CAVEAT_ENDGENEITY,
              "- **Loaded episodes only.** " + DISCLOSURE_LOADED_ONLY,
              "- **Maps are subjective.** The rule map is reviewed and committed before any adherence "
              "number is computed; unaudited skills carry the `auto` flag.",
              ""]
    lines += _ranking_lines(inputs)
    lines += _popularity_lines(inputs)
    lines += _model_lines(inputs)
    lines += _evidence_lines(inputs)
    lines += _excluded_lines(inputs)
    lines += _supporting_lines(inputs)
    lines += ["## Natural experiments", ""] + _experiment_lines(inputs["experiments"])
    lines += _appendix_lines(corpus_dir, inputs, program_map)
    return "\n".join(lines).rstrip("\n") + "\n"


def write_summary(path: Path, text: str) -> None:
    """utf-8 with \\n on every platform (D17). io.py has no text writer."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


# ---------------------------------------------------------------- stage
def corpora(data_dir, corpus: str | None = None) -> list:
    data_dir = Path(data_dir)
    if corpus:
        return [data_dir / corpus]
    if not data_dir.is_dir():
        return []
    return sorted(
        path for path in data_dir.iterdir()
        if path.is_dir() and ((path / "sessions.jsonl").exists() or (path / "out" / "evidence.csv").exists())
    )


def write_report(corpus_dir: Path, program_map=None) -> Path:
    """Write the three report files for one corpus dir and return the summary path."""
    corpus_dir = Path(corpus_dir)
    out = corpus_dir / "out"
    inputs = load_inputs(corpus_dir)
    out.mkdir(parents=True, exist_ok=True)
    plot_potency(inputs["corpus"], inputs["potency"], out / "potency.png")
    plot_status(inputs["corpus"], inputs["evidence"], out / "status.png")
    path = out / "summary.md"
    write_summary(path, summary_markdown(corpus_dir, inputs, program_map))
    return path


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m potency.report",
        description="Analysis: charts and summary -> out/potency.png, status.png, summary.md.",
    )
    p.add_argument("--corpus", default=None, help="corpus (default: every corpus in the data dir)")
    p.add_argument("--data", default=None, help="data dir")
    p.add_argument("--program-map", default=None, help="public/local program map JSON (appendix only)")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    data_dir = Path(io.resolve_data_dir(args.data))
    if not data_dir.is_dir():
        print(f"report: data dir not found: {data_dir}", file=sys.stderr)
        return 2
    dirs = corpora(data_dir, args.corpus)
    if not dirs:
        print(f"report: no corpus directories under {data_dir}", file=sys.stderr)
        return 2
    status = 0
    for corpus_dir in dirs:
        if not (corpus_dir / "out" / "evidence.csv").exists():
            print(f"report: {corpus_dir.name}: missing out/evidence.csv", file=sys.stderr)
            status = 1
            continue
        write_report(corpus_dir, args.program_map)
        print(f"report: {corpus_dir.name}: wrote out/potency.png, out/status.png, out/summary.md")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
