"""Tests for the D18 evidence layer: golden equality, handcrafted cases, rule-map overrides."""
import shutil
from pathlib import Path

import pytest

from potency import evidence, io, schema

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures" / "synthetic"
SYN = FIXTURES / "synth"
GOLDEN = FIXTURES / "golden"
CASES = io.read_json(GOLDEN / "cases.json")


@pytest.fixture(scope="module")
def base_rows():
    return evidence.compute_evidence(SYN)


@pytest.fixture(scope="module")
def golden_evidence():
    return io.read_csv(GOLDEN / "evidence.csv")


def _rows(rows, session_id, rule_id):
    return [r for r in rows if r["session_id"] == session_id and r["rule_id"] == rule_id]


def _write_rule_map(tmp_path, rules, name="rule_map.json"):
    path = tmp_path / name
    io.write_json(path, {"rules": rules})
    return path


def _override(observable, approved=True, rule_id="novel-1", **extra):
    return {
        "skill": "novel-skill",
        "version_id": "novel-v1",
        "rule_id": rule_id,
        "obligation": "required",
        "observable": observable,
        "approved": approved,
        **extra,
    }


def test_evidence_matches_golden_bytewise(base_rows, tmp_path):
    path = tmp_path / "evidence.csv"
    io.write_output_csv(path, base_rows)
    assert path.read_bytes() == (GOLDEN / "evidence.csv").read_bytes()


def test_rows_sorted_and_columns_match_schema(base_rows):
    keys = [(r["load_id"], r["rule_id"]) for r in base_rows]
    assert keys == sorted(keys)
    assert set(base_rows[0]) == set(schema.OUTPUT_COLUMNS["evidence.csv"])


def test_one_row_per_scorable_load_and_rule(base_rows, golden_evidence):
    assert len(base_rows) == len(golden_evidence)
    assert [r["load_id"] for r in base_rows] == [r["load_id"] for r in golden_evidence]


def test_no_excluded_load_leaks_a_row(base_rows):
    loads = {ld["load_id"]: ld for ld in io.read_table(SYN, "loads")}
    for row in base_rows:
        load = loads[row["load_id"]]
        assert not set(load["flags"]) & {"maintenance", "repeat"}
        assert load["version_source"] != "version_unknown"


@pytest.mark.parametrize(
    "case", CASES, ids=[f"{c['session_id']}:{c['rule_id']}" for c in CASES]
)
def test_every_golden_case(base_rows, case):
    rows = _rows(base_rows, case["session_id"], case["rule_id"])
    if case["status"] is None:
        assert rows == [], case
        return
    assert len(rows) == 1, case
    assert (rows[0]["status"], rows[0]["reason"]) == (case["status"], case["reason"]), case
    if "flags" in case:
        load = next(ld for ld in io.read_table(SYN, "loads") if ld["session_id"] == case["session_id"])
        assert case["flags"] == load["flags"], case


def test_evidence_steps_are_window_step_ids(base_rows):
    for row in base_rows:
        if row["status"] == "supported_agreement" or row["reason"] == "same_batch_only":
            assert row["evidence_steps"], row
            assert all(row["window_start"] <= s <= row["window_end"] for s in row["evidence_steps"])
        else:
            assert row["evidence_steps"] == [], row


def test_window_parameter_truncates_rows():
    rows = evidence.compute_evidence(SYN, window=5)
    assert len(rows) == len(evidence.compute_evidence(SYN))
    for row in rows:
        assert 1 <= row["window_end"] - row["window_start"] + 1 <= 5


def test_rule_map_approved_group_overrides(tmp_path):
    rule_map = evidence.read_rule_map(_write_rule_map(tmp_path, [_override(["terminal: ls"])]))
    assert set(rule_map) == {("novel-skill", "novel-v1")}
    rows = evidence.compute_evidence(SYN, rule_map=rule_map)
    # case-nomatch has no gog call, but its window is full of `terminal: ls`.
    row = _rows(rows, "case-nomatch", "novel-1")[0]
    assert (row["status"], row["reason"]) == ("supported_agreement", "matched")
    assert _rows(rows, "case-matched", "novel-1")[0]["status"] == "supported_agreement"


def test_rule_map_unapproved_group_is_ignored(tmp_path, base_rows):
    rule_map = evidence.read_rule_map(
        _write_rule_map(tmp_path, [_override(["terminal: ls"], approved=False)])
    )
    assert rule_map == {}
    assert evidence.compute_evidence(SYN, rule_map=rule_map) == base_rows


def test_rule_map_group_needs_every_rule_approved(tmp_path):
    rules = [
        _override(["terminal: ls"]),
        _override(["terminal: cat"], rule_id="novel-2", approved=False),
    ]
    assert evidence.read_rule_map(_write_rule_map(tmp_path, rules)) == {}


def test_rule_map_accepts_bare_list(tmp_path):
    path = tmp_path / "bare.json"
    io.write_json(path, [_override(["terminal: ls"])])
    assert set(evidence.read_rule_map(path)) == {("novel-skill", "novel-v1")}


def test_rule_map_ignores_unlisted_groups(tmp_path, base_rows):
    rules = [{
        "skill": "alt-skill", "version_id": "alt-v1", "rule_id": "alt-1",
        "obligation": "required", "observable": ["terminal: make"], "approved": True,
    }]
    rule_map = evidence.read_rule_map(_write_rule_map(tmp_path, rules))
    rows = evidence.compute_evidence(SYN, rule_map=rule_map)
    assert _rows(rows, "case-alternative", "alt-1")[0]["status"] == "no_observed_agreement"
    # Every non-listed group keeps its corpus rules.
    for version in ("novel-v1", "habit-v1", "mid-v2", "cond-v1"):
        before = [r for r in base_rows if r["version_id"] == version]
        after = [r for r in rows if r["version_id"] == version]
        assert before == after


def test_cli_writes_out_evidence(tmp_path):
    data = tmp_path / "synthetic"
    shutil.copytree(FIXTURES, data)
    assert evidence.main(["--data", str(data), "--corpus", "synth"]) == 0
    written = data / "synth" / "out" / "evidence.csv"
    assert written.read_bytes() == (GOLDEN / "evidence.csv").read_bytes()


def test_corpus_name_falls_back_to_directory(tmp_path):
    empty = tmp_path / "not-a-corpus"
    empty.mkdir()
    assert evidence.corpus_name(empty) == "not-a-corpus"