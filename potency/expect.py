"""Analysis: D3 expectation model -> out/expected.csv, out/expect_eval.json.

Stub created by the foundation PR; owned by W3. Replace main() with the real stage."""
from __future__ import annotations

import argparse

from potency import schema  # noqa: F401


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog='python -m potency.expect', description='Analysis: D3 expectation model -> out/expected.csv, out/expect_eval.json.')
    p.add_argument('--corpus', default=None, help='corpus')
    p.add_argument('--data', default=None, help='data dir')
    return p


def main(argv=None) -> int:
    build_parser().parse_args(argv)
    raise NotImplementedError('potency.expect is not implemented yet')


if __name__ == '__main__':
    raise SystemExit(main())
