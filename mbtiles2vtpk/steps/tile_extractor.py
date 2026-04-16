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
        self._ensure_rowid()

        max_zoom = self._read_max_zoom()
        log.info("Source MBTiles max zoom: %d", max_zoom)

        # Temporary output dir placed OUTSIDE work_dir so it is never
        # accidentally included in the final VTPK zip.
        import tempfile
        tmp_out = tempfile.mkdtemp(prefix="mbtiles2cc_")
        log.info("Temp bundle dir: %s", tmp_out)

        self._run_external_tool(max_zoom, tmp_out)
        self._move_bundles(tmp_out)

        # Clean up temp dir
        shutil.rmtree(tmp_out, ignore_errors=True)
        log.info("Tile extraction complete.")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _ensure_rowid(self) -> None:
        """
        Ensure the 'tiles' view/table exposes a 'rowid' column as expected
        by mbtiles2compactcache.py for sequential access:

            SELECT * FROM tiles WHERE rowid > {start} LIMIT {n}

        Strategy (non-destructive — never modifies the original data):

        Case 1 – tiles is a VIEW with rowid already    → nothing to do
        Case 2 – tiles is a VIEW without rowid         → try to rebuild the
                 view using map.rowid (standard split schema). If map table
                 doesn't exist, fall through to Case 3.
        Case 3 – tiles is a TABLE, or view rebuild not possible
                 → copy tiles into a new table '_tiles_with_rowid' that has
                   an explicit INTEGER PRIMARY KEY (= real SQLite rowid),
                   then DROP the original view/table and recreate 'tiles'
                   as a view over '_tiles_with_rowid'.
                   The copy is ordered by (zoom_level, tile_column, tile_row)
                   so rowid is a stable sequential key identical to what
                   OFFSET/LIMIT would produce.
        """
        con = sqlite3.connect(self.mbtiles_path)
        try:
            # --- Case 1: rowid already exposed? ---
            cur = con.execute("PRAGMA table_info(tiles)")
            columns = [row[1] for row in cur.fetchall()]
            if "rowid" in columns:
                log.info("'tiles' already exposes rowid — no patch needed.")
                return

            cur = con.execute(
                "SELECT type FROM sqlite_master WHERE name='tiles'"
            )
            row = cur.fetchone()
            if row is None:
                raise RuntimeError("No 'tiles' table or view found in MBTiles.")
            obj_type = row[0]

            log.warning("'tiles' %s has no rowid column — patching…", obj_type)

            # --- Case 2: standard split schema (map + images) ---
            if obj_type == "view":
                cur = con.execute(
                    "SELECT name FROM sqlite_master WHERE name='map' AND type='table'"
                )
                if cur.fetchone():
                    log.info("  Standard split schema detected — rebuilding view with map.rowid.")
                    con.execute("DROP VIEW tiles")
                    con.execute("""
                        CREATE VIEW tiles AS
                            SELECT map.rowid      AS rowid,
                                   map.zoom_level,
                                   map.tile_column,
                                   map.tile_row,
                                   images.tile_data
                            FROM map
                            JOIN images ON images.tile_id = map.tile_id
                    """)
                    con.commit()
                    log.info("  'tiles' view rebuilt with rowid. Done.")
                    return

            # --- Case 3: flat table or non-standard view ---
            # Count rows so we can log progress
            total = con.execute("SELECT COUNT(*) FROM tiles").fetchone()[0]
            log.info(
                "  Copying %d tiles into '_tiles_with_rowid' "
                "(ordered by zoom_level, tile_column, tile_row)…", total
            )

            con.execute("DROP TABLE IF EXISTS _tiles_with_rowid")
            con.execute("""
                CREATE TABLE _tiles_with_rowid (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    zoom_level  INTEGER NOT NULL,
                    tile_column INTEGER NOT NULL,
                    tile_row    INTEGER NOT NULL,
                    tile_data   BLOB
                )
            """)
            con.execute("""
                INSERT INTO _tiles_with_rowid
                    (zoom_level, tile_column, tile_row, tile_data)
                SELECT zoom_level, tile_column, tile_row, tile_data
                FROM tiles
                ORDER BY zoom_level, tile_column, tile_row
            """)
            con.commit()
            log.info("  Copy complete.")

            # Replace the original tiles object with a view over the new table
            if obj_type == "view":
                con.execute("DROP VIEW tiles")
            else:
                con.execute("DROP TABLE tiles")

            con.execute("""
                CREATE VIEW tiles AS
                    SELECT id          AS rowid,
                           zoom_level,
                           tile_column,
                           tile_row,
                           tile_data
                    FROM _tiles_with_rowid
            """)
            con.commit()
            log.info("  'tiles' view recreated over '_tiles_with_rowid'. Done.")

        finally:
            con.close()

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
                log.info("  Moved: %s/%s (%.1f KB)",
                         entry, bundle, os.path.getsize(dst)/1024)
