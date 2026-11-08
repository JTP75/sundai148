"""Pack a corpus dir into derived-<corpus>-<manifest hash>.zip with a SHA-256 list.

Stub created by the foundation PR; owned by W1. Replace main() with the real stage."""
from __future__ import annotations

import argparse

from potency import schema  # noqa: F401


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog='python -m potency.bundle', description='Pack a corpus dir into derived-<corpus>-<manifest hash>.zip with a SHA-256 list.')
    p.add_argument('--corpus', required=True, help='corpus name')
    p.add_argument('--data', default=None, help='data dir')
    p.add_argument('--out', default='.', help='directory for the zip')
    return p


def main(argv=None) -> int:
    build_parser().parse_args(argv)
    raise NotImplementedError('potency.bundle is not implemented yet')


if __name__ == '__main__':
    raise SystemExit(main())
