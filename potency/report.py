"""Analysis: charts and summary -> out/potency.png, status.png, summary.md.

Stub created by the foundation PR; owned by W5. Replace main() with the real stage."""
from __future__ import annotations

import argparse

from potency import schema  # noqa: F401


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog='python -m potency.report', description='Analysis: charts and summary -> out/potency.png, status.png, summary.md.')
    p.add_argument('--corpus', default=None, help='corpus')
    p.add_argument('--data', default=None, help='data dir')
    return p


def main(argv=None) -> int:
    build_parser().parse_args(argv)
    raise NotImplementedError('potency.report is not implemented yet')


if __name__ == '__main__':
    raise SystemExit(main())
