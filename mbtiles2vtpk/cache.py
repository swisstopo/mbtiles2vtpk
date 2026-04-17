"""
Disk cache for remote resources (fonts, sprites).

Cache location: ~/.mbtiles2vtpk/cache/
Structure:
    ~/.mbtiles2vtpk/cache/
        fonts/
            <sha256_of_url>.pbf
        sprites/
            <sha256_of_url>.json
            <sha256_of_url>.png

Cache key = SHA-256 of the full URL, so different URLs never collide.
"""

import hashlib
import os
import urllib.request
import urllib.parse
from typing import Optional

from .logger import get_logger

log = get_logger("Cache")

_CACHE_ROOT = os.path.join(os.path.expanduser("~"), ".mbtiles2vtpk", "cache")

# ---------------------------------------------------------------------------
# MapTiler credentials (read once from environment)
# ---------------------------------------------------------------------------
# Set these environment variables when using styles/fonts/sprites from
# api.maptiler.com:
#
#   MAPTILER_KEY    – your MapTiler API key, appended as ?key=<value>
#   MAPTILER_ORIGIN – your allowed origin, sent as the Origin: header
#
_MAPTILER_KEY    = os.environ.get("MAPTILER_KEY",    "")
_MAPTILER_ORIGIN = os.environ.get("MAPTILER_ORIGIN", "")


def _inject_maptiler(url: str) -> tuple[str, dict]:
    """
    If *url* targets api.maptiler.com, inject the API key as a query
    parameter and build the required Origin header.
    Returns (patched_url, headers_dict).
    """
    headers = {}
    if "api.maptiler.com" not in url:
        return url, headers

    if _MAPTILER_KEY:
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}key={urllib.parse.quote(_MAPTILER_KEY)}"
    else:
        log.warning("MAPTILER_KEY not set — requests to api.maptiler.com may fail.")

    if _MAPTILER_ORIGIN:
        headers["Origin"] = _MAPTILER_ORIGIN
    else:
        log.warning("MAPTILER_ORIGIN not set — requests to api.maptiler.com may be blocked.")

    return url, headers


def _cache_path(category: str, url: str, ext: str) -> str:
    # Strip API key from URL before hashing so the cache key is stable
    # even if the key changes.
    clean_url = url.split("?")[0]
    key = hashlib.sha256(clean_url.encode()).hexdigest()
    return os.path.join(_CACHE_ROOT, category, f"{key}{ext}")


def _ext(url: str) -> str:
    """Guess file extension from URL (ignoring query string)."""
    url_path = url.split("?")[0]
    if url_path.endswith(".png"):  return ".png"
    if url_path.endswith(".json"): return ".json"
    if url_path.endswith(".pbf"):  return ".pbf"
    return ".bin"


class FetchError(RuntimeError):
    """Raised when a required remote resource cannot be downloaded."""


def fetch(url: str, category: str = "misc", binary: bool = True) -> bytes:
    """
    Return the content of *url* as bytes.

    1. Check disk cache  → return immediately if hit.
    2. Inject MapTiler credentials if url targets api.maptiler.com.
    3. Download from network → store in cache → return.

    Raises FetchError if the download fails so the pipeline stops immediately
    rather than silently producing an incomplete VTPK.
    """
    ext  = _ext(url)
    path = _cache_path(category, url, ext)

    # --- Cache hit ---
    if os.path.exists(path):
        return open(path, "rb").read()

    # --- Inject MapTiler credentials if needed ---
    fetch_url, headers = _inject_maptiler(url)

    # --- Network fetch ---
    log.debug("    Downloading %s", url)
    try:
        req  = urllib.request.Request(fetch_url, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = resp.read()
    except Exception as e:
        raise FetchError(
            f"Failed to download resource:\n"
            f"  URL      : {url}\n"
            f"  Reason   : {e}\n"
            f"  Tip      : check network access and, for api.maptiler.com,\n"
            f"             set MAPTILER_KEY and MAPTILER_ORIGIN env variables."
        ) from e

    # --- Store in cache ---
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(data)

    return data


def fetch_optional(url: str, category: str = "misc") -> Optional[bytes]:
    """Like fetch() but returns None instead of raising on failure."""
    try:
        return fetch(url, category)
    except FetchError as e:
        log.warning("%s", e)
        return None


def clear(category: str = None) -> int:
    """Remove cached files. Returns number of files deleted."""
    root = os.path.join(_CACHE_ROOT, category) if category else _CACHE_ROOT
    deleted = 0
    for dirpath, _, filenames in os.walk(root):
        for fname in filenames:
            os.remove(os.path.join(dirpath, fname))
            deleted += 1
    return deleted


def cache_size() -> int:
    """Return total cache size in bytes."""
    total = 0
    for dirpath, _, filenames in os.walk(_CACHE_ROOT):
        for fname in filenames:
            total += os.path.getsize(os.path.join(dirpath, fname))
    return total
