"""End-to-end run of ``potency.run_all`` on a tmp data dir (task 6.1).

W3/W4 stages are stubs on this branch, so the stage calls are patched: one test drives the happy path,
one proves a stub is reported and the pipeline keeps going with the next stage that has inputs, and the
checksum tests prove the run stops on the offending file name.
"""
from __future__ import annotations

from pathlib import Path

from potency import evidence, expect, io, run_all, score
from tests.test_report import CORPUS, make_standin_data


def _patch_stages(monkeypatch, calls: list, error=None):
    """Replace the three upstream stages with recorders that return 0 or raise ``error``."""

    def make(name):
        def fake(argv=None):
            calls.append((name, list(argv or [])))
            if error is not None:
                raise error
            return 0

        return fake

    for name, module in (("evidence", evidence), ("expect", expect), ("score", score)):
        monkeypatch.setattr(module, "main", make(name))


def _strip_outputs(data: Path) -> None:
    for path in sorted((data / CORPUS / "out").glob("*")):
        path.unlink()


def test_run_all_runs_every_stage_in_order(tmp_path, monkeypatch, capsys):
    data = make_standin_data(tmp_path)
    calls: list = []
    _patch_stages(monkeypatch, calls)
    assert run_all.main(["--data", str(data), "--corpus", CORPUS]) == 0
    assert [name for name, _ in calls] == ["evidence", "expect", "score"]
    assert (data / CORPUS / "out" / "summary.md").is_file()
    for _, argv in calls:
        assert argv[:2] == ["--data", str(data)]
        assert argv[2:4] == ["--corpus", CORPUS]
    assert "report ok" in capsys.readouterr().out


def test_run_all_continues_past_a_stub_and_still_reports(tmp_path, monkeypatch, capsys):
    data = make_standin_data(tmp_path)
    calls: list = []
    _patch_stages(monkeypatch, calls, error=NotImplementedError("stage is not implemented yet"))
    status = run_all.main(["--data", str(data), "--corpus", CORPUS])
    assert status == 1
    assert [name for name, _ in calls] == ["evidence", "expect", "score"]
    out = data / CORPUS / "out"
    assert (out / "summary.md").is_file() and (out / "status.png").is_file()
    errors = capsys.readouterr().err
    for name in ("evidence", "expect", "score"):
        assert f"stage {name} is still a stub" in errors, name


def test_run_all_passes_program_map_only_to_consumers(tmp_path, monkeypatch):
    data = make_standin_data(tmp_path)
    map_path = tmp_path / "program_map.json"
    map_path.write_text("{}\n", encoding="utf-8")
    calls: list = []
    _patch_stages(monkeypatch, calls)
    assert run_all.main(["--data", str(data), "--corpus", CORPUS, "--program-map", str(map_path)]) == 0
    for name, argv in calls:
        if name == "score":
            assert "--program-map" in argv and str(map_path) in argv
        else:
            assert "--program-map" not in argv, name


def test_run_all_stops_on_checksum_mismatch(tmp_path, monkeypatch, capsys):
    data = make_standin_data(tmp_path)
    _strip_outputs(data)
    corpus_dir = data / CORPUS
    io.write_checksums(corpus_dir, sorted(p.name for p in corpus_dir.glob("*.jsonl")))
    (corpus_dir / "steps.jsonl").write_text("tampered\n", encoding="utf-8")
    calls: list = []
    _patch_stages(monkeypatch, calls)
    assert run_all.main(["--data", str(data), "--corpus", CORPUS]) == 1
    errors = capsys.readouterr().err
    assert "checksum mismatch: steps.jsonl" in errors
    assert calls == [], "no stage runs after a checksum failure"
    assert not (corpus_dir / "out" / "summary.md").exists()


def test_run_all_stops_on_a_missing_checksummed_file(tmp_path, capsys):
    data = make_standin_data(tmp_path)
    _strip_outputs(data)
    corpus_dir = data / CORPUS
    io.write_checksums(corpus_dir, sorted(p.name for p in corpus_dir.glob("*.jsonl")))
    (corpus_dir / "loads.jsonl").unlink()
    assert run_all.main(["--data", str(data), "--corpus", CORPUS]) == 1
    assert "missing file loads.jsonl" in capsys.readouterr().err


def test_run_all_skips_stages_without_inputs(tmp_path, capsys):
    data = tmp_path / "data"
    corpus_dir = data / CORPUS
    io.write_table(corpus_dir, "sessions", [])
    (corpus_dir / "out").mkdir(parents=True, exist_ok=True)
    assert run_all.main(["--data", str(data), "--corpus", CORPUS]) == 1
    errors = capsys.readouterr().err
    assert "skipping evidence (missing loads.jsonl" in errors


def test_run_all_without_a_corpus_walks_the_data_dir(tmp_path, monkeypatch):
    data = make_standin_data(tmp_path)
    calls: list = []
    _patch_stages(monkeypatch, calls)
    assert run_all.main(["--data", str(data)]) == 0
    assert calls and all(argv[2:4] == ["--corpus", CORPUS] for _, argv in calls)


def test_run_all_errors_on_an_empty_data_dir(tmp_path, capsys):
    assert run_all.main(["--data", str(tmp_path / "missing")]) == 1
    assert "no corpus directories" in capsys.readouterr().err
