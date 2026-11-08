"""Scoring tests: golden lift/CI, ranking flags, specificity weights, strata, placebo, sensitivity."""
import subprocess
import sys
from pathlib import Path

import pytest

from potency import io, schema, score

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / "tests" / "fixtures"
SYNTH = FIX / "synthetic"
PROGRAM_MAP = io.read_json(SYNTH / "program_map.json")
TABLES = ("sessions", "steps", "loads", "skill_versions", "rules", "provenance")


def golden_data_dir(tmp_path) -> Path:
    """Copy the frozen synth tables plus golden evidence/expected into <tmp>/data/synth."""
    data = tmp_path / "data"
    corpus = data / "synth"
    (corpus / "out").mkdir(parents=True)
    for table in TABLES:
        (corpus / f"{table}.jsonl").write_bytes((SYNTH / "synth" / f"{table}.jsonl").read_bytes())
    for name in ("evidence.csv", "expected.csv"):
        (corpus / "out" / name).write_bytes((SYNTH / "golden" / name).read_bytes())
    return data


def scored(tmp_path) -> tuple[Path, list[dict], list[dict], dict]:
    data = golden_data_dir(tmp_path)
    corpus = data / "synth"
    score.run_corpus(corpus, PROGRAM_MAP)
    rows = io.read_csv(corpus / "out" / "potency.csv")
    strata = io.read_csv(corpus / "out" / "strata.csv")
    detail = io.read_json(corpus / "out" / "experiments.json")
    return corpus, rows, strata, detail


def row_of(rows, skill):
    return next(r for r in rows if r["skill"] == skill)


def num(value):
    return None if value == "" else float(value)


# ------------------------------------------------------------------ golden effects (5.1)
def test_golden_known_effects(tmp_path):
    _, rows, _, _ = scored(tmp_path)
    known = io.read_json(SYNTH / "golden" / "potency_expect.json")["expect"]

    habit = row_of(rows, "habit-skill")
    assert abs(num(habit["lift"])) <= known["habit-skill"]["abs_max"]
    assert num(habit["ci_low"]) <= 0.0 <= num(habit["ci_high"])
    assert habit["label"] == "inconclusive"

    for skill in ("novel-skill", "mid-skill"):
        row = row_of(rows, skill)
        assert num(row["lift"]) >= known[skill]["min"]
        assert num(row["ci_low"]) > 0.0
        assert row["label"] == "positive"


def test_ranking_and_support_flags(tmp_path):
    _, rows, _, detail = scored(tmp_path)
    for row in rows:
        n_loads, n_clusters = int(row["n_loads"]), int(row["n_clusters"])
        assert (row["ranked"] == "true") == (n_loads >= schema.MIN_RANKED_LOADS and row["generic_only"] == "false")
        assert (row["supported"] == "true") == (
            n_loads >= schema.MIN_SUPPORTED_LOADS
            and n_clusters >= schema.MIN_SUPPORTED_CLUSTERS
            and row["generic_only"] == "false"
        )
    assert row_of(rows, "habit-skill")["supported"] == "true"
    assert row_of(rows, "cond-skill")["ranked"] == "false"  # 1 load: insufficient data
    assert detail["ranking"]["n_ranked"] == 3
    assert detail["ranking"]["n_supported"] == 3


def test_ubiquitous_command_dropped(tmp_path):
    """Spec scenario: a habitual command above the ceiling leaves only the specific one."""
    _, rows, _, _ = scored(tmp_path)
    novel = row_of(rows, "novel-skill")
    assert novel["set_size"] == "1"
    assert novel["generic_only"] == "false"
    # `terminal: npm test` is above the ceiling, so alt-skill has no weighted set left.
    alt = row_of(rows, "alt-skill")
    assert alt["set_size"] == "0" and alt["generic_only"] == "true" and alt["ranked"] == "false"


def test_avoid_reported_separately(tmp_path):
    _, rows, _, _ = scored(tmp_path)
    avoid = row_of(rows, "avoid-skill")
    assert int(avoid["avoid_matches"]) == 1
    assert avoid["lift"] == "" and avoid["set_size"] == "0"
    assert row_of(rows, "habit-skill")["avoid_matches"] == "0"


def test_placebo_below_observed_for_novel_skill(tmp_path):
    _, rows, _, _ = scored(tmp_path)
    novel = row_of(rows, "novel-skill")
    assert num(novel["placebo_lift"]) is not None
    assert 0.0 < num(novel["placebo_lift"]) < num(novel["mean_a"])


def test_follow_rate_is_raw_follow_through(tmp_path):
    _, rows, _, _ = scored(tmp_path)
    habit = row_of(rows, "habit-skill")
    assert num(habit["follow_rate"]) == pytest.approx(num(habit["mean_a"]))
    assert num(habit["mean_a"]) > 0.1  # the habit command is often followed, yet lift ~ 0


# ------------------------------------------------------------------ strata (D6)
def test_strata_columns_and_cells(tmp_path):
    _, _, strata, _ = scored(tmp_path)
    assert list(strata[0]) == schema.OUTPUT_COLUMNS["strata.csv"]
    cells = {(r["familiarity"], r["prior_knowledge"]): r for r in strata}
    novel_local = cells[("novel", "local")]
    assert int(novel_local["n_loads"]) == io.read_json(SYNTH / "golden" / "potency_expect.json")["n_loads"]["novel-skill"]
    assert num(novel_local["ci_low"]) <= num(novel_local["lift"]) <= num(novel_local["ci_high"])
    assert novel_local["pooled"] == "false"


def test_thin_strata_pool(tmp_path):
    """A cell with fewer than 10 loads pools every cell into novel+local vs rest."""
    data = tiny_data_dir(tmp_path)  # one load in a novel/local cell, one in habitual/public
    corpus = data / "tiny"
    score.run_corpus(corpus, PROGRAM_MAP)
    strata = io.read_csv(corpus / "out" / "strata.csv")
    assert strata and all(r["pooled"] == "true" for r in strata)
    assert {r["familiarity"] for r in strata} <= {"novel+local", "rest"}


# ------------------------------------------------------------------ hand-built corpus
def _step(sid, i, sig, ts, kind=None, batch=None):
    return {
        "corpus": "tiny", "session_id": sid, "step": i, "source_offset": i, "call_id": f"{sid}-c{i}",
        "batch_id": batch or f"{sid}-b{i}", "ts": ts, "kind": kind or ("shell" if sig.startswith("terminal: ") else "tool"),
        "signature": sig, "status": "ok", "attribution_skill": None,
    }


def _load(sid, i, skill, ts, flags=()):
    return {
        "corpus": "tiny", "session_id": sid, "load_id": schema.episode_id("tiny", sid, i), "skill": skill,
        "step": i, "ts": ts, "trigger": "chosen", "version_id": "v1", "version_source": "injected",
        "flags": sorted(flags), "cluster_key": f"repo-{sid}", "split": "train",
    }


def _rule(skill, rid, observable, obligation="required"):
    return {
        "corpus": "tiny", "skill": skill, "version_id": "v1", "rule_id": rid, "obligation": obligation,
        "applicability": [], "observable": list(observable), "alternatives": [], "location": None,
        "rule_source": "auto", "approved": False, "in_core": None,
    }


def tiny_data_dir(tmp_path) -> Path:
    """`terminal: ls` in every no-load window (above the ceiling), `terminal: gog tasks list` never."""
    data = tmp_path / "tiny_data"
    corpus = data / "tiny"
    (corpus / "out").mkdir(parents=True)
    filler = ["terminal: ls", "terminal: cat", "read_file", "terminal: grep"]
    sessions, steps, loads, evidence, expected = [], [], [], [], []

    def session(sid, start, split="train"):
        return {"corpus": "tiny", "session_id": sid, "start_ts": start, "source": "cli", "task_key": None,
                "cluster_key": f"repo-{sid}", "model": None, "harness_version": None, "pair_id": None,
                "pair_arm": None, "split": split}

    sessions.append(session("n0", 0.0))
    for i in range(40):
        steps.append(_step("n0", i, filler[i % 4], 30.0 * i))

    for sid, start, flags, skill in (("l0", 5000.0, (), "tiny-skill"),
                                     ("l1", 7000.0, ("incomplete",), "tiny-skill"),
                                     ("l2", 9000.0, (), "gen-skill")):
        sessions.append(session(sid, start))
        rows = [_step(sid, 0, "read_file", start), _step(sid, 1, "read_file", start + 30),
                _step(sid, 2, f"load: {skill}", start + 60, kind="load"),
                _step(sid, 3, "terminal: ls", start + 90),
                _step(sid, 4, "terminal: gog tasks list", start + 120)]
        rows += [_step(sid, i, "read_file", start + 30 * i) for i in range(5, 18)]
        steps.extend(rows)
        ld = _load(sid, 2, skill, start + 60, flags)
        loads.append(ld)
        evidence.append({"corpus": "tiny", "load_id": ld["load_id"], "session_id": sid,
                         "cluster_key": ld["cluster_key"], "skill": skill, "version_id": "v1",
                         "rule_id": "r-ls", "obligation": "required", "window_start": 3, "window_end": 12,
                         "status": "supported_agreement", "reason": "matched", "evidence_steps": "3"})
        expected.append({"corpus": "tiny", "load_id": ld["load_id"], "rule_id": "r-ls", "p_hat": 0.9})
        if skill == "tiny-skill":
            evidence.append({"corpus": "tiny", "load_id": ld["load_id"], "session_id": sid,
                             "cluster_key": ld["cluster_key"], "skill": skill, "version_id": "v1",
                             "rule_id": "r-gog", "obligation": "required", "window_start": 3, "window_end": 12,
                             "status": "supported_agreement", "reason": "matched", "evidence_steps": "4"})
            expected.append({"corpus": "tiny", "load_id": ld["load_id"], "rule_id": "r-gog", "p_hat": 0.0})

    io.write_table(corpus, "sessions", sessions)
    io.write_table(corpus, "steps", steps)
    io.write_table(corpus, "loads", loads)
    io.write_table(corpus, "skill_versions", [
        {"corpus": "tiny", "skill": s, "version_id": "v1", "version_source": "injected",
         "valid_from_ts": 0.0, "content_sha256": None} for s in ("tiny-skill", "gen-skill")])
    io.write_table(corpus, "rules", [
        _rule("tiny-skill", "r-ls", ["terminal: ls"]), _rule("tiny-skill", "r-gog", ["terminal: gog tasks list"]),
        _rule("gen-skill", "r-ls", ["terminal: ls"])])
    io.write_table(corpus, "provenance", [
        {"corpus": "tiny", "skill": s, "created_ts": None, "created_by": None, "agent_touched": False,
         "changes": []} for s in ("tiny-skill", "gen-skill")])
    io.write_output_csv(corpus / "out" / "evidence.csv", evidence)
    io.write_output_csv(corpus / "out" / "expected.csv", expected)
    return data


def test_specificity_drops_ubiquitous_command(tmp_path):
    data = tiny_data_dir(tmp_path)
    corpus = data / "tiny"
    score.run_corpus(corpus, PROGRAM_MAP)
    rows = io.read_csv(corpus / "out" / "potency.csv")
    tiny = row_of(rows, "tiny-skill")
    assert tiny["set_size"] == "1"  # `terminal: ls` removed by the ceiling
    assert num(tiny["lift"]) == pytest.approx(1.0)
    gen = row_of(rows, "gen-skill")
    assert gen["set_size"] == "0" and gen["generic_only"] == "true"


def test_sensitivity_excludes_incomplete_windows(tmp_path):
    data = tiny_data_dir(tmp_path)
    corpus = data / "tiny"
    score.run_corpus(corpus, PROGRAM_MAP)
    detail = io.read_json(corpus / "out" / "experiments.json")
    assert detail["sensitivity"]["excluded_flags"] == ["incomplete", "overlap"]
    tiny = next(r for r in detail["sensitivity"]["rows"] if r["skill"] == "tiny-skill")
    assert tiny["n_loads"] == 2 and tiny["n_loads_stable"] == 1


# ------------------------------------------------------------------ outputs, determinism, CLI
def test_potency_columns(tmp_path):
    corpus, _, _, _ = scored(tmp_path)
    header = (corpus / "out" / "potency.csv").read_text(encoding="utf-8").splitlines()[0]
    assert header.split(",") == schema.OUTPUT_COLUMNS["potency.csv"]


def test_popularity_and_bloat_reported(tmp_path):
    _, _, _, detail = scored(tmp_path)
    popularity = detail["popularity"]
    assert popularity["n_skills"] == 3
    assert popularity["threshold"] == schema.POPULARITY_FLAG_RHO
    assert popularity["flagged"] is (abs(popularity["load_count_rho"]) >= schema.POPULARITY_FLAG_RHO
                                     or abs(popularity["mean_base_rate_rho"]) >= schema.POPULARITY_FLAG_RHO)
    bloat = detail["bloat"]
    assert bloat["computable"] is True
    assert bloat["never_loaded"] == ["never-loaded-skill"]
    assert bloat["share_never_loaded"] == pytest.approx(0.25)
    assert "cond-skill" in bloat["loaded_unsupported"]


def test_outputs_are_deterministic(tmp_path):
    first = golden_data_dir(tmp_path / "a") / "synth"
    second = golden_data_dir(tmp_path / "b") / "synth"
    score.run_corpus(first, PROGRAM_MAP)
    score.run_corpus(second, PROGRAM_MAP)
    for name in ("potency.csv", "strata.csv", "experiments.json"):
        assert (first / "out" / name).read_bytes() == (second / "out" / name).read_bytes(), name


def test_cli_writes_outputs(tmp_path):
    data = golden_data_dir(tmp_path)
    proc = subprocess.run(
        [sys.executable, "-m", "potency.score", "--data", str(data), "--corpus", "synth",
         "--program-map", str(SYNTH / "program_map.json")],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert "synth" in proc.stdout
    for name in ("potency.csv", "strata.csv", "experiments.json"):
        assert (data / "synth" / "out" / name).exists()


def test_missing_evidence_is_an_error(tmp_path):
    corpus = tmp_path / "empty"
    corpus.mkdir()
    with pytest.raises(FileNotFoundError, match="evidence.csv"):
        score.read_inputs(corpus)


def test_spearman_ties():
    assert score.spearman([1, 2, 3], [1, 2, 3]) == pytest.approx(1.0)
    assert score.spearman([1, 2, 3], [3, 2, 1]) == pytest.approx(-1.0)
    assert score.spearman([1, 1, 1], [1, 2, 3]) is None
