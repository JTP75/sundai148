"""Source machine, stdlib only: outcome-free counts (corpus-intake spec) -> census.json.

Stub created by the foundation PR; owned by W1. Replace main() with the real stage."""
from __future__ import annotations

import argparse

from potency import schema  # noqa: F401


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog='python -m potency.census', description='Source machine, stdlib only: outcome-free counts (corpus-intake spec) -> census.json.')
    p.add_argument('--corpus', required=True, help='corpus name')
    p.add_argument('--data', default=None, help='data dir (default $POTENCY_DATA_DIR or ./data)')
    return p


def main(argv=None) -> int:
    build_parser().parse_args(argv)
    raise NotImplementedError('potency.census is not implemented yet')


if __name__ == '__main__':
    raise SystemExit(main())
