"""JSON extraction from noisy model output."""

from __future__ import annotations

import json

from incident_sentinel.backends.jsonutil import extract_object, strip_code_fences


def test_strip_fences():
    assert strip_code_fences('```json\n{"a": 1}\n```') == '{"a": 1}'


def test_extract_object_from_prose():
    text = 'Here is the report:\n{"title": "x", "n": 2}\nThanks!'
    assert json.loads(extract_object(text)) == {"title": "x", "n": 2}


def test_extract_handles_nested_and_strings():
    text = '{"a": {"b": 1}, "s": "has } brace"}'
    assert json.loads(extract_object(text)) == {"a": {"b": 1}, "s": "has } brace"}


def test_extract_from_fenced_block():
    assert json.loads(extract_object('```\n{"ok": true}\n```')) == {"ok": True}
