"""
Step 7 – Verify LODs in root.json against tile directories.
"""

import json
import os

from .base_step import BaseStep
from ..logger import get_logger

log = get_logger("LodsEditor")


class LodsEditor(BaseStep):
    """
    Cross-checks the LOD entries in p12/root.json against the p12/tile/
    directories actually present on disk.
    """

    def __init__(self, work_dir: str):
        self.work_dir = work_dir

    def run(self) -> None:
        root_path = os.path.join(self.work_dir, "p12", "root.json")
        tile_dir = os.path.join(self.work_dir, "p12", "tile")

        log.info("Verifying LODs against extracted bundles…")

        disk_zooms = set()
        if os.path.isdir(tile_dir):
            for entry in os.listdir(tile_dir):
                if entry.startswith("L") and os.path.isdir(os.path.join(tile_dir, entry)):
                    disk_zooms.add(int(entry[1:]))

        log.info("  Zoom levels on disk: %s", sorted(disk_zooms))

        with open(root_path, "r", encoding="utf-8") as fh:
            root = json.load(fh)

        current_lods = root.get("tileInfo", {}).get("lods", [])
        current_zooms = {l["level"] for l in current_lods}

        added   = disk_zooms - current_zooms
        removed = current_zooms - disk_zooms

        if not added and not removed:
            log.info("  LODs are consistent with disk. No changes needed.")
            return

        if added:
            log.warning("  Zoom levels on disk but missing from LODs: %s – ignored.", sorted(added))
        if removed:
            log.info("  Removing LOD entries with no tiles on disk: %s", sorted(removed))
            root["tileInfo"]["lods"] = [
                l for l in current_lods if l["level"] in disk_zooms
            ]
            with open(root_path, "w", encoding="utf-8") as fh:
                json.dump(root, fh)

        log.info("LODs verified.")
