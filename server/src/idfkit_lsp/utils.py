"""Shared utilities for text manipulation and position calculations."""

from __future__ import annotations

import ast


def get_line_text(source: str, line: int) -> str:
    """Extract a single line from source by 0-based line number."""
    lines = source.splitlines()
    if 0 <= line < len(lines):
        return lines[line]
    return ""


def get_word_at_position(line: str, character: int) -> tuple[str, int, int]:
    """Extract the word at or immediately before the cursor position.

    Returns (word, start_col, end_col).
    """
    if character > len(line):
        character = len(line)
    start = character
    while start > 0 and (line[start - 1].isalnum() or line[start - 1] == "_"):
        start -= 1
    end = character
    while end < len(line) and (line[end].isalnum() or line[end] == "_"):
        end += 1
    return line[start:end], start, end


def safe_parse(source: str) -> ast.Module | None:
    """Parse Python source, returning None on SyntaxError."""
    try:
        return ast.parse(source)
    except SyntaxError:
        return None
