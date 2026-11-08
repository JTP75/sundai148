"""Tests for the D3 expectation model: accuracy vs golden, eval contract, determinism."""
import shutil
from pathlib import Path

import pytest

from potency import evidence, expect, io, schema

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures" / "synthetic"
SYN = FIXTURES / "synth"
GOLDEN = FIXTURES / "golden"

NOVEL_COMMAND = "terminal: gog tasks list"


@pytest.fixture(scope="module")
def fitted():
    return expect.fit_and_predict(SYN)


def _write_files(directory: Path, rows, block) -> None:
    io.write_output_csv(directory / "expected.csv", rows)
    io.write_json(directory / "expect_eval.json", {block["corpus"]: block})


def test_accuracy_against_golden(fitted):
    rows, _ = fitted
    gold = io.read_csv(GOLDEN / "expected.csv")
    assert {(r["load_id"], r["rule_id"]) for r in rows} == {
        (r["load_id"], r["rule_id"]) for r in gold
    }
    by_key = {(r["load_id"], r["rule_id"]): float(r["p_hat"]) for r in gold}
    diffs = [abs(r["p_hat"] - by_key[(r["load_id"], r["rule_id"])]) for r in rows]
    assert sum(diffs) / len(diffs) < 0.08


def test_rows_sorted_one_per_evidence_row(fitted):
    rows, _ = fitted
    keys = [(r["load_id"], r["rule_id"]) for r in rows]
    assert keys == sorted(keys)
    ev = evidence.compute_evidence(SYN)
    assert keys == [(r["load_id"], r["rule_id"]) for r in ev]
    assert set(rows[0]) == set(schema.OUTPUT_COLUMNS["expected.csv"])


def test_novel_command_stays_near_zero(fitted):
    rows, _ = fitted
    loads = io.read_table(SYN, "loads")
    novel_ids = {ld["load_id"] for ld in loads if ld["skill"] == "novel-skill"}
    novel = [r for r in rows if r["load_id"] in novel_ids and r["rule_id"] == "novel-1"]
    assert novel
    assert max(r["p_hat"] for r in novel) < 0.05


def test_eval_block_shape(fitted):
    _, block = fitted
    assert block["corpus"] == "synth"
    assert block["window_n"] == schema.WINDOW_N
    assert block["context_k"] == schema.CONTEXT_K
    assert block["train_sessions"] > 0 and block["test_sessions"] > 0
    assert block["train_windows"] > 0 and block["test_windows"] > 0
    assert block["vocabulary"] > 0
    assert block["targets"]["vocabulary"] == block["vocabulary"]

    window = block["window"]
    assert window["rows"] > 0 and window["sessions"] > 0
    for arm in ("model", "popularity_baseline"):
        assert 0.0 <= window[arm]["auc"] <= 1.0
        assert 0.0 <= window[arm]["brier"] <= 1.0
    calibration = window["calibration"]
    assert len(calibration) == 10
    for b in calibration:
        assert {"bin", "lower", "upper", "count", "predicted", "observed"} <= set(b)
    assert sum(b["count"] for b in calibration) == window["rows"]

    nxt = block["next_command"]
    assert nxt["steps"] > 0 and nxt["sessions"] > 0
    assert 0.0 <= nxt["oov_share"] <= 1.0
    for arm in ("model", "popularity_baseline"):
        assert set(nxt[arm]) == {"1", "5", "10"}
        rates = nxt[arm]
        assert 0.0 <= rates["1"] <= rates["5"] <= rates["10"] <= 1.0
    assert nxt["by_decile"], "frequency deciles must be reported"
    assert sum(d["steps"] for d in nxt["by_decile"]) == nxt["steps"] - nxt["oov_steps"]
    for decile in nxt["by_decile"]:
        assert {"decile", "steps", "model", "popularity_baseline"} <= set(decile)


def test_two_runs_are_byte_identical(tmp_path, fitted):
    first, second = tmp_path / "first", tmp_path / "second"
    _write_files(first, *fitted)
    rows, block = expect.fit_and_predict(SYN)
    _write_files(second, rows, block)
    for name in ("expected.csv", "expect_eval.json"):
        assert (first / name).read_bytes() == (second / name).read_bytes()


def test_vocabulary_is_train_only():
    model = expect.ExpectationModel(SYN)
    sessions = {s["session_id"]: s for s in io.read_table(SYN, "sessions")}
    train_sigs = {
        st["signature"] for st in io.read_table(SYN, "steps")
        if st["kind"] != "load" and sessions[st["session_id"]]["split"] == "train"
    }
    assert set(model.vocab) <= train_sigs
    assert model.vocab == sorted(model.vocab)


def test_exposed_windows_are_excluded_from_the_fit():
    model = expect.ExpectationModel(SYN)
    sessions = {s["session_id"]: s for s in io.read_table(SYN, "sessions")}
    loads = [
        ld for ld in io.read_table(SYN, "loads")
        if ld["skill"] == "novel-skill" and sessions[ld["session_id"]]["split"] == "train"
    ]
    assert loads
    load = loads[0]
    assert model.exposed(load["session_id"], load["step"] + 1, NOVEL_COMMAND) is True
    assert model.exposed(load["session_id"], load["step"] + 1, "terminal: gog tasks get") is False
    assert [w for w in model.train_w if model.exposed(w["sid"], w["t"], NOVEL_COMMAND)]
    # gog only ever runs after a novel-skill load, so excluding those windows leaves base rate 0.
    assert model.models["win"][NOVEL_COMMAND]["base"] == 0.0


def test_rule_map_flows_into_expected_rows(tmp_path):
    rule_map = evidence.read_rule_map(_override_path(tmp_path))
    rows, _ = expect.fit_and_predict(SYN, rule_map=rule_map)
    loads = io.read_table(SYN, "loads")
    novel_ids = {ld["load_id"] for ld in loads if ld["skill"] == "novel-skill"}
    novel = [r for r in rows if r["load_id"] in novel_ids and r["rule_id"] == "novel-1"]
    # The override observes `terminal: ls`, a common command, so p_hat must move off zero.
    assert novel and max(r["p_hat"] for r in novel) > 0.05


def test_cli_writes_expected_and_eval(tmp_path):
    data = tmp_path / "synthetic"
    shutil.copytree(FIXTURES, data)
    assert expect.main(["--data", str(data), "--corpus", "synth"]) == 0
    out = data / "synth" / "out"
    rows = io.read_csv(out / "expected.csv")
    assert len(rows) == len(io.read_csv(GOLDEN / "expected.csv"))
    block = io.read_json(out / "expect_eval.json")
    assert set(block) == {"synth"}
    assert block["synth"]["corpus"] == "synth"


def _override_path(tmp_path):
    path = tmp_path / "rule_map.json"
    io.write_json(path, {"rules": [{
        "skill": "novel-skill",
        "version_id": "novel-v1",
        "rule_id": "novel-1",
        "obligation": "required",
        "observable": ["terminal: ls"],
        "approved": True,
    }]})
    return path