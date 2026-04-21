"""
Step 4b – Sanitize a Mapbox GL style for ArcGIS Pro compatibility.

ArcGIS Pro supports a subset of the Mapbox Style Specification v8.
This step fixes the known incompatibilities so Pro can render the style
without warnings or silent layer drops.

Fixes applied
-------------
1. paint.fill-pattern  – property expressions not supported
   → replace with the most-common literal value found in the expression,
     or remove the property when no literal can be extracted.

2. layout.symbol-z-order  – unknown property
   → remove.

3. layout.text-radial-offset  – unknown property
   → convert to text-offset (Cartesian [x, y] in ems).

4. layout.text-variable-anchor  – unknown property
   → convert to text-anchor using the first value in the list.

5. layout.symbol-placement "line-center"  – unsupported value
   → replace with "line".

6. layout.text-field  – string expected, array found
   → convert ["format", …] / ["concat", …] / ["get", "field"] expressions
     to a plain string template or the simplest equivalent literal.

7. layout.symbol-sort-key  – unknown property
   → remove.
"""

import copy
from collections import Counter
from typing import Any, Optional

from ..logger import get_logger

log = get_logger("StyleSanitizer")


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def sanitize_for_arcgis_pro(style: dict) -> dict:
    """
    Return a deep-copied, sanitized version of *style* compatible with
    ArcGIS Pro's Mapbox GL renderer.
    """
    style = copy.deepcopy(style)
    counters: dict = {}

    for layer in style.get("layers", []):
        paint  = layer.setdefault("paint",  {})
        layout = layer.setdefault("layout", {})

        # 1. fill-pattern: property expressions → literal or remove
        if "fill-pattern" in paint:
            fixed = _simplify_fill_pattern(paint["fill-pattern"])
            if fixed is None:
                del paint["fill-pattern"]
                _count(counters, "fill-pattern removed (no extractable literal)")
            elif fixed != paint["fill-pattern"]:
                paint["fill-pattern"] = fixed
                _count(counters, "fill-pattern expression → literal")

        # 2. symbol-z-order, icon-text-fit, icon-text-fit-padding → remove
        for _unsupported in ("symbol-z-order", "icon-text-fit", "icon-text-fit-padding",
                             "text-writing-mode"):
            if _unsupported in layout:
                del layout[_unsupported]
                _count(counters, f"{_unsupported} removed")

        # 2b. line-cap / line-join: unwrap ["literal", "value"] → bare string
        for _prop in ("line-cap", "line-join"):
            val = layout.get(_prop)
            if isinstance(val, list) and val and val[0] == "literal" and len(val) == 2:
                layout[_prop] = val[1]
                _count(counters, f"{_prop} ['literal','x'] → bare string")
            elif isinstance(val, list):
                # Any other expression → use safe defaults
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

        # 8. filter: remove typeof expressions (unsupported by QGIS/Pro)
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

        # 10. layout + paint numeric expressions: coerce value→number where needed
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
        if tj == "auto" or (isinstance(tj, list)):
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
                tt, "none", valid={"none","uppercase","lowercase"})
            _count(counters, "text-transform expression → literal")

        # 14. icon-image: expression → first non-empty literal output
        ii = layout.get("icon-image")
        if isinstance(ii, list):
            val = _extract_first_string_output(ii, "")
            if val:
                layout["icon-image"] = val
                _count(counters, "icon-image expression → first literal")
            else:
                del layout["icon-image"]
                _count(counters, "icon-image expression removed (no literal found)")

        # 12. icon-image: expressions not supported → extract best literal
        if "icon-image" in layout and isinstance(layout["icon-image"], list):
            fixed = _simplify_icon_image(layout["icon-image"])
            if fixed is None:
                del layout["icon-image"]
                _count(counters, "icon-image expression removed (no literal)")
            else:
                layout["icon-image"] = fixed
                _count(counters, "icon-image expression → literal")

        # Clean up empty dicts we may have introduced
        if not paint:
            del layer["paint"]
        if not layout:
            del layer["layout"]

    if counters:
        log.info("  Style sanitization summary:")
        for k, v in sorted(counters.items()):
            log.info("    %-50s %d layer(s)", k, v)
    else:
        log.info("  No ArcGIS Pro incompatibilities found – style unchanged.")

    return style


# ---------------------------------------------------------------------------
# Fix helpers
# ---------------------------------------------------------------------------

def _simplify_fill_pattern(value: Any) -> Optional[Any]:
    """
    ArcGIS Pro only supports a literal string for fill-pattern.
    If *value* is already a string, return it unchanged.
    Otherwise extract output values from a match/step/case expression —
    only the OUTPUT positions, never operator names or input/label strings.
    Returns the most-frequent non-empty output string, or None if none found.
    """
    if isinstance(value, str):
        return value  # already fine

    if not isinstance(value, list):
        return None

    outputs = _collect_expression_outputs(value)
    non_empty = [o for o in outputs if isinstance(o, str) and o]
    if not non_empty:
        return None

    return Counter(non_empty).most_common(1)[0][0]


def _collect_expression_outputs(expr: Any) -> list:
    """
    Collect output value strings from a GL expression tree.
    Only descends into OUTPUT positions of match/step/case, never into
    operator names, input expressions, or label/condition positions.
    This avoids collecting operator keywords like "match", "get", or
    feature-property values like "lake_elevation" as if they were outputs.
    """
    if isinstance(expr, str):
        # A bare string at top level IS an output (e.g. default of match)
        return [expr]

    if not isinstance(expr, list) or not expr:
        return []

    op = expr[0] if isinstance(expr[0], str) else None

    if op == "literal" and len(expr) == 2:
        inner = expr[1]
        return [inner] if isinstance(inner, str) else []

    if op == "match":
        # ["match", input, label, output, label, output, ..., default]
        # Outputs at positions 3, 5, 7, … and last item
        if len(expr) < 4:
            return []
        results = []
        i = 3
        while i < len(expr):
            results.extend(_collect_expression_outputs(expr[i]))
            i += 2
        return results

    if op in ("step", "interpolate"):
        # Outputs are list items after the first 2-3 items; skip non-list inputs
        results = []
        for item in expr[2:]:
            if isinstance(item, list):
                results.extend(_collect_expression_outputs(item))
            elif isinstance(item, str):
                results.append(item)
        return results

    if op == "case":
        # ["case", cond, output, cond, output, ..., default]
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

    # Any other expression: recurse into list children (not strings, which
    # would be operator names or property names)
    results = []
    for item in expr[1:]:
        if isinstance(item, list):
            results.extend(_collect_expression_outputs(item))
    return results


def _radial_to_cartesian_offset(radial_value: Any) -> Any:
    """
    Convert text-radial-offset (scalar, ems from anchor) to text-offset ([x, y]).
    We approximate radial placement as [0, -distance], i.e. directly above the
    anchor — the most common usage for point labels.
    For expression values we fall back to a safe default of [0, -0.5].
    """
    if isinstance(radial_value, (int, float)):
        return [0, -abs(radial_value)]
    return [0, -0.5]


def _simplify_text_field(expr: Any) -> str:
    """
    Convert a text-field expression array to a string ArcGIS Pro understands.

    ArcGIS Pro expects either a plain string ("My Label") or a field
    reference wrapped in curly braces ("{name}").

    Patterns handled:
      ["get", "field"]               → "{field}"
      ["to-string", ["get","field"]] → "{field}"
      ["concat", ...]                → concatenate sub-expressions
      ["format", part, opts, ...]    → concatenate text parts (skip opts dicts)
      ["coalesce", e1, e2, ...]      → first resolvable get expression
      ["upcase"|"downcase", e]       → delegate to inner expression
      ["literal", value]             → str(value)
      fallback                       → collect all ["get","x"] refs as "{x} {y}"
    """
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
            if isinstance(part, list):
                parts.append(_simplify_text_field(part))
            elif isinstance(part, str):
                parts.append(part)
        return "".join(parts)

    if op == "format":
        # ["format", text_expr, {opts}, text_expr2, {opts2}, …]
        parts = []
        i = 1
        while i < len(expr):
            part = expr[i]
            if isinstance(part, list):
                parts.append(_simplify_text_field(part))
            elif isinstance(part, str):
                parts.append(part)
            # skip the immediately following options dict (if any)
            if i + 1 < len(expr) and isinstance(expr[i + 1], dict):
                i += 2
            else:
                i += 1
        return " ".join(p for p in parts if p.strip())

    if op == "coalesce":
        for sub in expr[1:]:
            if isinstance(sub, list):
                result = _simplify_text_field(sub)
                if result:
                    return result
        return ""

    if op in ("upcase", "downcase"):
        return _simplify_text_field(expr[1]) if len(expr) > 1 else ""

    if op == "literal" and len(expr) == 2:
        return str(expr[1])

    # Fallback: scan for all ["get", x] pairs
    field_refs = []
    for i, item in enumerate(expr):
        if item == "get" and i + 1 < len(expr) and isinstance(expr[i + 1], str):
            field_refs.append("{" + expr[i + 1] + "}")
    if field_refs:
        return " ".join(field_refs)

    return ""


def _extract_first_string_output(expr: Any, default: str, valid: set = None) -> str:
    """
    Extract the first non-empty string output from a GL expression.
    Used to simplify icon-image, text-anchor, text-transform, text-justify
    expressions into a single literal value ArcGIS Pro can handle.

    - If expr is already a string, return it (filtered by valid if given).
    - For match/step/case/coalesce, collect all string outputs and return
      the first non-empty one that passes the valid filter.
    - Falls back to default if nothing usable is found.
    """
    candidates = _collect_expression_outputs(expr)
    for c in candidates:
        if isinstance(c, str) and c:
            if valid is None or c in valid:
                return c
    return default


def _remove_typeof_from_filter(expr: Any) -> Any:
    """
    Recursively remove sub-expressions that use the unsupported "typeof"
    operator from a filter expression.

    Rules:
    - Any expression that DIRECTLY uses "typeof" → replace with True
      (i.e. drop the condition, let all features through — safer than
      dropping the layer entirely).
    - ["all", ...] / ["any", ...] / ["none", ...] → recurse into children,
      remove True branches from "all"/"none", remove False branches from "any".
    - Returns None if the entire filter reduces to a no-op (caller removes it).
    """
    if not isinstance(expr, list) or not expr:
        return expr

    # Direct typeof usage: ["==", ["typeof", ...], "string"] etc.
    if _contains_typeof(expr):
        # If the whole expression depends on typeof, replace with True (pass-all)
        return None  # caller will treat as "remove this branch"

    op = expr[0] if isinstance(expr[0], str) else None

    if op == "all":
        cleaned = []
        for child in expr[1:]:
            result = _remove_typeof_from_filter(child)
            if result is None:
                # typeof branch → True, skip (neutral for "all")
                continue
            cleaned.append(result)
        if not cleaned:
            return None  # ["all"] with no conditions → remove filter
        if len(cleaned) == 1:
            return cleaned[0]
        return ["all"] + cleaned

    if op == "any":
        cleaned = []
        for child in expr[1:]:
            result = _remove_typeof_from_filter(child)
            if result is None:
                # typeof branch → True → "any" is always True → remove filter
                return None
            cleaned.append(result)
        if not cleaned:
            return None
        if len(cleaned) == 1:
            return cleaned[0]
        return ["any"] + cleaned

    if op == "case":
        # ["case", cond, output, cond, output, ..., default]
        new_expr = ["case"]
        i = 1
        while i + 1 < len(expr):
            cond = _remove_typeof_from_filter(expr[i])
            output = expr[i + 1]
            if cond is None:
                # condition always true → this branch always wins, use output directly
                return output
            new_expr.extend([cond, output])
            i += 2
        if len(expr) > i:
            new_expr.append(expr[i])  # default
        return new_expr if len(new_expr) > 1 else None

    # For other compound expressions, recurse into list children
    return expr


def _contains_typeof(expr: Any) -> bool:
    """Return True if expr or any sub-expression uses the typeof operator."""
    if not isinstance(expr, list):
        return False
    if expr and expr[0] == "typeof":
        return True
    return any(_contains_typeof(item) for item in expr)



# Comparison operators that expect same-type operands
_COMPARISON_OPS = {"==", "!=", "<", "<=", ">", ">="}


def _coerce_filter_comparisons(expr: Any) -> Any:
    """
    Recursively fix type mismatches in filter/condition expressions.

    Problem patterns:
      ["op", ["get","x"], NUMBER]  ->  ["op", ["to-number",["get","x"]], NUMBER]
      ["op", NUMBER, ["get","x"]]  ->  ["op", NUMBER, ["to-number",["get","x"]]]
      ["op", ["get","x"], STRING]  ->  ["op", ["to-string",["get","x"]], STRING]

    Recurses fully into all, any, none, case, match, and any nested expression.
    """
    if not isinstance(expr, list) or not expr:
        return expr

    op = expr[0] if isinstance(expr[0], str) else None

    if op in _COMPARISON_OPS and len(expr) == 3:
        left, right = expr[1], expr[2]
        left  = _coerce_operand(left,  right)
        right = _coerce_operand(right, left)
        return [op, left, right]

    # Recurse into everything else
    return [expr[0]] + [_coerce_filter_comparisons(c) if isinstance(c, list) else c
                        for c in expr[1:]]


def _coerce_operand(operand: Any, other: Any) -> Any:
    """
    If *operand* is a bare ["get", x] (returns "value" type), wrap it with
    ["to-number"] or ["to-string"] according to the type of *other*.
    Works regardless of which side (left or right) the get is on.
    """
    if not isinstance(operand, list) or not operand:
        return operand
    if operand[0] != "get":
        return operand
    # Determine expected type from the OTHER operand
    other_resolved = other
    # Unwrap to-number/to-string wrappers already applied to other side
    if isinstance(other_resolved, list) and other_resolved and other_resolved[0] in ("to-number", "to-string"):
        other_resolved = other_resolved[1] if len(other_resolved) > 1 else other_resolved
    if isinstance(other_resolved, (int, float)):
        return ["to-number", operand]
    if isinstance(other_resolved, str):
        return ["to-string", operand]
    return operand


def _coerce_numeric_expression(expr: Any) -> Any:
    """
    In layout properties that expect a number (text-size, icon-size, etc.),
    wrap any ["get","field"] leaf in output positions with ["to-number"].
    Works for step/interpolate/match/case/coalesce, both orderings of operands.
    """
    if not isinstance(expr, list) or not expr:
        return expr

    op = expr[0] if isinstance(expr[0], str) else None

    if op == "get":
        return ["to-number", expr]

    if op == "interpolate" and len(expr) >= 4:
        # ["interpolate", interp, input, stop, output, stop, output, ...]
        new = ["interpolate", expr[1], expr[2]]  # keep interp + zoom input
        i = 3
        while i < len(expr):
            new.append(expr[i])                          # stop (number) — keep
            if i + 1 < len(expr):
                new.append(_coerce_numeric_output(expr[i + 1]))  # output
            i += 2
        return new

    if op == "step" and len(expr) >= 3:
        # ["step", input, default, stop, output, ...]
        new = ["step", expr[1], _coerce_numeric_output(expr[2])]
        i = 3
        while i < len(expr):
            new.append(expr[i])                          # stop — keep
            if i + 1 < len(expr):
                new.append(_coerce_numeric_output(expr[i + 1]))  # output
            i += 2
        return new

    if op == "match":
        if len(expr) < 4:
            return expr
        new = [op, expr[1]]
        i = 2
        while i + 1 < len(expr):
            new.append(expr[i])                              # label
            new.append(_coerce_numeric_output(expr[i + 1])) # output
            i += 2
        new.append(_coerce_numeric_output(expr[i]))          # default
        return new

    if op == "case":
        # ["case", cond, output, cond, output, ..., default]
        # conditions may contain comparisons with get — coerce those too
        new = ["case"]
        i = 1
        while i + 1 < len(expr):
            new.append(_coerce_filter_comparisons(expr[i]))      # condition
            new.append(_coerce_numeric_output(expr[i + 1]))      # output
            i += 2
        if i < len(expr):
            new.append(_coerce_numeric_output(expr[i]))           # default
        return new

    if op == "coalesce":
        return ["coalesce"] + [_coerce_numeric_output(c) for c in expr[1:]]

    return expr


def _coerce_numeric_output(val: Any) -> Any:
    """Wrap a bare ["get","x"] with to-number; recurse into nested expressions."""
    if isinstance(val, list) and val:
        if val[0] == "get":
            return ["to-number", val]
        return _coerce_numeric_expression(val)
    return val


def _simplify_icon_image(expr: Any) -> Optional[Any]:
    """
    ArcGIS Pro only supports a literal string for icon-image.
    Extract the most representative non-empty output from a
    match/step/case expression.
    Prefer the first non-empty output (most specific) over the most frequent,
    since icon-image outputs tend to be all unique.
    Returns None if no non-empty literal found.
    """
    if isinstance(expr, str):
        return expr if expr else None
    if not isinstance(expr, list):
        return None
    outputs = _collect_expression_outputs(expr)
    non_empty = [o for o in outputs if isinstance(o, str) and o]
    if not non_empty:
        return None
    # Return the first non-empty output (most likely the "default" meaningful value)
    return non_empty[0]


def _count(counters: dict, key: str) -> None:
    counters[key] = counters.get(key, 0) + 1
