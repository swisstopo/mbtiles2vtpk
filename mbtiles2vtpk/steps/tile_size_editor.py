"""
Step 6 – Patch tile size in p12/root.json.
"""

import json
import os

from .base_step import BaseStep
from ..logger import get_logger

log = get_logger("TileSizeEditor")

VTPK_TILE_SIZE = 512


class TileSizeEditor(BaseStep):
    """Ensures tileInfo rows/cols = 512 in p12/root.json."""

    def __init__(self, work_dir: str):
        self.work_dir = work_dir

    def run(self) -> None:
        root_path = os.path.join(self.work_dir, "p12", "root.json")
        log.info("Patching tile size in: %s", root_path)

        with open(root_path, "r", encoding="utf-8") as fh:
            root = json.load(fh)

        old_rows = root.get("tileInfo", {}).get("rows")
        old_cols = root.get("tileInfo", {}).get("cols")
        root.setdefault("tileInfo", {})["rows"] = VTPK_TILE_SIZE
        root["tileInfo"]["cols"] = VTPK_TILE_SIZE

        log.info("  rows: %s → %d   cols: %s → %d", old_rows, VTPK_TILE_SIZE, old_cols, VTPK_TILE_SIZE)

        with open(root_path, "w", encoding="utf-8") as fh:
            json.dump(root, fh)
        log.info("Tile size patched.")
