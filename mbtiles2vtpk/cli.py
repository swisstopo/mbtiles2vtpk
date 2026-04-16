"""
CLI entry point for mbtiles2vtpk.

Usage:
    python -m mbtiles2vtpk.cli input.mbtiles output.vtpk [--work-dir /tmp/work]
"""

import argparse
import sys

from .converter import MBTiles2VTPKConverter


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mbtiles2vtpk",
        description="Convert a MBTiles vector tile package to the VTPK format.",
    )
    parser.add_argument(
        "input",
        metavar="INPUT",
        help="Path to the source .mbtiles file.",
    )
    parser.add_argument(
        "output",
        metavar="OUTPUT",
        help="Path for the output .vtpk file.",
    )
    parser.add_argument(
        "--work-dir",
        metavar="DIR",
        default=None,
        help="Working directory for intermediate files (default: auto temp dir).",
    )
    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    converter = MBTiles2VTPKConverter(
        mbtiles_path=args.input,
        output_path=args.output,
        work_dir=args.work_dir,
    )
    converter.convert()
    return 0


if __name__ == "__main__":
    sys.exit(main())
