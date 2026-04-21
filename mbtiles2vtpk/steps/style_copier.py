"""
Step 4 – Copy / build / download style resources into the VTPK structure.

If a --style URL or path is provided:
  1. Fetch the Mapbox GL style JSON
  2. Extract all referenced font names from layers (text-font property)
  3. Download font PBF glyphs (256 ranges × N fonts)
  4. Download sprite files (sprite.json/png + @2x variants)
  5. Patch glyphs/sprite/source URLs for VTPK layout
  6. Optionally sanitize the style for ArcGIS Pro compatibility
  7. Write everything to p12/resources/

If no style is provided:
  Build a minimal style from MBTiles metadata (existing behaviour).
"""

import json
import os
import sqlite3
import urllib.request
import urllib.error
from typing import List, Optional

from .base_step import BaseStep
from ..logger import get_logger
from ..cache import fetch as cache_fetch, fetch_optional, FetchError

log = get_logger("StyleCopier")

# All Unicode glyph ranges (256 codepoints each)
GLYPH_RANGES = [f"{i}-{i+255}" for i in range(0, 65536, 256)]


def _read_file(path: str) -> bytes:
    """Read a local file as bytes. Returns None on failure."""
    try:
        with open(path, "rb") as fh:
            return fh.read()
    except Exception as e:
        log.warning("    Failed to read %s: %s", path, e)
        return None


def _collect_font_names(expr, fonts: set) -> None:
    """
    Recursively collect font name strings from a text-font expression.

    Font names only appear as elements of a list-of-strings leaf, e.g.:
      ["Noto Sans Regular", "Noto Sans Italic"]

    They never appear as bare strings at the top level of a step/match/case
    expression — those positions hold input values like "lake_elevation".

    Strategy:
    - If expr is a plain list whose items are all strings → it IS a font array.
    - If expr is a GL expression (first element is an operator string) →
      recurse only into the output-value positions (skip operator and inputs).
    - ["literal", [...]] → unwrap and recurse into the inner list.
    """
    if not isinstance(expr, list) or not expr:
        return

    # Plain list of strings → font array
    if all(isinstance(item, str) for item in expr):
        fonts.update(expr)
        return

    op = expr[0] if isinstance(expr[0], str) else None

    if op == "literal" and len(expr) == 2:
        _collect_font_names(expr[1], fonts)
        return

    if op in ("step", "interpolate"):
        # ["step", input, default_output, threshold, output, ...]
        # ["interpolate", interp, input, stop, output, ...]
        # Outputs are at odd positions after the first 2-3 items; just recurse
        # into anything that is a list (skip strings which are inputs/operators).
        for item in expr[1:]:
            if isinstance(item, list):
                _collect_font_names(item, fonts)
        return

    if op == "match":
        # ["match", input, label, output, label, output, ..., default]
        # Labels (positions 2, 4, 6, …) can be strings or arrays of strings
        # (input values) — NOT font names.  Outputs (positions 3, 5, 7, …)
        # and the final default ARE font arrays.
        # Skip position 1 (input expr) and even-indexed labels.
        if len(expr) < 4:
            return
        # Outputs start at index 3, then every 2 steps; default is last item.
        i = 3
        while i < len(expr):
            _collect_font_names(expr[i], fonts)
            i += 2
        # If even number of remaining items the last is the default — already covered.
        return

    if op == "case":
        # ["case", cond, output, cond, output, ..., default]
        # Outputs at positions 2, 4, … and final default.
        i = 2
        while i < len(expr):
            _collect_font_names(expr[i], fonts)
            i += 2
        return

    if op == "coalesce":
        for item in expr[1:]:
            _collect_font_names(item, fonts)
        return

    # Any other expression: recurse into list children only
    for item in expr[1:]:
        if isinstance(item, list):
            _collect_font_names(item, fonts)



class StyleCopier(BaseStep):
    """
    Handles style resources for the VTPK.

    With --style:
      - Downloads/reads the Mapbox GL style
      - Downloads all referenced fonts and sprites
      - Patches URLs for VTPK local layout
      - Optionally sanitizes the style for ArcGIS Pro compatibility

    Without --style:
      - Builds a minimal style from MBTiles vector_layers metadata
    """

    def __init__(self, mbtiles_path: str, work_dir: str,
                 style_source: Optional[str] = None):
        """
        :param mbtiles_path:    Path to source .mbtiles file.
        :param work_dir:        Working directory (VTPK structure root).
        :param style_source:    Optional URL or local path to a Mapbox GL style JSON.
        """
        self.mbtiles_path = mbtiles_path
        self.work_dir = work_dir
        self.style_source = style_source

    # ------------------------------------------------------------------

    def run(self) -> None:
        styles_dir  = os.path.join(self.work_dir, "p12", "resources", "styles")
        fonts_dir   = os.path.join(self.work_dir, "p12", "resources", "fonts")
        sprites_dir = os.path.join(self.work_dir, "p12", "resources", "sprites")

        if self.style_source:
            log.info("External style provided: %s", self.style_source)
            style = self._load_external_style()
            if style:
                fonts  = self._extract_fonts(style)
                sprite = style.get("sprite", "")
                self._download_fonts(fonts, style.get("glyphs", ""), fonts_dir)
                self._download_sprites(sprite, sprites_dir)
                style  = self._patch_style(style)
                self._write_style(style, styles_dir)
                return

            log.warning("Could not load external style — falling back to minimal style.")

        # Fallback: build minimal style from MBTiles metadata
        log.info("Building minimal style from MBTiles metadata.")
        meta  = self._read_metadata()
        style = self._build_minimal_style(meta)
        self._write_style(style, styles_dir)

    # ------------------------------------------------------------------
    # External style loading
    # ------------------------------------------------------------------

    def _load_external_style(self) -> Optional[dict]:
        src = self.style_source
        if src.startswith("http://") or src.startswith("https://"):
            log.info("  Fetching style from URL (cache then network)…")
            data = cache_fetch(src, category="styles")
            raw  = data.decode("utf-8")
        else:
            log.info("  Reading style from local file…")
            data = _read_file(src)
            if data is None:
                raise FileNotFoundError(f"Style file not found: {src}")
            raw  = data.decode("utf-8")

        if raw is None:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError as e:
            log.error("  Style JSON parse error: %s", e)
            return None

    # ------------------------------------------------------------------
    # Font downloading
    # ------------------------------------------------------------------

    def _extract_fonts(self, style: dict) -> List[str]:
        """Return unique font names referenced in style layers.

        text-font can be:
          - ["Font Name 1", "Font Name 2"]            direct literal list
          - ["literal", ["Font Name 1", "Font Name 2"]]
          - ["step", ...] / ["match", ...] / ["case", ...]
            where the OUTPUT values are font arrays (list-of-strings)

        We only collect strings from font-array positions (list-of-strings
        leaves), never from match-input or condition strings such as class
        values like "lake_elevation".
        """
        fonts = set()
        for layer in style.get("layers", []):
            layout = layer.get("layout", {})
            tf = layout.get("text-font")
            if tf is not None:
                _collect_font_names(tf, fonts)
        if fonts:
            log.info("  Fonts referenced in style: %s", sorted(fonts))
        else:
            log.info("  No fonts found in style layers.")
        return sorted(fonts)

    def _download_fonts(self, fonts: List[str], glyphs_url_template: str, fonts_dir: str) -> None:
        """
        Download PBF glyph files for every font × every Unicode range.
        glyphs_url_template uses {fontstack} and {range} placeholders.
        """
        if not fonts:
            log.info("  No fonts to download.")
            return

        if not glyphs_url_template or not glyphs_url_template.startswith("http"):
            log.warning("  Glyphs URL is not a downloadable HTTP URL: %s", glyphs_url_template)
            log.warning("  Fonts will not be embedded — labels may not render in ArcGIS Pro.")
            return

        total_ranges = len(GLYPH_RANGES)
        log.info("  Downloading %d font(s) × %d glyph ranges…", len(fonts), total_ranges)

        for font in fonts:
            font_dir = os.path.join(fonts_dir, font)
            os.makedirs(font_dir, exist_ok=True)
            downloaded = cached = 0
            for grange in GLYPH_RANGES:
                url = (glyphs_url_template
                       .replace("{fontstack}", urllib.request.quote(font))
                       .replace("{range}", grange))
                from ..cache import _cache_path, _ext
                cp = _cache_path("fonts", url, ".pbf")
                was_cached = os.path.exists(cp)
                data = cache_fetch(url, category="fonts")
                if len(data) > 0:
                    out_path = os.path.join(font_dir, f"{grange}.pbf")
                    with open(out_path, "wb") as fh:
                        fh.write(data)
                    if was_cached: cached += 1
                    else:          downloaded += 1

            log.info("    %s: %d from cache, %d downloaded.", font, cached, downloaded)

    # ------------------------------------------------------------------
    # Sprite downloading
    # ------------------------------------------------------------------

    def _download_sprites(self, sprite_url: str, sprites_dir: str) -> None:
        """
        Download sprite.json/png + @2x variants from the sprite base URL.
        sprite_url may be "mapbox://..." or "https://..." or a local path.
        """
        if not sprite_url:
            log.info("  No sprite URL in style.")
            return

        # Resolve mapbox:// scheme to CDN URL
        if sprite_url.startswith("mapbox://sprites/"):
            parts  = sprite_url.replace("mapbox://sprites/", "")
            sprite_url = f"https://api.mapbox.com/styles/v1/{parts}/sprite"
            log.info("  Resolved mapbox sprite URL: %s", sprite_url)
        elif not sprite_url.startswith("http"):
            log.info("  Sprite URL is not downloadable: %s", sprite_url)
            return

        os.makedirs(sprites_dir, exist_ok=True)
        # (filename, url, optional)
        files = [
            ("sprite.json",     sprite_url + ".json",    False),  # required
            ("sprite.png",      sprite_url + ".png",     False),  # required
            ("sprite@2x.json",  sprite_url + "@2x.json", True),   # optional
            ("sprite@2x.png",   sprite_url + "@2x.png",  True),   # optional
        ]
        from ..cache import _cache_path
        for fname, url, optional in files:
            cp = _cache_path("sprites", url, ".png" if fname.endswith(".png") else ".json")
            was_cached = os.path.exists(cp)
            fetcher = fetch_optional if optional else cache_fetch
            data = fetcher(url, category="sprites")
            if data:
                out = os.path.join(sprites_dir, fname)
                with open(out, "wb") as fh:
                    fh.write(data)
                source = "cache" if was_cached else "network"
                log.info("    %s: %s (%d bytes)", fname, source, len(data))
            elif not optional:
                raise FetchError(f"Required sprite file could not be downloaded: {url}")
            else:
                log.info("    %s: not available (optional)", fname)

    # ------------------------------------------------------------------
    # Style patching
    # ------------------------------------------------------------------

    def _patch_style(self, style: dict) -> dict:
        """Rewrite glyphs/sprite/source URLs to VTPK-relative paths."""
        meta = self._read_metadata()
        min_zoom = int(meta.get("minzoom", 0))
        max_zoom = int(meta.get("maxzoom", 18))
        attribution = meta.get("attribution", "")
        bounds_wgs84 = None
        if "bounds" in meta:
            try:
                parts = [float(v.strip()) for v in meta["bounds"].split(",")]
                if len(parts) == 4:
                    bounds_wgs84 = parts
            except Exception:
                pass

        # Patch sources
        for src in style.get("sources", {}).values():
            if src.get("type") == "vector":
                src["url"]    = "../../"
                src["scheme"] = src.get("scheme", "xyz")
                src.setdefault("minzoom", min_zoom)
                src.setdefault("maxzoom", max_zoom)
                if attribution and "attribution" not in src:
                    src["attribution"] = attribution
                if bounds_wgs84 and "bounds" not in src:
                    src["bounds"] = bounds_wgs84

        # Patch glyphs
        if style.get("glyphs", "").startswith("http") or style.get("glyphs", "").startswith("mapbox://"):
            style["glyphs"] = "../fonts/{fontstack}/{range}.pbf"
            log.info("  Glyphs URL patched to local path.")

        # Patch sprite
        if style.get("sprite", "").startswith("http") or style.get("sprite", "").startswith("mapbox://"):
            style["sprite"] = "../sprites/sprite"
            log.info("  Sprite URL patched to local path.")

        return style

    # ------------------------------------------------------------------
    # Minimal style builder (no external style)
    # ------------------------------------------------------------------

    def _read_metadata(self) -> dict:
        con = sqlite3.connect(self.mbtiles_path)
        try:
            return dict(con.execute("SELECT name, value FROM metadata").fetchall())
        finally:
            con.close()

    def _build_minimal_style(self, meta: dict) -> dict:
        name        = meta.get("name", "unnamed")
        min_zoom    = int(meta.get("minzoom", 0))
        max_zoom    = int(meta.get("maxzoom", 18))
        attribution = meta.get("attribution", "")

        bounds_wgs84 = None
        if "bounds" in meta:
            try:
                parts = [float(v.strip()) for v in meta["bounds"].split(",")]
                if len(parts) == 4:
                    bounds_wgs84 = parts
            except Exception:
                pass

        layers_meta = []
        if "json" in meta:
            layers_meta = json.loads(meta["json"]).get("vector_layers", [])

        source = {
            "type":   "vector",
            "url":    "../../",
            "scheme": "xyz",
            "minzoom": min_zoom,
            "maxzoom": max_zoom,
        }
        if attribution:
            source["attribution"] = attribution
        if bounds_wgs84:
            source["bounds"] = bounds_wgs84

        gl_layers = [self._make_layer(l) for l in layers_meta]
        log.info("  Built minimal style with %d layer(s).", len(gl_layers))

        return {
            "version": 8,
            "name": name,
            "glyphs":  "../fonts/{fontstack}/{range}.pbf",
            "sprite":  "../sprites/sprite",
            "sources": {"esri": source},
            "layers":  gl_layers,
        }

    def _make_layer(self, layer_meta: dict) -> dict:
        layer_id = layer_meta["id"]
        fields   = layer_meta.get("fields", {})
        lid      = layer_id.lower()

        POINT_WORDS = ("name", "label", "point", "place", "city", "town", "capital")
        LINE_WORDS  = ("line", "border", "road", "rail", "river", "coast", "contour")

        if any(w in lid for w in POINT_WORDS):
            gl_type = "symbol"
            paint   = {}
            layout  = {"text-field": "{" + next(iter(fields), "_name") + "}"} if fields else {}
        elif any(w in lid for w in LINE_WORDS):
            gl_type = "line"
            paint   = {"line-color": "#888888", "line-width": 1}
            layout  = {}
        else:
            gl_type = "fill"
            paint   = {"fill-color": "#cccccc", "fill-opacity": 0.5}
            layout  = {}

        layer_def = {
            "id":           layer_id,
            "type":         gl_type,
            "source":       "esri",
            "source-layer": layer_id,
            "paint":        paint,
        }
        if layout:
            layer_def["layout"] = layout
        return layer_def

    def _write_style(self, style: dict, styles_dir: str) -> None:
        out = os.path.join(styles_dir, "root.json")
        with open(out, "w", encoding="utf-8") as fh:
            json.dump(style, fh, indent=2)
        log.info("Style written to: %s", out)
