"""
CLI entry point for mbtiles2vtpk.

Usage:
    mbtiles2vtpk input.mbtiles output.vtpk
    mbtiles2vtpk input.mbtiles output.vtpk --style https://...
    mbtiles2vtpk input.mbtiles output.vtpk --style ./my-style.json --work-dir C:/Temp
    mbtiles2vtpk --cache-info
    mbtiles2vtpk --clear-cache
"""

import argparse
import sys

from .converter import MBTiles2VTPKConverter


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mbtiles2vtpk",
        description="Convert a MBTiles vector tile package to the VTPK format.",
    )

    # --- Conversion arguments ---
    parser.add_argument(
        "input",
        metavar="INPUT",
        nargs="?",
        help="Path to the source .mbtiles file.",
    )
    parser.add_argument(
        "output",
        metavar="OUTPUT",
        nargs="?",
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
            "Mapbox GL style to embed — URL or local path. "
            "Referenced fonts and sprites are downloaded automatically "
            "and cached in ~/.mbtiles2vtpk/cache/. "
            "Example: https://raw.githubusercontent.com/mapbox/mapbox-gl-styles"
            "/master/styles/basic-v8.json"
        ),
    )

    # --- Cache management ---
    parser.add_argument(
        "--cache-info",
        action="store_true",
        help="Show cache location and total size, then exit.",
    )
    parser.add_argument(
        "--clear-cache",
        action="store_true",
        help="Delete all cached fonts and sprites, then exit.",
    )

    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    # --- Cache management commands ---
    if args.cache_info or args.clear_cache:
        from .cache import cache_size, clear, _CACHE_ROOT
        import os
        if args.clear_cache:
            n = clear()
            print(f"Cache cleared: {n} file(s) deleted from {_CACHE_ROOT}")
        else:
            size_mb = cache_size() / 1_048_576
            print(f"Cache location : {_CACHE_ROOT}")
            print(f"Cache size     : {size_mb:.1f} MB")
        return 0

    # --- Conversion ---
    if not args.input or not args.output:
        parser.print_help()
        return 1

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
