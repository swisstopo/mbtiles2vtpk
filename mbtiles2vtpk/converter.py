"""
Main orchestrator for the mbtiles -> vtpk conversion pipeline.
"""

import os
import shutil
import tempfile

from .steps.structure_creator import StructureCreator
from .steps.tile_extractor import TileExtractor
from .steps.tilemap_editor import TilemapEditor
from .steps.style_copier import StyleCopier
from .steps.root_json_creator import RootJsonCreator
from .steps.tile_size_editor import TileSizeEditor
from .steps.lods_editor import LodsEditor
from .steps.font_resolver import FontResolver
from .steps.repacker import Repacker
from .logger import get_logger

log = get_logger("Converter")


class MBTiles2VTPKConverter:
    """
    Orchestrates the full conversion pipeline from an MBTiles file to a VTPK package.
    """

    def __init__(self, mbtiles_path: str, output_path: str,
                 work_dir: str = None, style_source: str = None):
        """
        :param mbtiles_path: Path to the source .mbtiles file.
        :param output_path:  Path where the output .vtpk file will be written.
        :param style_source: Optional URL or path to a Mapbox GL style JSON.
        :param work_dir:     Optional working directory for intermediate files.
                             A temp directory is created (and cleaned up) if None.
        """
        self.mbtiles_path = mbtiles_path
        self.output_path = output_path
        self._provided_work_dir = work_dir
        self.style_source = style_source
        self.work_dir = None          # resolved in convert()

    def convert(self) -> None:
        """Run all conversion steps in order."""
        _cleanup = False
        if self._provided_work_dir:
            self.work_dir = self._provided_work_dir
        else:
            self.work_dir = tempfile.mkdtemp(prefix="mbtiles2vtpk_")
            _cleanup = True
            log.info("Using temp work dir: %s", self.work_dir)

        try:
            steps = [
                ("Step 1/9 – Create structure",       self._create_structure),
                ("Step 2/9 – Extract tiles",           self._extract_tiles),
                ("Step 3/9 – Edit tilemap",            self._edit_tilemap),
                ("Step 4/9 – Copy styles",             self._copy_styles),
                ("Step 5/9 – Create root.json",        self._create_root_json),
                ("Step 6/9 – Edit tile size",          self._edit_tile_size),
                ("Step 7/9 – Edit LODs",               self._edit_lods),
                ("Step 8/9 – Resolve fonts",           self._resolve_fonts),
                ("Step 9/9 – Repack to VTPK",          self._repack),
            ]
            for label, fn in steps:
                log.info("━━━ %s ━━━", label)
                fn()

            log.info("✓ Conversion complete → %s", self.output_path)
        finally:
            if _cleanup and os.path.isdir(self.work_dir):
                shutil.rmtree(self.work_dir)
                log.info("Temp work dir removed.")

    def _create_structure(self) -> None:
        StructureCreator(self.work_dir).run()

    def _extract_tiles(self) -> None:
        TileExtractor(self.mbtiles_path, self.work_dir).run()

    def _edit_tilemap(self) -> None:
        TilemapEditor(self.work_dir).run()

    def _copy_styles(self) -> None:
        StyleCopier(self.mbtiles_path, self.work_dir, self.style_source).run()

    def _create_root_json(self) -> None:
        RootJsonCreator(self.mbtiles_path, self.work_dir).run()

    def _edit_tile_size(self) -> None:
        TileSizeEditor(self.work_dir).run()

    def _edit_lods(self) -> None:
        LodsEditor(self.work_dir).run()

    def _resolve_fonts(self) -> None:
        FontResolver(self.mbtiles_path, self.work_dir).run()

    def _repack(self) -> None:
        Repacker(self.work_dir, self.output_path).run()
