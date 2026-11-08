"""Analysis: D18 evidence layer -> out/evidence.csv.

Stub created by the foundation PR; owned by W3. Replace main() with the real stage."""
from __future__ import annotations

import argparse

from potency import schema  # noqa: F401


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog='python -m potency.evidence', description='Analysis: D18 evidence layer -> out/evidence.csv.')
    p.add_argument('--corpus', default=None, help='corpus (default: every corpus in the data dir)')
    p.add_argument('--data', default=None, help='data dir')
    p.add_argument('--window', type=int, default=schema.WINDOW_N, help='window N')
    return p


def main(argv=None) -> int:
    build_parser().parse_args(argv)
    raise NotImplementedError('potency.evidence is not implemented yet')


if __name__ == '__main__':
    raise SystemExit(main())
