# mbtiles2vtpk

Convert MBTiles vector tile packages to the **ESRI VTPK** format.  
Tested with ArcGIS Pro and QGIS.

---

## Installation

```bash
# 1. Clone with submodules
git clone --recurse-submodules https://github.com/<you>/mbtiles2vtpk.git
cd mbtiles2vtpk

# If you already cloned without --recurse-submodules:
git submodule update --init --recursive

# 2. Install (editable mode)
pip install -e .
```

Requires **joblib** (dependency of the bundled submodule):

```bash
pip install joblib
```

---

## Usage

### Basic conversion

```bash
mbtiles2vtpk -i input.mbtiles -o output.vtpk
```

### With a custom Mapbox GL style

Provide a URL or a local path to a Mapbox GL style JSON.
Fonts (PBF glyphs) and sprites are downloaded automatically and
**cached locally** so subsequent conversions are instant.
The pipeline **stops immediately** if any required resource cannot be downloaded.

```bash
# From a public URL
mbtiles2vtpk -i input.mbtiles -o output.vtpk \
  --style https://raw.githubusercontent.com/mapbox/mapbox-gl-styles/master/styles/basic-v8.json

# From a local file
mbtiles2vtpk -i input.mbtiles -o output.vtpk --style ./my-style.json

# With a custom working directory
mbtiles2vtpk -i input.mbtiles -o output.vtpk --style ./my-style.json --work-dir C:\Temp\work
```

### All options

```
mbtiles2vtpk -i INPUT -o OUTPUT [--style URL_OR_PATH] [--work-dir DIR]
mbtiles2vtpk --cache-info
mbtiles2vtpk --clear-cache

conversion:
  -i, --input   PATH        Source .mbtiles file
  -o, --output  PATH        Output .vtpk file
  --style       URL_OR_PATH Mapbox GL style to embed (URL or local path)
  --work-dir    DIR         Intermediate working directory (default: auto temp)

cache:
  --cache-info              Show cache location and size, then exit
  --clear-cache             Delete all cached resources, then exit
```

### PyCharm / no install

```
Run > Edit Configurations
  → Module name : mbtiles2vtpk.cli
  → Parameters  : -i input.mbtiles -o output.vtpk [--style ...]
  → Working dir : <repo root>
```

---

## Resource cache

Downloaded fonts and sprites are cached in:

```
~/.mbtiles2vtpk/cache/
    styles/     ← style JSON files
    fonts/      ← PBF glyph files  (256 ranges × N fonts)
    sprites/    ← sprite.json / sprite.png / @2x variants
```

The cache key is the SHA-256 of the resource URL **without** the query string,
so changing API keys does not invalidate existing entries.

```bash
mbtiles2vtpk --cache-info    # show size
mbtiles2vtpk --clear-cache   # wipe everything
```

---

## MapTiler API credentials

When the style, fonts, or sprites are served from **api.maptiler.com**,
set these environment variables before running:

| Variable | Purpose |
|---|---|
| `MAPTILER_KEY` | API key — appended to every request as `?key=<value>` |
| `MAPTILER_ORIGIN` | Allowed origin — sent as the `Origin:` HTTP header |

If either variable is missing and the URL targets api.maptiler.com,
the conversion **stops with a clear error message**.

**Windows (PowerShell)**

```powershell
$env:MAPTILER_KEY    = "your_key_here"
$env:MAPTILER_ORIGIN = "https://your-app.example.com"
mbtiles2vtpk -i input.mbtiles -o output.vtpk --style https://api.maptiler.com/...
```

**Windows (CMD)**

```cmd
set MAPTILER_KEY=your_key_here
set MAPTILER_ORIGIN=https://your-app.example.com
mbtiles2vtpk -i input.mbtiles -o output.vtpk --style https://api.maptiler.com/...
```

**Linux / macOS**

```bash
export MAPTILER_KEY=your_key_here
export MAPTILER_ORIGIN=https://your-app.example.com
mbtiles2vtpk -i input.mbtiles -o output.vtpk --style https://api.maptiler.com/...
```

The credentials are injected at fetch time and **never stored in the cache**.

---

## External dependency

Tile bundle creation is delegated to
[ltbam/python-mbtiles2compactcache](https://github.com/ltbam/python-mbtiles2compactcache),
included as a git submodule under `mbtiles2vtpk/vendor/`.

```bash
# Populate after cloning
git submodule update --init --recursive
```

---

## Conversion pipeline

| # | Class | Description |
|---|-------|-------------|
| 1 | `StructureCreator` | Create VTPK folder skeleton |
| 2 | `TileExtractor` | Extract tiles → Compact Cache V2 bundles (via submodule) |
| 3 | `TilemapEditor` | Build presence quadtree → `p12/tilemap/root.json` |
| 4 | `StyleCopier` | Embed Mapbox GL style + download fonts & sprites |
| 5 | `RootJsonCreator` | Write `p12/root.json`, `metadata.json`, `esriinfo/` |
| 6 | `TileSizeEditor` | Patch tile size to 512 × 512 |
| 7 | `LodsEditor` | Verify LODs match extracted zoom levels |
| 8 | `FontResolver` | Write `p12/resources/info/root.json` resource index |
| 9 | `Repacker` | ZIP everything into a `.vtpk` archive (ZIP_STORED) |

---

## Output VTPK structure

```
output.vtpk  (ZIP, no compression)
├── esriinfo/
│   ├── item.pkinfo
│   └── iteminfo.xml
└── p12/
    ├── root.json
    ├── metadata.json
    ├── tile/
    │   ├── L00/R0000C0000.bundle
    │   └── ...
    ├── tilemap/
    │   └── root.json
    └── resources/
        ├── styles/root.json
        ├── fonts/<FontName>/<range>.pbf
        ├── sprites/sprite.json|png|@2x.*
        └── info/root.json
```
