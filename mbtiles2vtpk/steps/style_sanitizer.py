"""
Style sanitizer — ArcGIS Pro safe mode.

Converts a Mapbox GL Style Specification v8 style into a subset that
ArcGIS Pro can render without warnings or silent layer drops.

Usage
-----
    from .style_sanitizer import StyleSanitizer

    sanitizer = StyleSanitizer(style_dict)
    safe_style = sanitizer.run()

Fixes applied
-------------
 1. paint.fill-pattern           expression → most-common literal, or removed
 2. layout unsupported props      symbol-z-order, icon-text-fit, icon-text-fit-padding,
                                  text-writing-mode → removed
 2b. layout.line-cap/line-join   ["literal","x"] or expression → bare string
 3. layout.text-radial-offset    → text-offset [0, -distance]
 4. layout.text-variable-anchor  → text-anchor (first value)
 5. layout.symbol-placement      "line-center" → "line"
 6. layout.text-field            array expression → string template
 7. layout.symbol-sort-key       → removed
 8. filter typeof expressions    → branch removed / filter simplified
 9. filter comparisons           → bare get coerced to to-number/to-string
10. numeric expressions          → bare get in output positions wrapped with to-number
11. layout.text-justify          "auto" or expression → "center"
12. layout.text-anchor           ["literal","x"] or expression → first valid literal
13. layout.text-transform        expression → first valid literal
14. layout.icon-image            expression → first non-empty literal, or removed
"""

import copy
from collections import Counter
from typing import Any, Optional

from ..logger import get_logger

log = get_logger("StyleSanitizer")


class StyleSanitizer:
    """
    Applies ArcGIS Pro safe mode fixes to a Mapbox GL style.

    Parameters
    ----------
    style : dict
        Parsed Mapbox GL style JSON (will be deep-copied, not mutated).
    """

    def __init__(self, style: dict):
        self._style = style

    def run(self) -> dict:
        """Return a new, sanitized copy of the style."""
        style = copy.deepcopy(self._style)
        counters: dict = {}

        for layer in style.get("layers", []):
            paint  = layer.setdefault("paint",  {})
            layout = layer.setdefault("layout", {})

            # 1. fill-pattern: expression → literal or remove
            if "fill-pattern" in paint:
                fixed = _simplify_fill_pattern(paint["fill-pattern"])
                if fixed is None:
                    del paint["fill-pattern"]
                    _count(counters, "fill-pattern removed (no extractable literal)")
                elif fixed != paint["fill-pattern"]:
                    paint["fill-pattern"] = fixed
                    _count(counters, "fill-pattern expression → literal")

            # 2. remove unsupported layout properties
            for _prop in ("symbol-z-order", "icon-text-fit", "icon-text-fit-padding",
                          "text-writing-mode"):
                if _prop in layout:
                    del layout[_prop]
                    _count(counters, f"{_prop} removed")

            # 2b. line-cap / line-join: unwrap ["literal","x"] or fallback default
            for _prop in ("line-cap", "line-join"):
                val = layout.get(_prop)
                if isinstance(val, list) and val and val[0] == "literal" and len(val) == 2:
                    layout[_prop] = val[1]
                    _count(counters, f"{_prop} ['literal','x'] → bare string")
                elif isinstance(val, list):
                    layout[_prop] = "round" if _prop == "line-cap" else "miter"
                    _count(counters, f"{_prop} expression → default literal")

            # 3. text-radial-offset → text-offset
            if "text-radial-offset" in layout:
                radial = layout.pop("text-radial-offset")
                if "text-offset" not in layout:
                    layout["text-offset"] = _radial_to_cartesian_offset(radial)
                    _count(counters, "text-radial-offset → text-offset")
                else:
                    _count(counters, "text-radial-offset removed (text-offset exists)")

            # 4. text-variable-anchor → text-anchor (first value)
            if "text-variable-anchor" in layout:
                anchors = layout.pop("text-variable-anchor")
                if "text-anchor" not in layout:
                    first = anchors[0] if isinstance(anchors, list) and anchors else "center"
                    layout["text-anchor"] = first
                    _count(counters, "text-variable-anchor → text-anchor")
                else:
                    _count(counters, "text-variable-anchor removed (text-anchor exists)")

            # 5. symbol-placement "line-center" → "line"
            if layout.get("symbol-placement") == "line-center":
                layout["symbol-placement"] = "line"
                _count(counters, "symbol-placement line-center → line")

            # 6. text-field array expression → string
            if "text-field" in layout and isinstance(layout["text-field"], list):
                layout["text-field"] = _simplify_text_field(layout["text-field"])
                _count(counters, "text-field expression → string")

            # 7. symbol-sort-key → remove
            if "symbol-sort-key" in layout:
                del layout["symbol-sort-key"]
                _count(counters, "symbol-sort-key removed")

            # 8. filter: remove typeof expressions
            if "filter" in layer:
                fixed_filter = _remove_typeof_from_filter(layer["filter"])
                if fixed_filter is None:
                    del layer["filter"]
                    _count(counters, "filter removed (only typeof branch)")
                elif fixed_filter != layer["filter"]:
                    layer["filter"] = fixed_filter
                    _count(counters, "filter typeof branch removed")

            # 9. filter: coerce type mismatches in comparisons
            if "filter" in layer:
                layer["filter"] = _coerce_filter_comparisons(layer["filter"])

            # 10. numeric expressions: coerce value→number where needed
            _NUMERIC_LAYOUT_PROPS = (
                "text-size", "icon-size", "text-opacity", "icon-opacity",
                "text-halo-width", "text-halo-blur", "icon-rotate",
                "symbol-spacing", "text-max-width", "text-letter-spacing",
            )
            _NUMERIC_PAINT_PROPS = (
                "icon-opacity", "text-opacity", "fill-opacity", "line-opacity",
                "line-width", "line-offset", "line-gap-width", "line-blur",
                "fill-extrusion-opacity", "fill-extrusion-height", "fill-extrusion-base",
                "circle-radius", "circle-opacity", "circle-blur",
                "heatmap-weight", "heatmap-intensity", "heatmap-opacity",
                "raster-opacity", "raster-brightness-min", "raster-brightness-max",
            )
            for prop in _NUMERIC_LAYOUT_PROPS:
                if prop in layout and isinstance(layout[prop], list):
                    layout[prop] = _coerce_numeric_expression(layout[prop])
            for prop in _NUMERIC_PAINT_PROPS:
                if prop in paint and isinstance(paint[prop], list):
                    paint[prop] = _coerce_numeric_expression(paint[prop])

            # 11. text-justify: "auto" or expression → "center"
            tj = layout.get("text-justify")
            if tj == "auto" or isinstance(tj, list):
                layout["text-justify"] = "center"
                _count(counters, "text-justify → center")

            # 12. text-anchor: ["literal","x"] or expression → first valid literal
            ta = layout.get("text-anchor")
            if isinstance(ta, list):
                if ta and ta[0] == "literal" and len(ta) == 2:
                    layout["text-anchor"] = ta[1]
                    _count(counters, "text-anchor ['literal','x'] → bare string")
                else:
                    layout["text-anchor"] = _extract_first_string_output(ta, "center")
                    _count(counters, "text-anchor expression → first literal")

            # 13. text-transform: expression → first valid literal
            tt = layout.get("text-transform")
            if isinstance(tt, list):
                layout["text-transform"] = _extract_first_string_output(
                    tt, "none", valid={"none", "uppercase", "lowercase"})
                _count(counters, "text-transform expression → literal")

            # 14. icon-image: expression → first non-empty literal, or remove
            ii = layout.get("icon-image")
            if isinstance(ii, list):
                val = _extract_first_string_output(ii, "")
                if val:
                    layout["icon-image"] = val
                    _count(counters, "icon-image expression → first literal")
                else:
                    del layout["icon-image"]
                    _count(counters, "icon-image expression removed (no literal found)")

            # Clean up empty dicts we may have introduced
            if not paint:
                del layer["paint"]
            if not layout:
                del layer["layout"]

        if counters:
            log.info("  Pro safe mode — fixes applied:")
            for k, v in sorted(counters.items()):
                log.info("    %-52s %d layer(s)", k, v)
        else:
            log.info("  Pro safe mode — no fixes needed, style already compatible.")

        return style


# ---------------------------------------------------------------------------
# Helpers — expression output extraction
# ---------------------------------------------------------------------------

def _collect_expression_outputs(expr: Any) -> list:
    """
    Collect output value strings from a GL expression tree.
    Only descends into OUTPUT positions of match/step/case — never into
    operator names, input expressions, or label/condition positions.
    """
    if isinstance(expr, str):
        return [expr]
    if not isinstance(expr, list) or not expr:
        return []

    op = expr[0] if isinstance(expr[0], str) else None

    if op == "literal" and len(expr) == 2:
        return _collect_expression_outputs(expr[1])

    if op in ("step", "interpolate"):
        results = []
        for item in expr[2:]:
            if isinstance(item, list):
                results.extend(_collect_expression_outputs(item))
            elif isinstance(item, str):
                results.append(item)
        return results

    if op == "match":
        if len(expr) < 4:
            return []
        results = []
        i = 3
        while i < len(expr):
            results.extend(_collect_expression_outputs(expr[i]))
            i += 2
        return results

    if op == "case":
        results = []
        i = 2
        while i < len(expr):
            results.extend(_collect_expression_outputs(expr[i]))
            i += 2
        return results

    if op == "coalesce":
        results = []
        for item in expr[1:]:
            results.extend(_collect_expression_outputs(item))
        return results

    results = []
    for item in expr[1:]:
        if isinstance(item, list):
            results.extend(_collect_expression_outputs(item))
    return results


def _extract_first_string_output(expr: Any, default: str,
                                  valid: set = None) -> str:
    for c in _collect_expression_outputs(expr):
        if isinstance(c, str) and c:
            if valid is None or c in valid:
                return c
    return default


def _simplify_fill_pattern(value: Any) -> Optional[Any]:
    if isinstance(value, str):
        return value
    if not isinstance(value, list):
        return None
    outputs = _collect_expression_outputs(value)
    non_empty = [o for o in outputs if isinstance(o, str) and o]
    if not non_empty:
        return None
    return Counter(non_empty).most_common(1)[0][0]


def _radial_to_cartesian_offset(radial_value: Any) -> Any:
    if isinstance(radial_value, (int, float)):
        return [0, -abs(radial_value)]
    return [0, -0.5]


def _simplify_text_field(expr: Any) -> str:
    if not isinstance(expr, list) or not expr:
        return str(expr) if expr else ""
    op = expr[0] if isinstance(expr[0], str) else None
    if op == "get" and len(expr) == 2:
        return "{" + str(expr[1]) + "}"
    if op == "to-string":
        return _simplify_text_field(expr[1]) if len(expr) > 1 else ""
    if op == "concat":
        parts = []
        for part in expr[1:]:
            parts.append(_simplify_text_field(part) if isinstance(part, list) else str(part) if isinstance(part, str) else "")
        return "".join(parts)
    if op == "format":
        parts = []
        i = 1
        while i < len(expr):
            part = expr[i]
            if isinstance(part, list):
                parts.append(_simplify_text_field(part))
            elif isinstance(part, str):
                parts.append(part)
            i += 2 if (i + 1 < len(expr) and isinstance(expr[i + 1], dict)) else 1
        return " ".join(p for p in parts if p.strip())
    if op == "coalesce":
        for sub in expr[1:]:
            if isinstance(sub, list):
                r = _simplify_text_field(sub)
                if r:
                    return r
        return ""
    if op in ("upcase", "downcase"):
        return _simplify_text_field(expr[1]) if len(expr) > 1 else ""
    if op == "literal" and len(expr) == 2:
        return str(expr[1])
    field_refs = []
    for i, item in enumerate(expr):
        if item == "get" and i + 1 < len(expr) and isinstance(expr[i + 1], str):
            field_refs.append("{" + expr[i + 1] + "}")
    return " ".join(field_refs) if field_refs else ""


# ---------------------------------------------------------------------------
# Helpers — typeof filter removal
# ---------------------------------------------------------------------------

def _remove_typeof_from_filter(expr: Any) -> Any:
    if not isinstance(expr, list) or not expr:
        return expr
    if _contains_typeof(expr):
        return None
    op = expr[0] if isinstance(expr[0], str) else None
    if op == "all":
        cleaned = [c for c in (_remove_typeof_from_filter(x) for x in expr[1:]) if c is not None]
        if not cleaned:
            return None
        return cleaned[0] if len(cleaned) == 1 else ["all"] + cleaned
    if op == "any":
        for child in expr[1:]:
            if _remove_typeof_from_filter(child) is None:
                return None
        cleaned = [c for c in (_remove_typeof_from_filter(x) for x in expr[1:]) if c is not None]
        return cleaned[0] if len(cleaned) == 1 else ["any"] + cleaned if cleaned else None
    if op == "case":
        new_expr = ["case"]
        i = 1
        while i + 1 < len(expr):
            cond = _remove_typeof_from_filter(expr[i])
            if cond is None:
                return expr[i + 1]
            new_expr.extend([cond, expr[i + 1]])
            i += 2
        if len(expr) > i:
            new_expr.append(expr[i])
        return new_expr if len(new_expr) > 1 else None
    return expr


def _contains_typeof(expr: Any) -> bool:
    if not isinstance(expr, list):
        return False
    if expr and expr[0] == "typeof":
        return True
    return any(_contains_typeof(item) for item in expr)


# ---------------------------------------------------------------------------
# Helpers — type coercion
# ---------------------------------------------------------------------------

_COMPARISON_OPS = {"==", "!=", "<", "<=", ">", ">="}


def _coerce_filter_comparisons(expr: Any) -> Any:
    if not isinstance(expr, list) or not expr:
        return expr
    op = expr[0] if isinstance(expr[0], str) else None
    if op in _COMPARISON_OPS and len(expr) == 3:
        left  = _coerce_operand(expr[1], expr[2])
        right = _coerce_operand(expr[2], expr[1])
        return [op, left, right]
    return [expr[0]] + [_coerce_filter_comparisons(c) if isinstance(c, list) else c
                        for c in expr[1:]]


def _coerce_operand(operand: Any, other: Any) -> Any:
    if not isinstance(operand, list) or not operand or operand[0] != "get":
        return operand
    other_val = other[1] if (isinstance(other, list) and other and
                              other[0] in ("to-number", "to-string") and len(other) > 1) else other
    if isinstance(other_val, (int, float)):
        return ["to-number", operand]
    if isinstance(other_val, str):
        return ["to-string", operand]
    return operand


def _coerce_numeric_expression(expr: Any) -> Any:
    if not isinstance(expr, list) or not expr:
        return expr
    op = expr[0] if isinstance(expr[0], str) else None
    if op == "get":
        return ["to-number", expr]
    if op == "interpolate" and len(expr) >= 4:
        new = ["interpolate", expr[1], expr[2]]
        i = 3
        while i < len(expr):
            new.append(expr[i])
            if i + 1 < len(expr):
                new.append(_coerce_numeric_output(expr[i + 1]))
            i += 2
        return new
    if op == "step" and len(expr) >= 3:
        new = ["step", expr[1], _coerce_numeric_output(expr[2])]
        i = 3
        while i < len(expr):
            new.append(expr[i])
            if i + 1 < len(expr):
                new.append(_coerce_numeric_output(expr[i + 1]))
            i += 2
        return new
    if op == "match" and len(expr) >= 4:
        new = [op, expr[1]]
        i = 2
        while i + 1 < len(expr):
            new.append(expr[i])
            new.append(_coerce_numeric_output(expr[i + 1]))
            i += 2
        new.append(_coerce_numeric_output(expr[i]))
        return new
    if op == "case":
        new = ["case"]
        i = 1
        while i + 1 < len(expr):
            new.append(_coerce_filter_comparisons(expr[i]))
            new.append(_coerce_numeric_output(expr[i + 1]))
            i += 2
        if i < len(expr):
            new.append(_coerce_numeric_output(expr[i]))
        return new
    if op == "coalesce":
        return ["coalesce"] + [_coerce_numeric_output(c) for c in expr[1:]]
    return expr


def _coerce_numeric_output(val: Any) -> Any:
    if isinstance(val, list) and val:
        if val[0] == "get":
            return ["to-number", val]
        return _coerce_numeric_expression(val)
    return val


def _count(counters: dict, key: str) -> None:
    counters[key] = counters.get(key, 0) + 1
