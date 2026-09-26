#!/usr/bin/env python3
"""Fail when a repository-relative Markdown link points at a missing file."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse


LINK_RE = re.compile(r"(?<!!)\[[^\]]*\]\(([^)]*)\)")


def markdown_files(paths: list[str]) -> list[Path]:
    files: list[Path] = []
    for raw_path in paths:
        path = Path(raw_path)
        if path.is_dir():
            files.extend(path.rglob("*.md"))
        elif path.suffix == ".md":
            files.append(path)
    return files


def local_destination(raw_destination: str) -> str | None:
    destination = raw_destination.strip().split(maxsplit=1)[0] if raw_destination.strip() else ""
    if destination.startswith("<") and destination.endswith(">"):
        destination = destination[1:-1]

    parsed = urlparse(destination)
    if not destination or destination.startswith("#") or parsed.scheme or destination.startswith("//"):
        return None

    return unquote(destination.split("#", maxsplit=1)[0].split("?", maxsplit=1)[0])


def main() -> int:
    files = markdown_files(sys.argv[1:] or ["README.md", "docs", "services"])
    errors: list[str] = []

    for markdown_file in files:
        for line_number, line in enumerate(markdown_file.read_text().splitlines(), start=1):
            for match in LINK_RE.finditer(line):
                destination = local_destination(match.group(1))
                if destination and not (markdown_file.parent / destination).exists():
                    errors.append(f"{markdown_file}:{line_number}: missing local link target: {destination}")

    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
