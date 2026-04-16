"""
Step 2 – Extract tiles from MBTiles into VTPK compact cache format.

Delegates the actual bundle creation to the external tool:
    https://github.com/ltbam/python-mbtiles2compactcache

The tool is included as a git dependency and invoked via subprocess.
It writes bundles under <dest>/_alllayers/L<zz>/ which we then move
to the expected VTPK location p12/tile/L<zz>/.

CLI used:
    python mbtiles2compactcache.py -ml <max_zoom> -s <source.mbtiles> -d <dest_dir>
"""

import os
import shutil
import sqlite3
import subprocess
import sys

from .base_step import BaseStep
from ..logger import get_logger

log = get_logger("TileExtractor")

# Path to the bundled external script, relative to this file's package root.
# Resolved at runtime so it works regardless of install location.
_THIS_DIR   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SCRIPT_REL = os.path.join("vendor", "python-mbtiles2compactcache", "code", "mbtiles2compactcache.py")
MBTILES2CC_SCRIPT = os.path.join(_THIS_DIR, _SCRIPT_REL)


class TileExtractor(BaseStep):
    """
    Calls python-mbtiles2compactcache to produce Compact Cache V2 bundles
    from the source MBTiles file, then moves them into p12/tile/.

    The external script outputs to:
        <tmp_dir>/_alllayers/L<zz>/R<rrrr>C<cccc>.bundle

    We relocate them to:
        <work_dir>/p12/tile/L<zz>/R<rrrr>C<cccc>.bundle
    """

    def __init__(self, mbtiles_path: str, work_dir: str):
        self.mbtiles_path = mbtiles_path
        self.work_dir = work_dir

    # ------------------------------------------------------------------

    def run(self) -> None:
        self._check_script()

        max_zoom = self._read_max_zoom()
        log.info("Source MBTiles max zoom: %d", max_zoom)

        # Temporary output directory for the external tool
        tmp_out = os.path.join(self.work_dir, "_cc_tmp")
        os.makedirs(tmp_out, exist_ok=True)

        self._run_external_tool(max_zoom, tmp_out)
        self._move_bundles(tmp_out)

        # Clean up temp dir
        shutil.rmtree(tmp_out, ignore_errors=True)
        log.info("Tile extraction complete.")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _check_script(self) -> None:
        if not os.path.isfile(MBTILES2CC_SCRIPT):
            raise FileNotFoundError(
                f"python-mbtiles2compactcache script not found at:\n  {MBTILES2CC_SCRIPT}\n"
                "Run:  git submodule update --init --recursive"
            )
        log.info("Using external tool: %s", MBTILES2CC_SCRIPT)

    def _read_max_zoom(self) -> int:
        con = sqlite3.connect(self.mbtiles_path)
        try:
            cur = con.execute("SELECT value FROM metadata WHERE name='maxzoom'")
            row = cur.fetchone()
            return int(row[0]) if row else 0
        finally:
            con.close()

    def _run_external_tool(self, max_zoom: int, dest_dir: str) -> None:
        cmd = [
            sys.executable,          # same Python interpreter as caller
            MBTILES2CC_SCRIPT,
            "-ml", str(max_zoom),
            "-s",  self.mbtiles_path,
            "-d",  dest_dir,
        ]
        log.info("Running: %s", " ".join(cmd))

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
        )

        # Forward stdout/stderr from the tool to our logger
        for line in result.stdout.splitlines():
            if line.strip():
                log.info("  [mbtiles2cc] %s", line)
        for line in result.stderr.splitlines():
            if line.strip():
                log.warning("  [mbtiles2cc] %s", line)

        if result.returncode != 0:
            raise RuntimeError(
                f"mbtiles2compactcache exited with code {result.returncode}"
            )

    def _move_bundles(self, tmp_out: str) -> None:
        """
        Move bundles from <tmp_out>/_alllayers/L<zz>/ → p12/tile/L<zz>/.
        The external tool may output to _alllayers/ or directly to the dest
        root — we handle both layouts.
        """
        tile_dest = os.path.join(self.work_dir, "p12", "tile")

        # Try _alllayers sub-folder first (EsriDE convention), then bare root
        candidates = [
            os.path.join(tmp_out, "A3_MyCachedService", "Layers", "_alllayers"),
            tmp_out,
        ]
        source_root = None
        for candidate in candidates:
            if os.path.isdir(candidate) and any(
                e.startswith("L") for e in os.listdir(candidate)
            ):
                source_root = candidate
                break

        if source_root is None:
            raise RuntimeError(
                f"No bundle directories found under {tmp_out} after running "
                "mbtiles2compactcache. Expected L<zz> folders."
            )

        log.info("Moving bundles from: %s", source_root)

        for entry in sorted(os.listdir(source_root)):
            if not entry.startswith("L"):
                continue
            src_zoom_dir = os.path.join(source_root, entry)
            if not os.path.isdir(src_zoom_dir):
                continue

            dst_zoom_dir = os.path.join(tile_dest, entry)
            os.makedirs(dst_zoom_dir, exist_ok=True)

            bundles = [f for f in os.listdir(src_zoom_dir) if f.endswith(".bundle")]
            for bundle in bundles:
                src = os.path.join(src_zoom_dir, bundle)
                dst = os.path.join(dst_zoom_dir, bundle)
                shutil.move(src, dst)
                log.info("  Moved: %s/%s (%s KB)", entry, bundle,
                         f"{os.path.getsize(dst)/1024:.1f}")
