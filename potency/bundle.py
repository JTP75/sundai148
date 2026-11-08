"""Pack a corpus dir into derived-<corpus>-<manifest hash>.zip with a SHA-256 list.

Design D11, corpus-intake spec: the bundle is the only thing that leaves the source machine, so the
privacy backstop runs first and every file is checksummed. Entries carry a fixed timestamp and are
written in sorted order, so the same corpus dir produces the same zip bytes on every OS.
"""
from __future__ import annotations

import argparse
import zipfile
from pathlib import Path

from potency import io, privacy, schema

BUNDLE_EXTRA_FILES = ("census.json", "rules_draft.json")
FIXED_DATE_TIME = (1980, 1, 1, 0, 0, 0)
MANIFEST_HASH_CHARS = 12


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog='python -m potency.bundle', description='Pack a corpus dir into derived-<corpus>-<manifest hash>.zip with a SHA-256 list.')
    p.add_argument('--corpus', required=True, help='corpus name')
    p.add_argument('--data', default=None, help='data dir')
    p.add_argument('--out', default='.', help='directory for the zip')
    p.add_argument('--forbidden', action='append', default=[], metavar='STRING',
                   help='literal that must never appear in an output (repeatable)')
    p.add_argument('--verify', action='store_true',
                   help='also verify checksums.sha256 before packing (fails on a corrupted dir)')
    return p


def source_files(corpus_dir) -> list[str]:
    """Exported source files in one corpus dir, sorted; analysis outputs and the checksum list are out."""
    corpus_dir = Path(corpus_dir)
    names = [f"{table}.jsonl" for table in schema.TABLES] + ["manifest.json", *BUNDLE_EXTRA_FILES]
    return sorted(name for name in names if (corpus_dir / name).is_file())


def manifest_hash(corpus_dir) -> str:
    return io.sha256_file(Path(corpus_dir) / "manifest.json")[:MANIFEST_HASH_CHARS]


def bundle(corpus_dir, out_dir, corpus: str | None = None, forbidden=(), verify: bool = False) -> Path:
    corpus_dir = Path(corpus_dir)
    corpus = corpus or corpus_dir.name
    if not (corpus_dir / "manifest.json").is_file():
        raise FileNotFoundError(f"{corpus}: no manifest.json; run potency.extract first")
    if verify:
        io.verify_checksums(corpus_dir)
    privacy.check_corpus_dir(corpus_dir, forbidden=list(forbidden))
    names = source_files(corpus_dir)
    io.write_checksums(corpus_dir, names)
    members = sorted([*names, schema.CHECKSUMS_FILE])
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"derived-{corpus}-{manifest_hash(corpus_dir)}.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in members:
            info = zipfile.ZipInfo(name, date_time=FIXED_DATE_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, (corpus_dir / name).read_bytes())
    return out


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    corpus_dir = io.resolve_data_dir(args.data) / args.corpus
    out = bundle(corpus_dir, args.out, args.corpus, forbidden=args.forbidden, verify=args.verify)
    print(f"bundle\t{out}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
