#!/usr/bin/env python3
"""
Bridges markitdown-processor output into the raw/ format expected by the
karpathy-llm-wiki skill (see .agents/skills/karpathy-llm-wiki/SKILL.md and
references/raw-template.md).

convert.py produces markdown/<stem>/<stem>.md (+ optional images/), with no
metadata header, no topic assignment, and no date-slug filename. This script
wraps one such converted document into karpathy-llm-wiki's raw entry format:

    raw/<topic>/YYYY-MM-DD-<slug>.md   -- title + Source/Collected/Published
                                           header + the converted content
    raw/<topic>/<slug>/images/         -- sidecar copy of the images/ folder,
                                           if any (karpathy-llm-wiki's raw/
                                           format is text-only and has no
                                           field for images; this keeps them
                                           from being lost without pretending
                                           the wiki skill understands them)

One raw entry per converted document (no chunking) - the wiki skill's own
Compile step is what synthesizes a document down into wiki articles.

Usage:
    python .agents/skills/markitdown-processor/scripts/to_wiki_raw.py \\
        markdown/<stem>/ <topic> \\
        --title "Human Title" \\
        --source "origin description, e.g. original filename or URL" \\
        [--published YYYY-MM-DD]   # omit for "Unknown"
        [--collected YYYY-MM-DD]   # defaults to today
        [--slug custom-slug]       # defaults to a slugified title
        [--raw-root raw/]          # defaults to raw/
"""

import argparse
import re
import shutil
import sys
from datetime import date
from pathlib import Path


def slugify(text: str, max_len: int = 60) -> str:
    slug = text.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug).strip("-")
    return slug[:max_len].rstrip("-")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "markdown_dir", type=Path, help="A markdown/<stem>/ folder from convert.py"
    )
    parser.add_argument("topic", help="Topic subdirectory under raw/, e.g. cooking")
    parser.add_argument("--title", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--published", default="Unknown")
    parser.add_argument("--collected", default=date.today().isoformat())
    parser.add_argument("--slug", default=None)
    parser.add_argument("--raw-root", type=Path, default=Path("raw"))
    args = parser.parse_args()

    md_files = list(args.markdown_dir.glob("*.md"))
    if len(md_files) != 1:
        print(
            f"Expected exactly one .md file in {args.markdown_dir}, found {len(md_files)}",
            file=sys.stderr,
        )
        return 1
    src_md = md_files[0]

    slug = args.slug or slugify(args.title)
    topic_dir = args.raw_root / args.topic
    topic_dir.mkdir(parents=True, exist_ok=True)
    dest_md = topic_dir / f"{args.collected}-{slug}.md"

    content = src_md.read_text(encoding="utf-8")

    images_src = args.markdown_dir / "images"
    if images_src.is_dir() and any(images_src.iterdir()):
        images_dest = topic_dir / slug / "images"
        images_dest.parent.mkdir(parents=True, exist_ok=True)
        if images_dest.exists():
            shutil.rmtree(images_dest)
        shutil.copytree(images_src, images_dest)
        content = content.replace("(images/", f"({slug}/images/")
        print(f"  carried {len(list(images_dest.iterdir()))} images -> {images_dest}")

    header = (
        f"# {args.title}\n\n"
        f"> Source: {args.source}\n"
        f"> Collected: {args.collected}\n"
        f"> Published: {args.published}\n\n"
    )
    dest_md.write_text(header + content, encoding="utf-8")
    print(f"-> {dest_md}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
