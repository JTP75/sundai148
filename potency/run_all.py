"""Analysis: verify checksums, then evidence -> expect -> score -> report (task 6.1).

``run_all`` is the one command the runbook and CI use. It verifies ``checksums.sha256`` when the bundle
ships one (stopping on the first mismatching file name), then calls each stage's ``main`` in process so
a stub or a missing input is reported once instead of as a traceback.

A stage that raises ``NotImplementedError`` (still a stub, W3/W4) is reported and skipped; the next stage
runs only when its own inputs exist. Any skip makes the overall exit status non-zero, so a partial
pipeline can never look green.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from potency import evidence, expect, io, report, schema, score

# (stage name, module, required inputs relative to the corpus dir)
STAGES = (
    ("evidence", evidence, ("loads.jsonl", "steps.jsonl", "rules.jsonl")),
    ("expect", expect, ("out/evidence.csv",)),
    ("score", score, ("out/evidence.csv", "out/expected.csv")),
    ("report", report, ("out/evidence.csv",)),
)
PROGRAM_MAP_STAGES = ("score", "report")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m potency.run_all",
        description="Analysis: verify checksums, then evidence -> expect -> score -> report.",
    )
    p.add_argument("--corpus", default=None, help="corpus (default: every corpus in the data dir)")
    p.add_argument("--data", default=None, help="data dir")
    p.add_argument("--program-map", default=None, help="public/local program map JSON (score, report)")
    return p


def corpora(data_dir: Path, corpus: str | None = None) -> list:
    """Corpus dirs to process: the named one, else those holding a sessions table or evidence output."""
    data_dir = Path(data_dir)
    if corpus:
        return [data_dir / corpus]
    if not data_dir.is_dir():
        return []
    return sorted(
        path for path in data_dir.iterdir()
        if path.is_dir() and ((path / "sessions.jsonl").exists() or (path / "out" / "evidence.csv").exists())
    )


def verify_checksums(directory: Path, stream=None) -> bool:
    """Verify <directory>/checksums.sha256 when present. False means stop the run."""
    stream = sys.stderr if stream is None else stream
    path = Path(directory) / schema.CHECKSUMS_FILE
    if not path.exists():
        return True
    try:
        io.verify_checksums(directory)
    except (ValueError, FileNotFoundError) as exc:
        print(f"run_all: checksum verification failed: {exc}", file=stream)
        return False
    print(f"run_all: checksums ok in {Path(directory).as_posix()}")
    return True


def _stage_args(data_dir: Path, corpus_dir: Path, stage: str, program_map) -> list:
    args = ["--data", str(data_dir), "--corpus", Path(corpus_dir).name]
    if program_map and stage in PROGRAM_MAP_STAGES:
        args += ["--program-map", str(program_map)]
    return args


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    data_dir = Path(io.resolve_data_dir(args.data))
    corpus_dirs = corpora(data_dir, args.corpus)
    if not corpus_dirs:
        print(f"run_all: no corpus directories under {data_dir}", file=sys.stderr)
        return 1
    if not verify_checksums(data_dir):
        return 1

    failed = False
    for corpus_dir in corpus_dirs:
        if not Path(corpus_dir).is_dir():
            print(f"run_all: corpus dir not found: {corpus_dir}", file=sys.stderr)
            failed = True
            continue
        if not verify_checksums(corpus_dir):
            return 1
        for stage, module, required in STAGES:
            missing = [name for name in required if not (corpus_dir / name).exists()]
            if missing:
                print(f"run_all: {corpus_dir.name}: skipping {stage} (missing {', '.join(missing)})",
                      file=sys.stderr)
                failed = True
                continue
            try:
                status = module.main(_stage_args(data_dir, corpus_dir, stage, args.program_map))
            except NotImplementedError as exc:
                print(f"run_all: {corpus_dir.name}: stage {stage} is still a stub ({exc}); "
                      f"continuing with the next stage that has inputs", file=sys.stderr)
                failed = True
                continue
            except FileNotFoundError as exc:
                print(f"run_all: {corpus_dir.name}: stage {stage} failed: {exc}", file=sys.stderr)
                failed = True
                continue
            if status:
                print(f"run_all: {corpus_dir.name}: stage {stage} exited {status}", file=sys.stderr)
                failed = True
            else:
                print(f"run_all: {corpus_dir.name}: {stage} ok")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
