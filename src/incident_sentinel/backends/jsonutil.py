"""Helpers for coaxing a clean JSON object out of a model's text reply."""

from __future__ import annotations


def strip_code_fences(text: str) -> str:
    """Remove Markdown ```json fences if the model wrapped its output."""
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.split("\n", 1)[-1] if "\n" in stripped else stripped
        if stripped.endswith("```"):
            stripped = stripped[: stripped.rfind("```")]
    return stripped.strip()


def extract_object(text: str) -> str:
    """Return the outermost ``{...}`` block from ``text``.

    Falls back to the fence-stripped text if no balanced object is found.
    """
    cleaned = strip_code_fences(text)
    start = cleaned.find("{")
    if start == -1:
        return cleaned
    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(cleaned)):
        char = cleaned[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return cleaned[start : index + 1]
    return cleaned[start:]
