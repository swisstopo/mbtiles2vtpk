"""
Step 1 – Create the VTPK folder structure matching the reference format.
"""

import os
from .base_step import BaseStep
from ..logger import get_logger

log = get_logger("StructureCreator")

VTPK_DIRS = [
    "esriinfo",
    os.path.join("p12", "tile"),
    os.path.join("p12", "tilemap"),
    os.path.join("p12", "resources", "fonts"),
    os.path.join("p12", "resources", "info"),
    os.path.join("p12", "resources", "sprites"),
    os.path.join("p12", "resources", "styles"),
]


class StructureCreator(BaseStep):
    """
    Creates the expected directory layout for a VTPK package inside work_dir.

    Output structure (matches reference VTPK):
        <work_dir>/
            esriinfo/
            p12/
                tile/
                tilemap/
                resources/
                    fonts/
                    info/
                    sprites/
                    styles/
    """

    def __init__(self, work_dir: str):
        self.work_dir = work_dir

    def run(self) -> None:
        log.info("Creating VTPK folder structure in: %s", self.work_dir)
        for rel_path in VTPK_DIRS:
            full_path = os.path.join(self.work_dir, rel_path)
            os.makedirs(full_path, exist_ok=True)
            log.info("  Created: %s", rel_path)
        log.info("Folder structure ready.")
