"""Source machine, stdlib only: read a corpus source and write the D12 tables + manifest.json.

Stub created by the foundation PR; owned by W1 (hermes) / W2 (claude_code adapter). Replace main() with the real stage."""
from __future__ import annotations

import argparse

from potency import schema  # noqa: F401


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog='python -m potency.extract', description='Source machine, stdlib only: read a corpus source and write the D12 tables + manifest.json.')
    p.add_argument('--corpus', required=True, help='corpus name, e.g. hermes-orin or swechat-v1')
    p.add_argument('--adapter', required=True, help='adapter: hermes | claude_code')
    p.add_argument('--source', required=True, help='source path (state.db, or a transcripts dir)')
    p.add_argument('--out', required=True, help='data dir; tables go to <out>/<corpus>/')
    return p


def main(argv=None) -> int:
    build_parser().parse_args(argv)
    raise NotImplementedError('potency.extract is not implemented yet')


if __name__ == '__main__':
    raise SystemExit(main())
