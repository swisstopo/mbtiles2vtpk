"""
CLI entry point for mbtiles2vtpk.

Usage:
    mbtiles2vtpk -i input.mbtiles -o output.vtpk
    mbtiles2vtpk -i input.mbtiles -o output.vtpk --style https://...
    mbtiles2vtpk -i input.mbtiles -o output.vtpk --style ./my-style.json
    mbtiles2vtpk --cache-info
    mbtiles2vtpk --clear-cache
"""

import argparse
import sys


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mbtiles2vtpk",
        description="Convert a MBTiles vector tile package to the VTPK format.",
    )

    # --- Conversion arguments ---
    parser.add_argument(
        "-i", "--input",
        metavar="INPUT",
        help="Path to the source .mbtiles file.",
    )
    parser.add_argument(
        "-o", "--output",
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
            "Mapbox GL style to embed — URL or local path. "
            "Referenced fonts and sprites are downloaded automatically "
            "and cached in ~/.mbtiles2vtpk/cache/. "
            "For styles on api.maptiler.com set MAPTILER_KEY and "
            "MAPTILER_ORIGIN environment variables."
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

    # --- Cache management commands (no conversion needed) ---
    if args.cache_info or args.clear_cache:
        from .cache import cache_size, clear, _CACHE_ROOT
        if args.clear_cache:
            n = clear()
            print(f"Cache cleared: {n} file(s) deleted from {_CACHE_ROOT}")
        else:
            size_mb = cache_size() / 1_048_576
            print(f"Cache location : {_CACHE_ROOT}")
            print(f"Cache size     : {size_mb:.1f} MB")
        return 0

    # --- Validate required conversion arguments ---
    if not args.input or not args.output:
        parser.print_help()
        print("\nerror: -i/--input and -o/--output are required for conversion.", file=sys.stderr)
        return 1

    # --- Run conversion ---
    from .converter import MBTiles2VTPKConverter
    from .cache import FetchError

    try:
        converter = MBTiles2VTPKConverter(
            mbtiles_path=args.input,
            output_path=args.output,
            work_dir=args.work_dir,
            style_source=args.style,
        )
        converter.convert()
    except FetchError as e:
        print(f"\n[ERROR] Download failed — conversion aborted.\n{e}", file=sys.stderr)
        return 1
    except FileNotFoundError as e:
        print(f"\n[ERROR] File not found — conversion aborted.\n{e}", file=sys.stderr)
        return 1
    except ValueError as e:
        print(f"\n[ERROR] {e}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
