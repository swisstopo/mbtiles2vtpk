"""
CLI entry point for mbtiles2vtpk.

Usage:
    python -m mbtiles2vtpk.cli input.mbtiles output.vtpk
    python -m mbtiles2vtpk.cli input.mbtiles output.vtpk --style https://...
    python -m mbtiles2vtpk.cli input.mbtiles output.vtpk --style ./my-style.json
    python -m mbtiles2vtpk.cli input.mbtiles output.vtpk --work-dir C:/Temp/work
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
    parser.add_argument(
        "--style",
        metavar="URL_OR_PATH",
        default=None,
        help=(
            "Optional Mapbox GL style to embed. Can be a URL (https://...) or a "
            "local file path. Referenced fonts and sprites will be downloaded "
            "automatically. Example: "
            "https://raw.githubusercontent.com/mapbox/mapbox-gl-styles/"
            "master/styles/basic-v8.json"
        ),
    )
    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    converter = MBTiles2VTPKConverter(
        mbtiles_path=args.input,
        output_path=args.output,
        work_dir=args.work_dir,
        style_source=args.style,
    )
    converter.convert()
    return 0


if __name__ == "__main__":
    sys.exit(main())
