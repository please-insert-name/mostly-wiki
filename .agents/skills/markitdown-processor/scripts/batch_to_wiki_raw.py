#!/usr/bin/env python3
"""
Batch companion to to_wiki_raw.py: bridges every markdown/<stem>/ folder in a
directory into raw/<topic>/ at once, auto-filling --title/--source/--published
from the metadata header convert.py's epub converter writes at the top of
each .md file (**Title:**, **Authors:**, **Date:**).

Only useful when that metadata is present and trustworthy (epub sources) and
one topic covers the whole batch - for anything needing per-book judgment
(mixed topics, missing/wrong metadata, non-epub sources), use to_wiki_raw.py
directly instead.

Usage:
    python .agents/skills/markitdown-processor/scripts/batch_to_wiki_raw.py \\
        markdown/ vegan-cooking [--raw-root raw/] [--skip stem1,stem2]
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path

META_RE = re.compile(r"^\*\*(Title|Authors|Date|Publisher):\*\*\s*(.+)$", re.MULTILINE)
SCRIPT_DIR = Path(__file__).resolve().parent


def slugify(text: str, max_len: int = 60) -> str:
    slug = text.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug).strip("-")
    return slug[:max_len].rstrip("-")


def parse_metadata(md_path: Path) -> dict:
    head = md_path.read_text(encoding="utf-8")[:2000]
    return {k: v.strip() for k, v in META_RE.findall(head)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("markdown_root", type=Path)
    parser.add_argument("topic")
    parser.add_argument("--raw-root", type=Path, default=Path("raw"))
    parser.add_argument("--skip", default="", help="Comma-separated stems to skip")
    args = parser.parse_args()

    skip = {s.strip() for s in args.skip.split(",") if s.strip()}
    book_dirs = sorted(
        d for d in args.markdown_root.iterdir() if d.is_dir() and d.name not in skip
    )

    for book_dir in book_dirs:
        md_files = list(book_dir.glob("*.md"))
        if len(md_files) != 1:
            print(f"SKIP {book_dir.name}: expected 1 .md file, found {len(md_files)}")
            continue

        meta = parse_metadata(md_files[0])
        title = meta.get("Title", book_dir.name)
        authors = meta.get("Authors", "")
        date = meta.get("Date", "")
        publisher = meta.get("Publisher", "")

        source_bits = [f"epub: {title}"]
        if authors:
            source_bits.append(f"by {authors}")
        if publisher:
            source_bits.append(f"({publisher})")
        source = " ".join(source_bits)

        published = date if date else "Unknown"
        slug = slugify(title)

        cmd = [
            sys.executable,
            str(SCRIPT_DIR / "to_wiki_raw.py"),
            str(book_dir),
            args.topic,
            "--title", title,
            "--source", source,
            "--published", published,
            "--slug", slug,
            "--raw-root", str(args.raw_root),
        ]
        subprocess.run(cmd, check=True)

    return 0


if __name__ == "__main__":
    sys.exit(main())
