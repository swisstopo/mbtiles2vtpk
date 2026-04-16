"""
Step 8 – Resolve fonts and generate p12/resources/info/root.json.
"""

import json
import os
import sqlite3

from .base_step import BaseStep
from ..logger import get_logger

log = get_logger("FontResolver")


class FontResolver(BaseStep):
    """
    - Extracts embedded fonts from MBTiles metadata if present.
    - Patches remote glyphs URL in style to local path.
    - Generates p12/resources/info/root.json listing all font PBF resources.
    """

    def __init__(self, mbtiles_path: str, work_dir: str):
        self.mbtiles_path = mbtiles_path
        self.work_dir = work_dir

    def run(self) -> None:
        log.info("Resolving fonts…")
        meta = self._read_metadata()
        fonts_dir = os.path.join(self.work_dir, "p12", "resources", "fonts")

        if "fonts" in meta:
            self._extract_embedded_fonts(meta["fonts"], fonts_dir)
        else:
            log.info("  No embedded fonts in MBTiles metadata.")

        self._patch_style_glyphs()
        self._write_resource_info()

    # ------------------------------------------------------------------

    def _read_metadata(self) -> dict:
        con = sqlite3.connect(self.mbtiles_path)
        try:
            cur = con.execute("SELECT name, value FROM metadata")
            return dict(cur.fetchall())
        finally:
            con.close()

    def _extract_embedded_fonts(self, fonts_json: str, fonts_dir: str) -> None:
        import base64
        fonts = json.loads(fonts_json)
        log.info("  Extracting %d embedded font range(s)…", len(fonts))
        for entry in fonts:
            font_name = entry["name"]
            glyph_range = entry["range"]
            data = base64.b64decode(entry["data"])
            out_dir = os.path.join(fonts_dir, font_name)
            os.makedirs(out_dir, exist_ok=True)
            out_path = os.path.join(out_dir, f"{glyph_range}.pbf")
            with open(out_path, "wb") as fh:
                fh.write(data)
            log.info("    Written: fonts/%s/%s.pbf", font_name, glyph_range)

    def _patch_style_glyphs(self) -> None:
        style_path = os.path.join(
            self.work_dir, "p12", "resources", "styles", "root.json"
        )
        if not os.path.exists(style_path):
            log.warning("  Style file not found, skipping glyphs URL patch.")
            return

        with open(style_path, "r", encoding="utf-8") as fh:
            style = json.load(fh)

        current_glyphs = style.get("glyphs", "")
        if not current_glyphs:
            log.info("  No glyphs URL in style – nothing to patch.")
            return

        if current_glyphs.startswith("http"):
            log.warning("  Remote glyphs URL detected. Patching to local path.")
            style["glyphs"] = "../fonts/{fontstack}/{range}.pbf"
            with open(style_path, "w", encoding="utf-8") as fh:
                json.dump(style, fh, indent=2)
            log.info("  Glyphs URL patched.")
        else:
            log.info("  Glyphs URL already local: %s", current_glyphs)

    def _write_resource_info(self) -> None:
        """Generate p12/resources/info/root.json listing all font PBF paths."""
        fonts_dir = os.path.join(self.work_dir, "p12", "resources", "fonts")
        resource_list = []

        if os.path.isdir(fonts_dir):
            for font_name in sorted(os.listdir(fonts_dir)):
                font_path = os.path.join(fonts_dir, font_name)
                if not os.path.isdir(font_path):
                    continue
                for pbf_file in sorted(os.listdir(font_path)):
                    if pbf_file.endswith(".pbf"):
                        resource_list.append(f"../fonts/{font_name}/{pbf_file}")

        out_path = os.path.join(self.work_dir, "p12", "resources", "info", "root.json")
        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump({"resourceInfo": resource_list}, fh)
        log.info("  resources/info/root.json written (%d font ranges listed).", len(resource_list))
