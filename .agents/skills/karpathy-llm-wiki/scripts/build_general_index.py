#!/usr/bin/env python3
"""Rebuild wiki/general-index.md: a flat, regenerable list of every recipe
across wiki/vegan-cooking/*.md, with its source article and a one-line
description, for quick lookup without knowing the chapter in advance.

Reconstructed 2026-08-20 after the original script was accidentally deleted.
Safe to rerun any time; fully derived from the wiki/vegan-cooking/*.md files.
"""
import glob
import os
import re

WIKI_DIR = os.path.join("wiki", "vegan-cooking")
OUT_PATH = os.path.join("wiki", "general-index.md")


def extract_items(path):
    text = open(path, encoding="utf-8").read()
    rel = os.path.relpath(path, "wiki").replace(os.sep, "/")
    # Split on H2 headings; skip the "Overview" section.
    sections = re.split(r"^## (.+)$", text, flags=re.M)
    # sections[0] is preamble before first ##; then alternating heading, body
    items = []
    for i in range(1, len(sections), 2):
        heading = sections[i].strip()
        body = sections[i + 1] if i + 1 < len(sections) else ""
        if heading.lower() == "overview":
            continue
        desc_match = re.search(r"^\*(.+?)\*\s*$", body, flags=re.M)
        desc = desc_match.group(1).strip() if desc_match else ""
        items.append((heading, rel, desc))
    return items


def anchor(text):
    text = text.lower()
    text = re.sub(r"[^\w\s-]", "", text)
    text = text.replace(" ", "-")
    return text


def main():
    files = sorted(glob.glob(os.path.join(WIKI_DIR, "*.md")))
    all_items = []
    for f in files:
        all_items.extend(extract_items(f))

    all_items.sort(key=lambda x: x[0].lower())

    lines = [
        "# General Recipe Index",
        "",
        "Flat, regenerable index of every recipe across `wiki/vegan-cooking/*.md`,"
        " for finding a dish without knowing which book/chapter it's in.",
        f"Regenerate with `python3 .agents/skills/karpathy-llm-wiki/scripts/build_general_index.py`.",
        "",
        f"{len(all_items)} items.",
        "",
    ]
    for heading, rel, desc in all_items:
        link = f"vegan-cooking/{os.path.basename(rel)}#{anchor(heading)}"
        if desc:
            lines.append(f"- [{heading}]({link}) — {desc}")
        else:
            lines.append(f"- [{heading}]({link})")

    os.makedirs("wiki", exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")

    print(f"Wrote {OUT_PATH} ({len(all_items)} items)")


if __name__ == "__main__":
    main()
