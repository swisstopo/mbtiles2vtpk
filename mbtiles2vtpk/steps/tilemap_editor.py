"""
Step 3 – Generate p12/tilemap/root.json as a presence quadtree.

The quadtree is built by recursively descending the tile tree from z=0
down to the maximum zoom level present in the package.  At each node we
check whether the corresponding tile actually exists in the extracted
bundles (instead of testing intersection with a fixed bbox).

Tree structure (same as the reference VTPK):
  - 0   → tile absent (leaf)
  - 1   → tile present (leaf, only at max_level)
  - [ul, ur, ll, lr] → four children (upper-left, upper-right,
                                       lower-left, lower-right)

The child ordering follows the convention in quadtree.py:
    offsets = [(0,1), (1,1), (0,0), (1,0)]   dx, dy in TMS space

Bundle index encoding (compact cache v2):
    slot  = (vtpk_row - bundle_row_origin) * 128 + (col - bundle_col_origin)
    entry = 8 bytes little-endian  →  size in bits [63:40], offset in bits [39:0]
    size == 0  →  tile absent
"""

import json
import os
import struct
from typing import Dict, Set, Tuple

from .base_step import BaseStep
from ..logger import get_logger

log = get_logger("TilemapEditor")

BUNDLE_DIM = 128


# ---------------------------------------------------------------------------
# Bundle reading helpers
# ---------------------------------------------------------------------------

def _load_bundle_present_slots(path: str) -> Set[int]:
    """Return the set of slot indices that contain a tile in this bundle."""
    present = set()
    with open(path, "rb") as fh:
        fh.read(64)                              # skip header
        index = fh.read(BUNDLE_DIM * BUNDLE_DIM * 8)
    for slot in range(BUNDLE_DIM * BUNDLE_DIM):
        entry = struct.unpack_from("<Q", index, slot * 8)[0]
        size = (entry >> 40) & 0xFFFFFF
        if size > 0:
            present.add(slot)
    return present


def _build_presence_set(tile_dir: str, zoom: int) -> Set[Tuple[int, int]]:
    """
    Return a set of (vtpk_row, col) for every tile present at *zoom*.
    vtpk_row uses top-left origin (row 0 = top of world).
    """
    layer_dir = os.path.join(tile_dir, f"L{zoom:02d}")
    if not os.path.isdir(layer_dir):
        return set()

    present: Set[Tuple[int, int]] = set()
    for fname in os.listdir(layer_dir):
        if not fname.endswith(".bundle"):
            continue
        # filename: R<rrrr>C<cccc>.bundle  (hex, bundle-origin row/col)
        name = fname[:-7]                        # strip .bundle
        r_part, c_part = name[1:].split("C")
        br = int(r_part, 16)                     # bundle row origin
        bc = int(c_part, 16)                     # bundle col origin

        path = os.path.join(layer_dir, fname)
        slots = _load_bundle_present_slots(path)
        for slot in slots:
            slot_row = slot // BUNDLE_DIM
            slot_col = slot % BUNDLE_DIM
            present.add((br + slot_row, bc + slot_col))

    return present


# ---------------------------------------------------------------------------
# Quadtree builder (driven by presence sets, not a bbox)
# ---------------------------------------------------------------------------

def _build_tree(
    zoom: int,
    max_zoom: int,
    vtpk_row: int,
    col: int,
    presence_by_zoom: Dict[int, Set[Tuple[int, int]]],
) -> object:
    """
    Recursively build the presence quadtree node for the tile at
    (vtpk_row, col, zoom).

    vtpk_row uses the VTPK convention: row 0 = top of world.

    Returns:
      0         – tile and all descendants absent
      1         – tile present (leaf at max_zoom)
      [...]     – list of four child results
    """
    # Is this tile present at the current zoom?
    if (vtpk_row, col) not in presence_by_zoom.get(zoom, set()):
        return 0

    # Leaf level reached
    if zoom == max_zoom:
        return 1

    # Recurse into the four children.
    # In the quadtree.py convention the offsets are (dx, dy) in TMS y-up space:
    #   upper-left  (0,1) → VTPK row offset 0, col offset 0
    #   upper-right (1,1) → VTPK row offset 0, col offset 1
    #   lower-left  (0,0) → VTPK row offset 1, col offset 0
    #   lower-right (1,0) → VTPK row offset 1, col offset 1
    #
    # TMS dy=1 means "same row as parent's top half" → VTPK row*2 + 0 (top)
    # TMS dy=0 means "parent's bottom half"          → VTPK row*2 + 1 (bottom)
    child_offsets = [
        (0, 0),   # upper-left  (TMS dx=0, dy=1)
        (0, 1),   # upper-right (TMS dx=1, dy=1)
        (1, 0),   # lower-left  (TMS dx=0, dy=0)
        (1, 1),   # lower-right (TMS dx=1, dy=0)
    ]

    children = []
    for dr, dc in child_offsets:
        child_row = vtpk_row * 2 + dr
        child_col = col * 2 + dc
        child_zoom = zoom + 1
        children.append(
            _build_tree(child_zoom, max_zoom, child_row, child_col, presence_by_zoom)
        )

    # Compact: if all children are 0 the parent should be 0 too,
    # but since we already know the parent tile exists we keep it.
    return children


def _build_full_tree(
    min_zoom: int,
    max_zoom: int,
    presence_by_zoom: Dict[int, Set[Tuple[int, int]]],
) -> object:
    """
    Build the top-level quadtree.  Zoom 0 has exactly one tile (0, 0).
    If min_zoom > 0 we still start from z=0 and walk down.
    """
    return _build_tree(0, max_zoom, 0, 0, presence_by_zoom)


# ---------------------------------------------------------------------------
# Step class
# ---------------------------------------------------------------------------

class TilemapEditor(BaseStep):
    """
    Scans the extracted tile bundles, builds a presence quadtree for all
    zoom levels, and writes it to p12/tilemap/root.json.
    """

    def __init__(self, work_dir: str):
        self.work_dir = work_dir

    def run(self) -> None:
        tile_dir = os.path.join(self.work_dir, "p12", "tile")
        log.info("Scanning tile directory: %s", tile_dir)

        zoom_dirs = sorted(
            d for d in os.listdir(tile_dir)
            if d.startswith("L") and os.path.isdir(os.path.join(tile_dir, d))
        )
        if not zoom_dirs:
            log.warning("No zoom directories found — tilemap will be empty.")
            self._write({})
            return

        zoom_levels = [int(d[1:]) for d in zoom_dirs]
        min_zoom = min(zoom_levels)
        max_zoom = max(zoom_levels)
        log.info("Zoom levels: %s → building quadtree from z%d to z%d", zoom_levels, min_zoom, max_zoom)

        # Load tile presence for every zoom level
        presence_by_zoom: Dict[int, Set[Tuple[int, int]]] = {}
        for z in zoom_levels:
            ps = _build_presence_set(tile_dir, z)
            presence_by_zoom[z] = ps
            log.info("  z%d: %d tiles present", z, len(ps))

        log.info("Building quadtree…")
        tree = _build_full_tree(min_zoom, max_zoom, presence_by_zoom)

        out_path = os.path.join(self.work_dir, "p12", "tilemap", "root.json")
        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump({"index": tree}, fh, separators=(",", ":"))

        log.info("p12/tilemap/root.json written.")
