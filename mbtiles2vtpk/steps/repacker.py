"""
Step 9 – Repack the working directory into a .vtpk archive.

A VTPK file is a ZIP archive (renamed .vtpk).
Convention:
  - JSON / text files  → deflate compression
  - .bundle files      → store (no compression, already binary)
"""

import os
import zipfile

from .base_step import BaseStep
from ..logger import get_logger

log = get_logger("Repacker")


class Repacker(BaseStep):
    """
    Walks work_dir and packs every file into a ZIP-based .vtpk archive
    at output_path.
    """

    def __init__(self, work_dir: str, output_path: str):
        self.work_dir = work_dir
        self.output_path = output_path

    def run(self) -> None:
        log.info("Repacking '%s' → '%s'", self.work_dir, self.output_path)

        out_dir = os.path.dirname(self.output_path)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)

        total_files = 0
        total_bytes = 0

        with zipfile.ZipFile(self.output_path, "w", allowZip64=True) as zf:
            for dirpath, _dirnames, filenames in os.walk(self.work_dir):
                for filename in filenames:
                    abs_path = os.path.join(dirpath, filename)
                    # Arc name: path relative to work_dir
                    arc_name = os.path.relpath(abs_path, self.work_dir)

                    # Use STORE for bundle files, DEFLATE for everything else
                    if filename.endswith(".bundle"):
                        compress = zipfile.ZIP_STORED
                    else:
                        compress = zipfile.ZIP_DEFLATED

                    zf.write(abs_path, arc_name, compress_type=compress)
                    size = os.path.getsize(abs_path)
                    total_files += 1
                    total_bytes += size
                    log.info(
                        "  Added: %-55s  %8.1f KB  [%s]",
                        arc_name,
                        size / 1024,
                        "STORE" if compress == zipfile.ZIP_STORED else "DEFLATE",
                    )

        vtpk_size = os.path.getsize(self.output_path)
        log.info(
            "Done. %d file(s) packed, source %.1f MB → vtpk %.1f MB",
            total_files,
            total_bytes / 1_048_576,
            vtpk_size / 1_048_576,
        )
