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
import threading

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

        # Temporary output dir placed OUTSIDE work_dir so it is never
        # accidentally included in the final VTPK zip.
        import tempfile
        tmp_out = tempfile.mkdtemp(prefix="mbtiles2cc_")
        log.info("Temp bundle dir: %s", tmp_out)

        self._run_external_tool(tmp_out)
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

    def _run_external_tool(self, dest_dir: str) -> None:
        cmd = [
            sys.executable,
            "-u",
            MBTILES2CC_SCRIPT,
            "-s", self.mbtiles_path,
            "-d", dest_dir,
        ]
        log.info("Running: %s", " ".join(cmd))
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )

        stderr_lines = []

        def stream_stdout():
            for line in process.stdout:
                line = line.rstrip()
                if line:
                    log.info("  [mbtiles2cc stdout] %s", line)

        def stream_stderr():
            for line in process.stderr:
                line = line.rstrip()
                if line:
                    log.warning("  [mbtiles2cc stderr] %s", line)
                    stderr_lines.append(line)

        stdout_thread = threading.Thread(target=stream_stdout, daemon=True)
        stderr_thread = threading.Thread(target=stream_stderr, daemon=True)
        stdout_thread.start()
        stderr_thread.start()

        stdout_thread.join()
        stderr_thread.join()
        process.wait()

        if process.returncode != 0 or stderr_lines:
            raise RuntimeError(
                f"mbtiles2compactcache failed (exit code {process.returncode}):\n"
                + "\n".join(stderr_lines)
            )




    def _move_bundles(self, tmp_out: str) -> None:
        """
        Move bundles from <tmp_out>/_alllayers/L<zz>/ → p12/tile/L<zz>/.
        The external tool may output to _alllayers/ or directly to the dest
        root — we handle both layouts.
        """
        tile_dest = os.path.join(self.work_dir, "p12", "tile")        
        
        if os.path.isdir(tmp_out) and any(
                e.startswith("L") for e in os.listdir(tmp_out)
            ):
                source_root = tmp_out
        
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
                log.info("  Moved: %s/%s (%.1f KB)",
                         entry, bundle, os.path.getsize(dst)/1024)
