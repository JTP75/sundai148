"""Source machine, stdlib only: read a corpus source and write the D12 tables + manifest.json.

One adapter per harness, one intermediate format (design D11, D12). The adapter reads its source
read-only and returns the six tables; this stage writes them deterministically and runs the privacy
backstop before anything can leave the machine.
"""
from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path

from potency import io, privacy, schema

ADAPTERS = ("hermes", "claude_code")
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog='python -m potency.extract', description='Source machine, stdlib only: read a corpus source and write the D12 tables + manifest.json.')
    p.add_argument('--corpus', required=True, help='corpus name, e.g. hermes-orin or swechat-v1')
    p.add_argument('--adapter', required=True, choices=ADAPTERS, help='adapter: hermes | claude_code')
    p.add_argument('--source', required=True, help='source path (state.db, or a transcripts dir)')
    p.add_argument('--out', required=True, help='data dir; tables go to <out>/<corpus>/')
    p.add_argument('--forbidden', action='append', default=[], metavar='STRING',
                   help='literal that must never appear in an output (repeatable)')
    return p


def extractor_git_sha() -> str | None:
    """sha of the checkout running the extractor, if git and a repository are available."""
    try:
        done = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).resolve().parent.parent,
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    sha = done.stdout.strip()
    return sha if done.returncode == 0 and _GIT_SHA_RE.match(sha) else None


def run_adapter(adapter: str, source, corpus: str):
    """``(tables, meta)`` from the adapter; the import is lazy so a missing adapter only fails here."""
    if adapter == "hermes":
        from potency.adapters import hermes

        return hermes.extract_with_meta(source, corpus)
    if adapter == "claude_code":
        from potency.adapters import claude_code

        return claude_code.extract(source, corpus), {}
    raise ValueError(f"unknown adapter {adapter!r}")


def build_manifest(tables: dict[str, list[dict]], meta: dict, corpus: str, adapter: str) -> dict:
    """Snapshot record (corpus-intake spec): max ids/timestamp, row counts, split cutoff, extractor sha."""
    sessions = tables.get("sessions", [])
    starts = [r["start_ts"] for r in sessions if isinstance(r.get("start_ts"), (int, float))]
    cutoff = meta.get("split_cutoff_ts")
    if cutoff is None:
        train = [r["start_ts"] for r in sessions if r.get("split") == "train"]
        cutoff = max(train) if train else None
    return {
        "corpus": corpus,
        "adapter": adapter,
        "generated_by": "potency.extract",
        "extractor_git_sha": meta.get("extractor_git_sha") or extractor_git_sha(),
        "max_message_id": meta.get("max_message_id"),
        "max_timestamp": meta.get("max_timestamp", max(starts) if starts else None),
        "split_cutoff_ts": cutoff,
        "split_counts": meta.get("split_counts") or {
            "train": sum(1 for r in sessions if r.get("split") == "train"),
            "test": sum(1 for r in sessions if r.get("split") == "test"),
        },
        "row_counts": {table: len(tables.get(table, [])) for table in schema.TABLES},
        "source": meta.get("source") or {},
    }


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    source = Path(args.source)
    corpus_dir = io.resolve_data_dir(args.out) / args.corpus
    tables, meta = run_adapter(args.adapter, source, args.corpus)
    counts = {table: io.write_table(corpus_dir, table, tables.get(table, [])) for table in schema.TABLES}
    manifest = build_manifest(tables, meta, args.corpus, args.adapter)
    io.write_json(corpus_dir / "manifest.json", manifest)
    privacy.check_corpus_dir(corpus_dir, forbidden=args.forbidden)
    for table in schema.TABLES:
        print(f"{table}\t{counts[table]}")
    print(f"manifest\t{corpus_dir / 'manifest.json'}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
