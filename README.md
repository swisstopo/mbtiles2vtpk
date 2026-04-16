# mbtiles2vtpk

Convert MBTiles vector tile packages to the ESRI VTPK format.

## Installation

```bash
# 1. Clone with submodules
git clone --recurse-submodules https://github.com/<you>/mbtiles2vtpk.git
cd mbtiles2vtpk

# If you already cloned without --recurse-submodules:
git submodule update --init --recursive

# 2. Install in editable mode (no extra PyPI deps needed)
pip install -e .
```

## Usage

```bash
mbtiles2vtpk ./data/countries.mbtiles countries.vtpk
mbtiles2vtpk ./data/countries.mbtiles countries.vtpk --work-dir C:\Temp\work
```

Or with Python directly (PyCharm / no install):

```
Run > Edit Configurations → Module name: mbtiles2vtpk.cli
Parameters: input.mbtiles output.vtpk
Working directory: <repo root>
```

## External dependency

Tile bundle creation is delegated to
[ltbam/python-mbtiles2compactcache](https://github.com/ltbam/python-mbtiles2compactcache),
included as a git submodule under `mbtiles2vtpk/vendor/`.

The script is called as:

```
python mbtiles2compactcache.py -ml <max_zoom> -s <source.mbtiles> -d <dest_dir>
```

## Conversion steps

| # | Class | Description |
|---|-------|-------------|
| 1 | `StructureCreator`  | Create VTPK folder skeleton |
| 2 | `TileExtractor`     | Extract tiles → Compact Cache V2 bundles (via submodule) |
| 3 | `TilemapEditor`     | Build presence quadtree → `p12/tilemap/root.json` |
| 4 | `StyleCopier`       | Extract / build Mapbox GL style |
| 5 | `RootJsonCreator`   | Write `p12/root.json`, `metadata.json`, `esriinfo/` |
| 6 | `TileSizeEditor`    | Patch tile size to 512 × 512 |
| 7 | `LodsEditor`        | Verify LODs match extracted zoom levels |
| 8 | `FontResolver`      | Embed fonts, patch glyphs URL, write resource info |
| 9 | `Repacker`          | ZIP everything into a `.vtpk` archive |
