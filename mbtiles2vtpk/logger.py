"""
Simple logger factory for mbtiles2vtpk.
Each step gets a named logger so output looks like:
  [StructureCreator] Creating VTPK folder structure...
  [TileExtractor]    Extracting z0 (1 tiles)...
"""

import logging

_FMT = "[%(name)-20s] %(message)s"
logging.basicConfig(level=logging.INFO, format=_FMT)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
