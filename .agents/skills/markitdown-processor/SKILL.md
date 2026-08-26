---
name: markitdown-processor
description: "Use when converting unstructured source files (epub, pdf, docx, pptx, xlsx) into clean Markdown as the first step of a wiki-building pipeline. Triggers: converting sources/ files to markdown, 'convert this epub/pdf/docx/pptx/xlsx', processing documents with markitdown, or any mention of 'markitdown-processor'."
---

# Markitdown Processor

Converts unstructured source files into Markdown, patching known gaps in `markitdown`'s default output so the result is actually usable as wiki source material. This is step one of a larger pipeline: raw files in → clean per-source Markdown + extracted images out. It does not compile or structure a wiki — that is a separate downstream step.

## Prerequisite

Requires the `markitdown` CLI (`pip install markitdown`) plus `openpyxl` for the xlsx path. Verify with `markitdown --version` before running; if missing, ask the user to install it rather than silently falling back to something else.

## Usage

```
python .agents/skills/markitdown-processor/scripts/convert.py <source> [out_root]
```

- `<source>` — a single file, or a directory (batch-converts every supported file inside it: `.epub`, `.pdf`, `.docx`, `.pptx`, `.xlsx`).
- `[out_root]` — output root directory, default `markdown/`. Each source file gets its own subfolder named after its stem: `markdown/<stem>/<stem>.md`, with an `images/` subfolder alongside it when images were extracted.

Typical call for this project: `python .agents/skills/markitdown-processor/scripts/convert.py sources/`.

## What it fixes per format

Plain `markitdown` silently drops or mangles content in format-specific ways. Do not use the bare `markitdown` CLI directly for these formats — always go through this script.

- **epub** — `markitdown` flattens the whole spine into one Markdown string and never copies embedded images out of the zip; internal links (e.g. `toc.xhtml`) point to files that were never written to disk. This script extracts every image from the epub archive into `images/`, and strips those dangling `.xhtml` cross-references (keeping the link text, dropping the href).
- **docx / pptx** — by default `markitdown` truncates embedded images to a bare `data:image/png;base64...` placeholder (docx) or invents a filename that's never written to disk (pptx). The script calls `markitdown --keep-data-uris` to get the real base64 data, then extracts it into `images/` and rewrites references to relative paths — keeping the `.md` itself small.
- **xlsx** — `markitdown`'s converter (`pandas.read_excel` → `to_html`) doesn't understand merged cells: a header merged across several columns becomes `Unnamed: N` columns, and every other cell in a merged range renders the literal text `NaN`. The script reads the sheet with `openpyxl` instead and fills narrow merges (e.g. a year spanning four quarter columns) across their cells, while leaving wide section-header merges only in their top-left cell (to avoid repeating a title across dozens of columns).
- **pdf** — `markitdown`'s PDF path (pdfminer/pdfplumber) is text-only. It does not extract embedded raster images or vector figures at all, and exposes no image data for this script to recover — this is a hard limitation, not something patched. Figures/diagrams in a PDF are silently lost; say so explicitly if the user asks about a PDF with figures, don't claim full fidelity.

## Verifying output

After conversion, before reporting success:
1. Skim the generated `.md` for the format-specific failure mode above (garbled tables for xlsx, dangling links for epub, etc.).
2. For files with images, confirm every `![...](images/...)` reference resolves to an actual file on disk — a quick grep + existence check catches silent extraction failures.
3. For xlsx, check that section-header rows aren't repeating their text across every column (a sign the merge-fill ratio needs adjusting for that sheet's layout).

## Known non-goals

- No OCR — scanned/image-only PDFs will produce little or no text; that's outside this script's scope.
- `.xls` (legacy binary format) and other extensions fall back to plain `markitdown` with no post-processing; add a converter branch if a gap surfaces there.
- Does not deduplicate or restructure content — one input file always maps to one output folder, unmodified in intent from the source.

## Feeding into karpathy-llm-wiki

`markdown/<stem>/<stem>.md` is not yet valid input for the `karpathy-llm-wiki` skill: that skill's `raw/` expects one Markdown file per source with a `# Title` + `> Source / Collected / Published` header (see its `references/raw-template.md`), filed under `raw/<topic>/YYYY-MM-DD-<slug>.md`. It also has no concept of images.

`scripts/to_wiki_raw.py` bridges the two: it wraps one converted document with that header and writes it to `raw/<topic>/...`, copying any `images/` folder alongside as `raw/<topic>/<slug>/images/` and rewriting the image references to match (karpathy-llm-wiki itself ignores these — they just ride along so nothing is lost).

```
python .agents/skills/markitdown-processor/scripts/to_wiki_raw.py \
    markdown/<stem>/ <topic> \
    --title "Human Title" \
    --source "origin description, e.g. original filename" \
    [--published YYYY-MM-DD]   # omit for "Unknown"
```

One raw entry per converted document — no chunking. Picking `<topic>` and `--title`/`--source`/`--published` is an editorial judgment call (infer from the document's own metadata/filename where possible); this script does not guess them for you. Note this project's `raw/` name is already taken by `karpathy-llm-wiki`'s own convention — original binary uploads live in `sources/` instead, which is what this skill's `convert.py` should be pointed at.

After bridging, invoke the `karpathy-llm-wiki` skill's Ingest/Compile step on each new `raw/<topic>/*.md` entry to actually produce `wiki/` articles — that synthesis step belongs to that skill, not to this one.
