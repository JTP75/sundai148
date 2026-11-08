"""Source machine, stdlib only: draft rule map from versioned skill text (no text exported).

Stub created by the foundation PR; owned by W1. Replace main() with the real stage."""
from __future__ import annotations

import argparse

from potency import schema  # noqa: F401


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog='python -m potency.draft_rules', description='Source machine, stdlib only: draft rule map from versioned skill text (no text exported).')
    p.add_argument('--corpus', required=True, help='corpus name')
    p.add_argument('--skills', required=True, help='dir holding SKILL.md files')
    p.add_argument('--data', default=None, help='data dir')
    return p


def main(argv=None) -> int:
    build_parser().parse_args(argv)
    raise NotImplementedError('potency.draft_rules is not implemented yet')


if __name__ == '__main__':
    raise SystemExit(main())
