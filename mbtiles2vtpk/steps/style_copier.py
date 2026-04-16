"""
Step 4 – Copy style resources into the VTPK structure.
"""

import json
import os
import sqlite3

from .base_step import BaseStep
from ..logger import get_logger

log = get_logger("StyleCopier")

DEFAULT_STYLE = {
    "version": 8,
    "name": "default",
    "sources": {
        "esri": {
            "type": "vector",
            "url": "."
        }
    },
    "layers": []
}


class StyleCopier(BaseStep):
    """
    Extracts the style JSON from the MBTiles metadata (key 'style' or 'json')
    and writes it to p12/resources/styles/root.json.
    Falls back to a minimal default style if none is embedded.
    """

    def __init__(self, mbtiles_path: str, work_dir: str):
        self.mbtiles_path = mbtiles_path
        self.work_dir = work_dir

    def run(self) -> None:
        log.info("Looking for embedded style in MBTiles metadata…")
        style = self._extract_style()

        styles_dir = os.path.join(self.work_dir, "p12", "resources", "styles")
        out_path = os.path.join(styles_dir, "root.json")

        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump(style, fh, indent=2)
        log.info("Style written to: %s", out_path)

    # ------------------------------------------------------------------

    def _extract_style(self) -> dict:
        con = sqlite3.connect(self.mbtiles_path)
        try:
            cur = con.execute("SELECT name, value FROM metadata")
            meta = dict(cur.fetchall())
        finally:
            con.close()

        # Some tilesets embed a full Mapbox GL style under 'style'
        if "style" in meta:
            log.info("  Found embedded 'style' key in metadata.")
            return json.loads(meta["style"])

        # Others store vector_layers info under 'json' – build a minimal style
        if "json" in meta:
            log.info("  No full style found; building minimal style from 'json' metadata.")
            layers_meta = json.loads(meta["json"]).get("vector_layers", [])
            style = dict(DEFAULT_STYLE)
            style["name"] = meta.get("name", "unnamed")
            style["layers"] = [
                {
                    "id": layer["id"],
                    "type": "fill",
                    "source": "esri",
                    "source-layer": layer["id"],
                    "paint": {}
                }
                for layer in layers_meta
            ]
            log.info("  Built minimal style with %d layer(s).", len(style["layers"]))
            return style

        log.warning("  No style information found; using empty default style.")
        return DEFAULT_STYLE
