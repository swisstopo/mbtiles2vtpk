"""
Step 5 – Create p12/root.json + p12/metadata.json + esriinfo files.
"""

import json
import math
import os
import sqlite3

from .base_step import BaseStep
from ..logger import get_logger

log = get_logger("RootJsonCreator")

SPATIAL_REFERENCE = {"wkid": 102100, "latestWkid": 3857}
ORIGIN = {"x": -20037508.3427870013, "y": 20037508.3427870013}

DEFAULT_EXTENT = {
    "xmin": -20037508.3427892,
    "ymin": -20037508.3427892,
    "xmax": 20037508.3427892,
    "ymax": 20037508.3427892,
    "spatialReference": SPATIAL_REFERENCE,
}

# LODs for 512×512 tiles — level 0 = resolution 78271 (one step above 256px level 0)
# Justification: 512px tiles = 2× the size of 256px tiles → same data, one zoom level "earlier"
WM_RESOLUTIONS = [
    78271.5169639999949, 39135.7584819999465, 19567.87924100005,
    9783.93962049995025, 4891.96981024997967, 2445.98490512498984,
    1222.99245256249492, 611.496226281244958, 305.748113140690009,
    152.874056570279009, 76.4370282852055, 38.2185141425365984,
    19.1092570712682992, 9.5546285356341496, 4.7773142678170748,
    2.3886571339746849, 1.19432856698734, 0.59716428342752503,
    0.29858214177990849,
]
WM_SCALES = [
    295828763.7957775, 147914381.897888511, 73957190.9489444941,
    36978595.4744720012, 18489297.7372360006, 9244648.8686180003,
    4622324.43430900015, 2311162.21715450007, 1155581.1085775001,
    577790.554288499989, 288895.2771445, 144447.638572,
    72223.8192859999981, 36111.9096429999991, 18055.9548215,
    9027.97741099999985, 4513.98870549999992, 2256.99435249999988,
    1128.4971765,
]

# Meters per degree at equator for WGS84 → used to convert lon/lat bbox to 3857
_DEG2RAD = math.pi / 180.0
_EARTH_R  = 6378137.0


def _lonlat_to_3857(lon: float, lat: float):
    x = lon * _DEG2RAD * _EARTH_R
    y = math.log(math.tan(math.pi / 4 + lat * _DEG2RAD / 2)) * _EARTH_R
    return x, y


def _parse_mbtiles_bounds(bounds_str: str) -> dict | None:
    """
    Parse the MBTiles 'bounds' metadata value (lon_min,lat_min,lon_max,lat_max)
    and return an Esri extent dict in EPSG:3857.
    """
    try:
        parts = [float(v.strip()) for v in bounds_str.split(",")]
        if len(parts) != 4:
            return None
        lon_min, lat_min, lon_max, lat_max = parts
        # Clamp latitude to avoid infinity at poles
        lat_min = max(lat_min, -85.0511)
        lat_max = min(lat_max, 85.0511)
        xmin, ymin = _lonlat_to_3857(lon_min, lat_min)
        xmax, ymax = _lonlat_to_3857(lon_max, lat_max)
        return {
            "xmin": xmin, "ymin": ymin,
            "xmax": xmax, "ymax": ymax,
            "spatialReference": SPATIAL_REFERENCE,
        }
    except Exception:
        return None


class RootJsonCreator(BaseStep):
    """
    Generates:
      - p12/root.json          (tile service descriptor with initialExtent / fullExtent)
      - p12/metadata.json      (vector layer list)
      - esriinfo/iteminfo.xml  (package metadata)
      - esriinfo/item.pkinfo   (package info stub)
    """

    def __init__(self, mbtiles_path: str, work_dir: str):
        self.mbtiles_path = mbtiles_path
        self.work_dir = work_dir

    def run(self) -> None:
        log.info("Reading MBTiles metadata…")
        meta = self._read_metadata()
        vector_layers = self._read_vector_layers()

        name        = meta.get("name", "Unnamed")
        description = meta.get("description", "")
        attribution = meta.get("attribution", "")
        min_zoom    = int(meta.get("minzoom", 0))
        max_zoom    = int(meta.get("maxzoom", len(WM_RESOLUTIONS) - 1))
        max_zoom    = min(max_zoom, len(WM_RESOLUTIONS) - 1)

        log.info("  name=%s  minzoom=%d  maxzoom=%d", name, min_zoom, max_zoom)

        # --- Extent ---
        extent = None
        if "bounds" in meta:
            extent = _parse_mbtiles_bounds(meta["bounds"])
            if extent:
                log.info(
                    "  Extent from MBTiles bounds: xmin=%.0f ymin=%.0f xmax=%.0f ymax=%.0f",
                    extent["xmin"], extent["ymin"], extent["xmax"], extent["ymax"],
                )
            else:
                log.warning("  Could not parse MBTiles 'bounds' value: %s", meta["bounds"])

        if extent is None:
            extent = DEFAULT_EXTENT
            log.info("  Using default full-world extent.")

        # --- LODs ---
        lods = [
            {"level": z, "resolution": WM_RESOLUTIONS[z], "scale": WM_SCALES[z]}
            for z in range(min_zoom, max_zoom + 1)
        ]
        log.info("  LODs: %d levels (%d → %d)", len(lods), min_zoom, max_zoom)

        # --- p12/root.json ---
        root = {
            "currentVersion": 11.5,
            "name": name,
            "copyrightText": attribution,
            "type": "indexedVector",
            "exportTilesAllowed": False,
            "minScale": WM_SCALES[min_zoom],
            "maxScale": WM_SCALES[max_zoom],
            "initialExtent": extent,
            "fullExtent": extent,
            "tileInfo": {
                "rows": 512,
                "cols": 512,
                "dpi": 96,
                "format": "pbf",
                "origin": ORIGIN,
                "spatialReference": SPATIAL_REFERENCE,
                "lods": lods,
            },
            "maxzoom": max_zoom,
            "minLOD": min_zoom,
            "maxLOD": max_zoom,
            "resourceInfo": {
                "styleVersion": 8,
                "tileCompression": "gzip",
                "cacheInfo": {
                    "storageInfo": {
                        "packetSize": 128,
                        "storageFormat": "compactV2",
                    }
                },
            },
            "capabilities": "TilesOnly",
            "defaultStyles": "resources/styles",
        }
        root_path = os.path.join(self.work_dir, "p12", "root.json")
        with open(root_path, "w", encoding="utf-8") as fh:
            json.dump(root, fh)
        log.info("p12/root.json written (initialExtent + fullExtent included).")

        # --- p12/metadata.json ---
        meta_path = os.path.join(self.work_dir, "p12", "metadata.json")
        with open(meta_path, "w", encoding="utf-8") as fh:
            json.dump({"vector_layers": vector_layers}, fh)
        log.info("p12/metadata.json written (%d layers).", len(vector_layers))

        # --- esriinfo ---
        self._write_iteminfo_xml(name, description, attribution, min_zoom, max_zoom, extent)
        self._write_pkinfo(name)

    # ------------------------------------------------------------------

    def _read_metadata(self) -> dict:
        con = sqlite3.connect(self.mbtiles_path)
        try:
            cur = con.execute("SELECT name, value FROM metadata")
            return dict(cur.fetchall())
        finally:
            con.close()

    def _read_vector_layers(self) -> list:
        con = sqlite3.connect(self.mbtiles_path)
        try:
            cur = con.execute("SELECT value FROM metadata WHERE name='json'")
            row = cur.fetchone()
            if row:
                import json as _json
                return _json.loads(row[0]).get("vector_layers", [])
            return []
        finally:
            con.close()

    def _write_iteminfo_xml(self, name, description, attribution, min_zoom, max_zoom, extent):
        import uuid
        # Convert 3857 extent to WGS84 for the XML
        def x_to_lon(x): return x / _EARTH_R / _DEG2RAD
        def y_to_lat(y): return (2 * math.atan(math.exp(y / _EARTH_R)) - math.pi / 2) / _DEG2RAD

        xmin_deg = x_to_lon(extent["xmin"])
        ymin_deg = y_to_lat(extent["ymin"])
        xmax_deg = x_to_lon(extent["xmax"])
        ymax_deg = y_to_lat(extent["ymax"])

        xml = f"""<?xml version="1.0" encoding="utf-8" ?>
<ESRI_ItemInformation Culture='en-US'>
<n>{name}</n>
<guid>{str(uuid.uuid4()).upper()}</guid>
<version>1.0</version>
<created></created>
<modified></modified>
<catalogpath></catalogpath>
<snippet></snippet>
<description>{description}</description>
<summary></summary>
<title>{name}</title>
<tags>Data,Vector Tile Package,vtpk</tags>
<type>Vector Tile Package</type>
<typekeywords>
<typekeyword>Data</typekeyword>
<typekeyword>Vector Tile Package</typekeyword>
<typekeyword>vtpk</typekeyword>
</typekeywords>
<thumbnail></thumbnail>
<documentation></documentation>
<url></url>
<extent>
<xmin>{xmin_deg:.10f}</xmin>
<ymin>{ymin_deg:.10f}</ymin>
<xmax>{xmax_deg:.10f}</xmax>
<ymax>{ymax_deg:.10f}</ymax>
</extent>
<spatialreference>WGS_1984_Web_Mercator_Auxiliary_Sphere</spatialreference>
<minScale>{WM_SCALES[min_zoom]}</minScale>
<maxScale>{WM_SCALES[max_zoom]}</maxScale>
<datalastModifiedTime></datalastModifiedTime>
<accessinformation>{attribution}</accessinformation>
<licenseinfo></licenseinfo>
</ESRI_ItemInformation>
"""
        out = os.path.join(self.work_dir, "esriinfo", "iteminfo.xml")
        with open(out, "w", encoding="utf-8") as fh:
            fh.write(xml)
        log.info("esriinfo/iteminfo.xml written (extent in WGS84).")

    def _write_pkinfo(self, name: str):
        import json as _json
        pkinfo = {"name": name, "type": "Vector Tile Package"}
        out = os.path.join(self.work_dir, "esriinfo", "item.pkinfo")
        with open(out, "w", encoding="utf-8") as fh:
            _json.dump(pkinfo, fh)
        log.info("esriinfo/item.pkinfo written.")
