#!/usr/bin/env python3
"""
Converts unstructured source files (epub, pdf, docx, pptx, xlsx) to Markdown
as the first step of the wiki-building pipeline.

Wraps `markitdown` and patches known gaps in its default output:

  epub   - markitdown flattens the whole spine into one Markdown string and
           never copies embedded images out of the zip. We extract every
           image from the epub archive into images/ next to the .md, and
           strip cross-references to sibling .xhtml files (e.g. links to
           toc.xhtml) since those files were never written to disk and can
           never resolve - the link text is kept, the href is dropped.

  docx/  - by default markitdown truncates embedded images to a bare
  pptx     "data:image/png;base64..." placeholder (docx) or invents a fake
           filename that is never written to disk (pptx). Passing
           --keep-data-uris makes markitdown emit the *real* base64 data;
           we then pull that out into images/ and rewrite the reference to
           a relative path, keeping the .md itself small and readable.

  xlsx   - markitdown's converter (pandas.read_excel -> to_html) does not
           understand merged cells: a merged header (e.g. a year spanning
           four quarter columns) becomes "Unnamed: N" columns and literal
           "NaN" text everywhere else in the range. We read the sheet with
           openpyxl instead, fill every cell of a merged range with its
           top-left value, and render a clean Markdown table ourselves.

  pdf    - markitdown's PDF converter (pdfminer/pdfplumber) is text-only:
           it does not extract embedded raster images or vector figures at
           all, with no placeholder either. There is nothing to patch here
           (no image data is exposed for us to recover); this is a hard
           limitation of the underlying libraries, and the file is
           converted as-is. Figures/diagrams in a PDF are silently lost.

Usage:
    python .agents/skills/markitdown-processor/scripts/convert.py sources/some-file.epub
    python .agents/skills/markitdown-processor/scripts/convert.py sources/some-file.docx markdown/custom-name/
    python .agents/skills/markitdown-processor/scripts/convert.py sources/   # convert every
                                                                          # supported file
                                                                          # in the folder
"""

import argparse
import base64
import re
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Callable

import openpyxl

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp"}
INTERNAL_LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)\s]+\.xhtml[^)]*)\)")
DATA_URI_RE = re.compile(
    r"!\[([^\]]*)\]\(data:image/([\w+.-]+);base64,([A-Za-z0-9+/=]+)\)"
)
EXT_ALIASES = {"jpeg": "jpg", "svg+xml": "svg"}


def run_markitdown(src: Path, md_path: Path, *extra_args: str) -> None:
    subprocess.run(
        ["markitdown", *extra_args, str(src), "-o", str(md_path)], check=True
    )


# --- epub -------------------------------------------------------------


def strip_internal_links(markdown_text: str) -> str:
    return INTERNAL_LINK_RE.sub(lambda m: m.group(1), markdown_text)


def extract_epub_images(epub_path: Path, images_dir: Path) -> int:
    count = 0
    with zipfile.ZipFile(epub_path, "r") as z:
        for name in z.namelist():
            ext = Path(name).suffix.lower()
            if ext not in IMAGE_EXTENSIONS:
                continue
            dest = images_dir / Path(name).name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(z.read(name))
            count += 1
    return count


def convert_epub(src: Path, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    md_path = out_dir / (src.stem + ".md")

    run_markitdown(src, md_path)

    text = md_path.read_text(encoding="utf-8")
    cleaned = strip_internal_links(text)
    if cleaned != text:
        md_path.write_text(cleaned, encoding="utf-8")
        print("  stripped unresolved internal .xhtml links")

    n = extract_epub_images(src, out_dir / "images")
    print(f"  extracted {n} images -> {out_dir / 'images'}")
    return md_path


# --- docx / pptx --------------------------------------------------------


def extract_data_uri_images(markdown_text: str, images_dir: Path) -> tuple[str, int]:
    counter = 0

    def repl(m: re.Match) -> str:
        nonlocal counter
        counter += 1
        alt, subtype, b64 = m.groups()
        ext = EXT_ALIASES.get(subtype.lower(), subtype.lower())
        filename = f"image_{counter:03d}.{ext}"
        images_dir.mkdir(parents=True, exist_ok=True)
        (images_dir / filename).write_bytes(base64.b64decode(b64))
        return f"![{alt}](images/{filename})"

    new_text = DATA_URI_RE.sub(repl, markdown_text)
    return new_text, counter


def convert_office_with_images(src: Path, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    md_path = out_dir / (src.stem + ".md")

    run_markitdown(src, md_path, "--keep-data-uris")

    text = md_path.read_text(encoding="utf-8")
    new_text, n = extract_data_uri_images(text, out_dir / "images")
    if n:
        md_path.write_text(new_text, encoding="utf-8")
    print(f"  extracted {n} images -> {out_dir / 'images'}")
    return md_path


# --- xlsx -----------------------------------------------------------------


def _fill_merged_cells(
    ws, max_fill_ratio: float = 0.5
) -> dict[tuple[int, int], object]:
    """Propagate each merged range's top-left value across its cells, so a
    header like a year spanning four quarter columns stays legible once the
    sheet is flattened into a single-row-per-line Markdown table.

    Wide merges (e.g. a section-title row merged across nearly every column)
    are skipped: repeating that text in every column would bloat the table
    without adding information, so only the top-left cell keeps the value.
    """
    total_cols = ws.max_column or 1
    fill: dict[tuple[int, int], object] = {}
    for merged_range in ws.merged_cells.ranges:
        width = merged_range.max_col - merged_range.min_col + 1
        if width / total_cols > max_fill_ratio:
            continue
        top_left = ws.cell(
            row=merged_range.min_row, column=merged_range.min_col
        ).value
        for row in range(merged_range.min_row, merged_range.max_row + 1):
            for col in range(merged_range.min_col, merged_range.max_col + 1):
                fill[(row, col)] = top_left
    return fill


def _sheet_to_rows(ws) -> list[list[str]]:
    fill = _fill_merged_cells(ws)
    rows: list[list[str]] = []
    for row in ws.iter_rows():
        values = []
        for cell in row:
            value = fill.get((cell.row, cell.column), cell.value)
            values.append("" if value is None else str(value))
        if any(v.strip() for v in values):
            rows.append(values)
    return rows


def _rows_to_markdown_table(rows: list[list[str]]) -> str:
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    col_widths = [max(len(row[i]) for row in rows) for i in range(width)]

    def fmt(row: list[str]) -> str:
        return "| " + " | ".join(c.ljust(w) for c, w in zip(row, col_widths)) + " |"

    header, *body = rows
    lines = [fmt(header), "|" + "|".join("-" * (w + 2) for w in col_widths) + "|"]
    lines.extend(fmt(r) for r in body)
    return "\n".join(lines)


def convert_xlsx(src: Path, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    md_path = out_dir / (src.stem + ".md")

    wb = openpyxl.load_workbook(src, data_only=True)
    sections = []
    for ws in wb.worksheets:
        rows = _sheet_to_rows(ws)
        if not rows:
            continue
        sections.append(f"## {ws.title}\n\n{_rows_to_markdown_table(rows)}")

    md_path.write_text("\n\n".join(sections), encoding="utf-8")
    print(f"  wrote {len(wb.worksheets)} sheet(s), merged cells resolved")
    return md_path


# --- pdf ------------------------------------------------------------------


def convert_pdf(src: Path, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    md_path = out_dir / (src.stem + ".md")
    run_markitdown(src, md_path)
    print("  note: text only - embedded images/figures are not extracted")
    return md_path


# --- fallback ---------------------------------------------------------


def convert_generic(src: Path, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    md_path = out_dir / (src.stem + ".md")
    run_markitdown(src, md_path)
    return md_path


CONVERTERS: dict[str, Callable[[Path, Path], Path]] = {
    ".epub": convert_epub,
    ".pdf": convert_pdf,
    ".docx": convert_office_with_images,
    ".pptx": convert_office_with_images,
    ".xlsx": convert_xlsx,
}


def convert_one(src: Path, out_dir: Path) -> None:
    converter = CONVERTERS.get(src.suffix.lower(), convert_generic)
    print(f"Converting {src.name} ({converter.__name__})")
    md_path = converter(src, out_dir)
    print(f"  -> {md_path}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="Source file or directory")
    parser.add_argument(
        "out_root",
        type=Path,
        nargs="?",
        default=Path("markdown"),
        help="Output root directory (default: markdown/). Each source file "
        "gets its own subfolder named after its stem.",
    )
    args = parser.parse_args()

    if args.source.is_dir():
        files = [
            f
            for f in sorted(args.source.iterdir())
            if f.is_file() and f.suffix.lower() in CONVERTERS
        ]
        if not files:
            print(f"No supported files found in {args.source}")
            return 1
        for f in files:
            convert_one(f, args.out_root / f.stem)
    else:
        convert_one(args.source, args.out_root / args.source.stem)

    return 0


if __name__ == "__main__":
    sys.exit(main())
