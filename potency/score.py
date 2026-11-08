"""Analysis: lift, controls, ranking, experiments -> out/potency.csv, strata.csv, experiments.json.

Stub created by the foundation PR; owned by W4. Replace main() with the real stage."""
from __future__ import annotations

import argparse

from potency import schema  # noqa: F401


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog='python -m potency.score', description='Analysis: lift, controls, ranking, experiments -> out/potency.csv, strata.csv, experiments.json.')
    p.add_argument('--corpus', default=None, help='corpus')
    p.add_argument('--data', default=None, help='data dir')
    p.add_argument('--program-map', default=None, help='public/local program map JSON')
    return p


def main(argv=None) -> int:
    build_parser().parse_args(argv)
    raise NotImplementedError('potency.score is not implemented yet')


if __name__ == '__main__':
    raise SystemExit(main())
