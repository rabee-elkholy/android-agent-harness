"""Mask Java/Kotlin comments and literals while preserving source offsets."""
from __future__ import annotations


def mask_comments_and_strings(text: str) -> str:
    result = list(text)
    i = 0
    size = len(text)
    while i < size:
        start = i
        if text.startswith("//", i):
            end = text.find("\n", i + 2)
            i = size if end < 0 else end
        elif text.startswith("/*", i):
            depth = 1
            i += 2
            while i < size and depth:
                if text.startswith("/*", i):
                    depth += 1
                    i += 2
                elif text.startswith("*/", i):
                    depth -= 1
                    i += 2
                else:
                    i += 1
        elif text.startswith('"""', i):
            end = text.find('"""', i + 3)
            i = size if end < 0 else end + 3
        elif text[i] in "\"'":
            quote = text[i]
            i += 1
            while i < size:
                char = text[i]
                i += 1
                if char == "\\":
                    i = min(i + 1, size)
                elif char == quote:
                    break
        else:
            i += 1
            continue
        result[start:i] = [char if char in "\r\n" else " " for char in text[start:i]]
    return "".join(result)
