"""Report stage (task 6.1): files produced, required wording, forbidden wording, determinism.

The inputs are stand-ins written with the frozen ``schema.OUTPUT_COLUMNS``, because W3 (evidence, expect)
and W4 (score) are stubs on this branch. Nothing here touches ``tests/fixtures/``.
"""
from __future__ import annotations

from pathlib import Path

from potency import io, report, schema

CORPUS = "synth"
CLUSTERS = {"s0": "repo-0", "s1": "repo-1", "s2": "repo-2", "s3": "repo-3", "s4": "repo-4"}

REQUIRED_PHRASES = [
    "agreement with prescribed action",
    "upper bound on skill influence",
    "endogenous",
    "loaded episodes only",
    "no agreement observed",
    "median lift on novel+local",
    "agent-touched",
    "no-agent-trace",
    "popularity check",
    "not computable",
    "Rule map",
    "Program map",
]
FORBIDDEN_PHRASES = ["skill quality", "ignored", "inert", "prune"]

EVIDENCE_CYCLE = (
    ("supported_agreement", "matched"),
    ("supported_agreement", "matched"),
    ("no_observed_agreement", "no_match_complete_window"),
    ("insufficient_evidence", "incomplete_window"),
    ("supported_agreement", "matched_alternative"),
    ("insufficient_evidence", "same_batch_only"),
    ("supported_agreement", "matched"),
    ("not_applicable", "applicability_false"),
    ("insufficient_evidence", "applicability_unknown"),
)
RULE_OF = {
    "novel-skill": ("novel-1", "required"),
    "habit-skill": ("habit-1", "required"),
    "mid-skill": ("mid-1", "required"),
    "alt-skill": ("alt-1", "required"),
    "cond-skill": ("cond-1", "conditional"),
}


# ---------------------------------------------------------------- stand-in inputs
def _sessions() -> list:
    return [
        {
            "corpus": CORPUS, "session_id": f"s{i}", "start_ts": 1767225600.0 + 3600.0 * i,
            "source": "cli" if i % 2 else "cron", "task_key": None, "cluster_key": CLUSTERS[f"s{i}"],
            "model": "standin-model", "harness_version": "0.0", "pair_id": None, "pair_arm": None,
            "split": "train" if i < 3 else "test",
        }
        for i in range(5)
    ]


def _steps() -> list:
    return [
        {
            "corpus": CORPUS, "session_id": f"s{i}", "step": j, "source_offset": 2 * j,
            "call_id": f"s{i}-c{j}", "batch_id": f"s{i}-b{j}", "ts": 1767225600.0 + 3600.0 * i + 30.0 * j,
            "kind": "shell", "signature": "terminal: git status", "status": "ok", "attribution_skill": None,
        }
        for i in range(5) for j in range(3)
    ]


def _loads() -> list:
    rows = []
    next_step = {}

    def add(skill, session, flags=(), version_source="injected", version_id=None):
        step = next_step.get(session, 2)
        next_step[session] = step + 1
        rows.append({
            "corpus": CORPUS, "session_id": session, "load_id": schema.episode_id(CORPUS, session, step),
            "skill": skill, "step": step, "ts": 1767225600.0 + 3600.0 * int(session[1:]) + 30.0 * step,
            "trigger": "instructed" if step % 3 == 0 else ("preloaded" if step % 3 == 1 else "chosen"),
            "version_id": version_id, "version_source": version_source, "flags": sorted(flags),
            "cluster_key": CLUSTERS[session], "split": "train" if int(session[1:]) < 3 else "test",
        })

    for session in ("s0", "s1", "s2", "s3", "s4", "s0"):
        add("novel-skill", session, version_id="novel-v1")
    for session in ("s0", "s1", "s2", "s0", "s1", "s2", "s0", "s1"):
        add("habit-skill", session, version_id="habit-v1")
    for session in ("s1", "s2", "s3", "s4", "s0"):
        add("mid-skill", session, version_id="mid-v1")
    add("alt-skill", "s3", version_id="alt-v1")
    add("cond-skill", "s4", version_id="cond-v1")
    add("novel-skill", "s2", flags=["maintenance"], version_id="novel-v1")
    add("mid-skill", "s1", flags=["maintenance"], version_id="mid-v1")
    add("habit-skill", "s0", flags=["repeat"], version_id="habit-v1")
    add("core-skill", "s3", version_source="version_unknown")
    return rows


def _rules() -> list:
    def rule(skill, rule_id, obligation, observable, rule_source="auto", approved=False, applicability=()):
        return {
            "corpus": CORPUS, "skill": skill, "version_id": f"{skill.split('-')[0]}-v1", "rule_id": rule_id,
            "obligation": obligation, "applicability": list(applicability), "observable": list(observable),
            "alternatives": [], "location": None, "rule_source": rule_source, "approved": approved,
            "in_core": None,
        }

    return [
        rule("novel-skill", "novel-1", "required", ["terminal: gog tasks list"]),
        rule("habit-skill", "habit-1", "required", ["terminal: git commit"]),
        rule("mid-skill", "mid-1", "required", ["terminal: docker compose up"]),
        rule("cond-skill", "cond-1", "conditional", ["terminal: git push"],
             rule_source="approved", approved=True, applicability=["terminal: git merge"]),
    ]


def _provenance() -> list:
    return [
        {"corpus": CORPUS, "skill": "novel-skill", "created_ts": 1767225600.0 - 86400.0, "created_by": None,
         "agent_touched": False, "changes": []},
        {"corpus": CORPUS, "skill": "habit-skill", "created_ts": None, "created_by": "agent",
         "agent_touched": True, "changes": []},
        {"corpus": CORPUS, "skill": "mid-skill", "created_ts": None, "created_by": "learn",
         "agent_touched": True, "changes": [{"ts": 1769000000.0, "actor": "curator", "action": "patch",
                                             "added": ["terminal: make"], "removed": []}]},
        {"corpus": CORPUS, "skill": "never-loaded-skill", "created_ts": None, "created_by": "agent",
         "agent_touched": True, "changes": []},
    ]


def _evidence(loads: list) -> list:
    rows = []
    index = 0
    for load in loads:
        if set(load["flags"]) & {"maintenance", "repeat"} or load["version_source"] == "version_unknown":
            continue
        rule_id, obligation = RULE_OF[load["skill"]]
        status, reason = EVIDENCE_CYCLE[index % len(EVIDENCE_CYCLE)]
        index += 1
        steps = [load["step"] + 2] if status == "supported_agreement" else []
        rows.append({
            "corpus": CORPUS, "load_id": load["load_id"], "session_id": load["session_id"],
            "cluster_key": load["cluster_key"], "skill": load["skill"], "version_id": load["version_id"],
            "rule_id": rule_id, "obligation": obligation, "window_start": load["step"] + 1,
            "window_end": load["step"] + schema.WINDOW_N, "status": status, "reason": reason,
            "evidence_steps": steps,
        })
    return rows


def _potency_row(skill, n_loads, n_clusters, lift_shrunk, ci_low, ci_high, provenance, *,
                 supported, ranked=True, label="positive", lift=None, generic_only=False, auto=False):
    return {
        "corpus": CORPUS, "skill": skill, "n_loads": n_loads, "n_clusters": n_clusters, "set_size": 1,
        "follow_rate": 0.5, "mean_a": 0.6, "mean_a_hat": 0.6 - (lift_shrunk if lift is None else lift),
        "lift": lift_shrunk if lift is None else lift, "lift_shrunk": lift_shrunk, "ci_low": ci_low,
        "ci_high": ci_high, "placebo_lift": 0.01, "avoid_matches": 0, "label": label,
        "supported": supported, "ranked": ranked, "generic_only": generic_only, "auto": auto,
        "provenance_group": provenance,
    }


def _potency() -> list:
    return [
        _potency_row("novel-skill", 6, 5, 0.72, 0.40, 0.90, "no-agent-trace", supported=True),
        _potency_row("habit-skill", 8, 3, 0.03, -0.10, 0.15, "agent-touched", supported=True,
                     label="inconclusive"),
        _potency_row("mid-skill", 5, 4, 0.28, -0.02, 0.55, "agent-touched", supported=True,
                     label="inconclusive"),
        _potency_row("alt-skill", 1, 1, 0.54, None, None, "no-agent-trace", supported=False, ranked=False,
                     label="inconclusive"),
    ]


def _strata(pooled: bool) -> list:
    rows = [
        {"corpus": CORPUS, "familiarity": "novel", "prior_knowledge": "local", "n_loads": 22, "lift": 0.62,
         "ci_low": 0.35, "ci_high": 0.88, "pooled": False},
        {"corpus": CORPUS, "familiarity": "occasional", "prior_knowledge": "public", "n_loads": 40,
         "lift": 0.11, "ci_low": 0.02, "ci_high": 0.20, "pooled": False},
        {"corpus": CORPUS, "familiarity": "habitual", "prior_knowledge": "public", "n_loads": 60,
         "lift": 0.04, "ci_low": -0.01, "ci_high": 0.09, "pooled": False},
    ]
    if pooled:
        rows.append({"corpus": CORPUS, "familiarity": "novel", "prior_knowledge": "local", "n_loads": 34,
                     "lift": 0.58, "ci_low": 0.30, "ci_high": 0.86, "pooled": True})
    return rows


EXPERIMENTS = {
    "corpus": CORPUS,
    "pre_post_creation": {"computable": False, "reason": "no task key in this corpus"},
    "edit_response": {"computable": True,
                      "result": {"mid-skill": {"added": "terminal: make", "pre": 0.22, "post": 0.43}}},
    "paired_runs": {"computable": False, "reason": "no paired with/without-skill runs"},
    "trigger_split": {"instructed": {"n_loads": 5, "lift": 0.40},
                      "chosen": {"n_loads": 9, "lift": 0.20},
                      "preloaded": {"n_loads": 2, "lift": 0.05}},
    "popularity_check": {"spearman_load_count": 0.62, "spearman_base_rate": None, "flagged": True},
}


def make_standin_data(root: Path, *, pooled_stratum: bool = True, corpus: str = CORPUS) -> Path:
    """Write a valid data dir with stand-in outputs. Returns the data dir."""
    corpus_dir = Path(root) / "data" / corpus
    io.write_table(corpus_dir, "sessions", _sessions())
    io.write_table(corpus_dir, "steps", _steps())
    loads = _loads()
    io.write_table(corpus_dir, "loads", loads)
    io.write_table(corpus_dir, "rules", _rules())
    io.write_table(corpus_dir, "provenance", _provenance())
    out = corpus_dir / "out"
    io.write_output_csv(out / "evidence.csv", _evidence(loads))
    io.write_output_csv(out / "expected.csv", [
        {"corpus": CORPUS, "load_id": row["load_id"], "rule_id": row["rule_id"], "p_hat": 0.2}
        for row in _evidence(loads)[:4]
    ])
    io.write_output_csv(out / "potency.csv", _potency())
    io.write_output_csv(out / "strata.csv", _strata(pooled_stratum))
    io.write_json(out / "experiments.json", EXPERIMENTS)
    io.write_json(out / "expect_eval.json", {
        "corpus": CORPUS, "beats_popularity": True, "hit_rate_at_1": 0.5, "popularity_hit_rate_at_1": 0.3,
    })
    return Path(root) / "data"


def _summary(data: Path, corpus: str = CORPUS) -> str:
    return (data / corpus / "out" / "summary.md").read_text(encoding="utf-8")


# ---------------------------------------------------------------- tests
def test_report_writes_the_three_outputs(tmp_path):
    data = make_standin_data(tmp_path)
    assert report.main(["--data", str(data), "--corpus", CORPUS]) == 0
    out = data / CORPUS / "out"
    for name in ("potency.png", "status.png", "summary.md"):
        assert (out / name).is_file(), name
    assert (out / "potency.png").read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    assert (out / "status.png").read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_summary_has_required_phrases(tmp_path):
    data = make_standin_data(tmp_path)
    report.main(["--data", str(data)])
    text = _summary(data).lower()
    for phrase in REQUIRED_PHRASES:
        assert phrase.lower() in text, phrase


def test_summary_avoids_forbidden_wording(tmp_path):
    data = make_standin_data(tmp_path)
    report.main(["--data", str(data)])
    text = _summary(data).lower()
    for phrase in FORBIDDEN_PHRASES:
        assert phrase not in text, phrase


def test_headline_numbers(tmp_path):
    data = make_standin_data(tmp_path)
    report.main(["--data", str(data), "--corpus", CORPUS])
    text = _summary(data)
    assert "**0.580**" in text, "headline 1 prefers the pooled novel+local cell"
    assert "**0.126** vs **0.720**" in text, "headline 2 is load-weighted per provenance group"
    assert "**2 of 3**" in text, "headline 3 counts ranked skills with ci_low <= 0"


def test_headline_prefers_pooled_cell_only_when_present(tmp_path):
    data = make_standin_data(tmp_path)
    io.write_output_csv(data / CORPUS / "out" / "strata.csv", _strata(False))
    report.main(["--data", str(data), "--corpus", CORPUS])
    assert "**0.620**" in _summary(data)


def test_evidence_examples_cover_every_status_and_reason(tmp_path):
    data = make_standin_data(tmp_path)
    report.main(["--data", str(data), "--corpus", CORPUS])
    text = _summary(data)
    for status, reasons in schema.REASONS.items():
        assert f"`{status}`" in text
        for reason in reasons:
            if status == "supported_agreement" or status == "no_observed_agreement":
                if reason in ("matched", "matched_alternative", "no_match_complete_window"):
                    assert f"reason `{reason}`" in text, reason
    for reason in ("incomplete_window", "same_batch_only", "applicability_unknown", "applicability_false"):
        assert f"reason `{reason}`" in text, reason


def test_excluded_loads_and_insufficient_data(tmp_path):
    data = make_standin_data(tmp_path)
    report.main(["--data", str(data), "--corpus", CORPUS])
    text = _summary(data)
    assert "| `maintenance` | 2 |" in text
    assert "| `repeat` | 1 |" in text
    assert "| `version_unknown` | 1 |" in text
    assert "Insufficient data" in text and "`cond-skill`: 1 scorable load" in text


def test_experiments_report_not_computable(tmp_path):
    data = make_standin_data(tmp_path)
    report.main(["--data", str(data), "--corpus", CORPUS])
    text = _summary(data)
    assert "Not computable: no task key in this corpus." in text
    assert "Not computable: no paired with/without-skill runs." in text
    assert "`mid-skill`: added=terminal: make" in text


def test_popularity_flag_and_appendix(tmp_path):
    data = make_standin_data(tmp_path)
    map_path = tmp_path / "program_map.json"
    map_path.write_text("{}\n", encoding="utf-8")
    report.main(["--data", str(data), "--corpus", CORPUS, "--program-map", str(map_path)])
    text = _summary(data)
    assert "**Flagged**" in text and "0.620" in text
    assert "Rule map: `" in text and "4 rules over" in text and "1 approved" in text
    assert "Program map (public/local prior-knowledge proxy): `" in text


def test_summary_is_deterministic(tmp_path):
    data = make_standin_data(tmp_path)
    report.main(["--data", str(data), "--corpus", CORPUS])
    out = data / CORPUS / "out"
    inputs = {p.name: p.read_bytes() for p in sorted(out.glob("*")) if p.suffix in (".csv", ".json")}
    first = {name: (out / name).read_bytes() for name in ("summary.md", "potency.png", "status.png")}
    report.main(["--data", str(data), "--corpus", CORPUS])
    for name, before in first.items():
        assert (out / name).read_bytes() == before, name
    for name, before in inputs.items():
        assert (out / name).read_bytes() == before, f"report rewrote its input {name}"


def test_no_ranked_rows_still_lists_insufficient_data(tmp_path):
    data = make_standin_data(tmp_path)
    rows = _potency()
    for row in rows:
        row["ranked"] = False
    io.write_output_csv(data / CORPUS / "out" / "potency.csv", rows)
    assert report.main(["--data", str(data), "--corpus", CORPUS]) == 0
    text = _summary(data)
    assert "No skill has enough scorable loads to be ranked" in text
    assert "### Insufficient data" in text


def test_evidence_only_fallback_keeps_the_demo(tmp_path):
    """D18: without potency.csv the status chart and the evidence section still stand."""
    data = make_standin_data(tmp_path)
    out = data / CORPUS / "out"
    for name in ("potency.csv", "strata.csv", "expected.csv", "experiments.json", "expect_eval.json"):
        (out / name).unlink()
    assert report.main(["--data", str(data), "--corpus", CORPUS]) == 0
    text = _summary(data)
    assert (out / "status.png").is_file() and (out / "potency.png").is_file()
    assert "Not computable: `out/potency.csv` is missing or empty" in text
    assert "no evidence rows" not in text


def test_reports_every_corpus_by_default(tmp_path):
    data = make_standin_data(tmp_path)
    other = data / "other"
    io.write_output_csv(other / "out" / "evidence.csv", _evidence(_loads())[:3])
    assert report.main(["--data", str(data)]) == 0
    assert (data / CORPUS / "out" / "summary.md").is_file()
    assert (other / "out" / "summary.md").is_file()


def test_missing_evidence_is_an_error(tmp_path):
    data = make_standin_data(tmp_path)
    (data / CORPUS / "out" / "evidence.csv").unlink()
    assert report.main(["--data", str(data), "--corpus", CORPUS]) == 1
