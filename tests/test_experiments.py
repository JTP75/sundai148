"""D7 experiment tests: paired runs, edit-response, pre/post creation, trigger split, missing inputs."""
from pathlib import Path

import pytest

from potency import experiments, io, score
from tests.test_score import golden_data_dir


def run(tmp_path) -> dict:
    corpus = golden_data_dir(tmp_path) / "synth"
    return experiments.run_experiments(corpus)


def test_paired_runs_novel_skill_positive(tmp_path):
    paired = run(tmp_path)["paired_runs"]
    assert paired["computable"] is True
    novel = paired["skills"]["novel-skill"]
    assert novel["computable"] is True
    assert novel["n_pairs"] == 20
    assert novel["experimental_difference"] > 0.0
    assert novel["observational_lift"] > 0.0
    assert novel["endogeneity_gap"] == novel["observational_lift"] - novel["experimental_difference"]


def test_edit_response_added_command_positive(tmp_path):
    edit = run(tmp_path)["edit_response"]
    assert edit["computable"] is True
    row = next(r for r in edit["rows"] if r["skill"] == "mid-skill" and r["signature"] == "terminal: make")
    assert row["kind"] == "added"
    assert row["actor"] == "curator"
    assert row["n_pre"] > 0 and row["n_post"] > 0
    assert row["delta"] > 0.0
    assert row["relative_delta"] > 0.0


def test_pre_post_creation_on_keyed_tasks(tmp_path):
    pre_post = run(tmp_path)["pre_post"]
    assert pre_post["computable"] is True
    row = next(r for r in pre_post["rows"] if r["skill"] == "novel-skill")
    assert row["post_treat"] > row["pre_treat"]
    assert row["pre_treat"] == 0.0  # the novel command never ran before the skill existed
    # Every keyed task in the fixture eventually loads a skill, so there is no control task left.
    assert row["did"] is None
    assert "note" in pre_post
    skipped = {r["skill"] for r in pre_post["skipped"]}
    assert {"habit-skill", "mid-skill"} <= skipped  # created before the corpus starts


def test_pre_post_difference_in_differences():
    """Unit test of S1's contrast with a load-free control task, which the fixture lacks."""
    sessions = {
        "tp": {"session_id": "tp", "task_key": "task-t", "start_ts": 100.0, "split": "train"},
        "tq": {"session_id": "tq", "task_key": "task-t", "start_ts": 300.0, "split": "train"},
        "cp": {"session_id": "cp", "task_key": "task-c", "start_ts": 100.0, "split": "train"},
        "cq": {"session_id": "cq", "task_key": "task-c", "start_ts": 300.0, "split": "train"},
    }

    def steps(sid, target=None):
        rows = [{"step": i, "signature": "read_file", "kind": "tool"} for i in range(12)]
        if target:
            rows[2]["signature"] = target
        return rows

    inputs = score.Inputs(
        corpus="hand", corpus_dir=Path("."), sessions=sessions, session_rows=list(sessions.values()),
        loads={"L1": {"load_id": "L1", "skill": "s", "session_id": "tq", "step": 0, "ts": 300.0}},
        rules={}, provenance={"s": {"skill": "s", "created_ts": 200.0, "created_by": None,
                                    "agent_touched": False, "changes": []}},
        steps={"tp": steps("tp"), "tq": steps("tq", "terminal: gog tasks list"),
               "cp": steps("cp"), "cq": steps("cq")},
        evidence=[], expected={}, program_map={},
    )
    section = experiments._pre_post(inputs, {"s": {"terminal: gog tasks list"}})
    row = section["rows"][0]
    assert (row["pre_treat"], row["post_treat"]) == (0.0, 1.0)
    assert (row["pre_control"], row["post_control"]) == (0.0, 0.0)
    assert row["did"] == pytest.approx(1.0)
    assert section["by_provenance"][0]["mean_did"] == pytest.approx(1.0)


def test_trigger_split(tmp_path):
    split = run(tmp_path)["trigger_split"]
    assert split["computable"] is True
    triggers = {r["trigger"] for r in split["by_trigger"]}
    assert {"chosen", "preloaded"} <= triggers
    novel = {(r["trigger"], r["n_loads"]) for r in split["rows"] if r["skill"] == "novel-skill"}
    assert ("preloaded", 1) in novel and ("chosen", 105) in novel
    preloaded = next(r for r in split["rows"] if r["skill"] == "novel-skill" and r["trigger"] == "preloaded")
    assert preloaded["lift"] == 1.0


def test_missing_inputs_are_reported_not_raised(tmp_path):
    corpus = tmp_path / "bare"
    corpus.mkdir()
    payload = experiments.run_experiments(corpus)
    for section in ("pre_post", "edit_response", "paired_runs", "trigger_split"):
        assert payload[section]["computable"] is False
        assert "reason" in payload[section]


def test_experiments_are_deterministic(tmp_path):
    first = experiments.run_experiments(golden_data_dir(tmp_path / "a") / "synth")
    second = experiments.run_experiments(golden_data_dir(tmp_path / "b") / "synth")
    assert io.dumps(first) == io.dumps(second)


def test_experiments_cli(tmp_path):
    data = golden_data_dir(tmp_path)
    assert experiments.main(["--data", str(data), "--corpus", "synth"]) == 0
    payload = io.read_json(data / "synth" / "out" / "experiments.json")
    assert payload["paired_runs"]["computable"] is True
