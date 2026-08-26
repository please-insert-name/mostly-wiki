#!/usr/bin/env python3
"""Build/query wiki/retrieval-index.db: a derived SQLite index for fast,
structured pre-filtering over a karpathy-llm-wiki (see
.agents/skills/karpathy-llm-wiki and .agents/skills/retrieval-index/SKILL.md).

The wiki's markdown articles under wiki/<topic>/ remain the only source of
truth. This database is a disposable, fully regeneratable artifact derived
from them — never hand-edited, never authoritative beyond what it can prove
from explicit or structural facts in the source text.

CURRENT STATE: implemented for wiki/vegan-cooking (schema approved
2026-08-25, extended 2026-08-26 after a 182-question test pass — see
../SKILL.md "Known limitations" for what this index can and can't answer).
If this script is reused for a different topic directory, treat SCHEMA_SQL
and extract_records() as needing a fresh setup pass: collect example
questions, inspect the wiki, propose a schema, get it approved, THEN adapt:
  - SCHEMA_SQL: CREATE TABLE statements for the approved schema
  - extract_records(wiki_root): walks wiki/<topic>/*.md and yields
    (table_name, {column: value}) rows matching SCHEMA_SQL

Every item-level table should carry an `article` (path relative to wiki/)
and `anchor` (markdown heading anchor) column at minimum, so a query result
can always be traced back to the exact source section.

Standard shape (see ../SKILL.md): an `items` table for structured facts plus
an `items_fts` FTS5 virtual table (title, body, item_id UNINDEXED) for
free-text matching on questions that don't reduce to exact filters. `body`
must be the section's actual source text verbatim, never an LLM-authored
summary. Populate both in the same extraction pass so they stay in sync.

Usage:
    python retrieval_index.py rebuild [wiki_root]
        Drop + recreate every table, re-extract from wiki/, repopulate.
        Full rebuild only, no incremental upsert. Safe to rerun any time,
        e.g. after every karpathy-llm-wiki ingest.

    python retrieval_index.py query "<SELECT ...>" [wiki_root]
        Run a read-only query against the index and print the results as
        a simple pipe-delimited table. Only SELECT statements are allowed.

    python retrieval_index.py classify <category> '<json payload>' [wiki_root]
        additional-information-retrieval: record LLM classification results
        for one category (see ../SKILL.md). payload is the JSON directly,
        or `@<path>` to read it from a file (use this for large batches —
        an inline payload can exceed the OS command-line length limit):
          {"tags": [{"ingredient_id": int, "tag": str,
                     "confidence": "explicit"|"inferred"}, ...],
           "classified_item_ids": [int, ...]}
        Insert-only, incremental-safe — never deletes existing tags.

    python retrieval_index.py reset-category <category> [wiki_root]
        Wipe ingredient_tags/classified_items for one category (e.g. after
        improving that category's classification rules), so it can be
        cleanly reclassified from scratch. Other categories are untouched.

wiki_root defaults to "wiki" (relative to the current working directory).
"""
import hashlib
import json
import re
import sqlite3
import sys
from pathlib import Path

DB_FILE_NAME = "retrieval-index.db"

# --- Schema (approved 2026-08-25 for wiki/vegan-cooking) -----------------
# One row per recipe in `items`, one row per ingredient bullet in
# `item_ingredients`, full-text search over title+body in `items_fts`.
# num_ingredients/num_steps are mechanical counts (not judgment calls);
# yield_text/cooking_time_text/calories_text/dietary_tags are stored only
# when literally present in the source text (see ../SKILL.md Principles).
# Tables extract_records() populates from the wiki markdown. Dropped and
# fully recreated on every `rebuild` (see rebuild(), which treats this list
# as authoritative for what gets dropped). items/item_ingredients use
# content-derived, deterministic ids (see _stable_id) rather than plain
# autoincrement specifically so that `rebuild` — which must stay cheap and
# safe to rerun after every karpathy-llm-wiki ingest — never invalidates the
# foreign keys held by the LLM-derived tables below (ingredient_tags,
# classified_items), which are expensive to (re)populate and are therefore
# NOT dropped by `rebuild` (see ADDITIONAL_INFO_SCHEMA_SQL).
MECHANICAL_TABLES = ["items", "item_ingredients", "items_fts"]

SCHEMA_SQL = """
CREATE TABLE items (
    id INTEGER PRIMARY KEY,   -- stable hash of (article, anchor) — see _stable_id
    title TEXT NOT NULL,
    article TEXT NOT NULL,   -- path relative to wiki/, e.g. "vegan-cooking/foo.md"
    anchor TEXT NOT NULL,    -- markdown heading anchor within the article
    book TEXT,
    author TEXT,
    chapter TEXT,
    description TEXT,
    yield_text TEXT,
    serves_min INTEGER,       -- parsed from yield_text, only when it's a people-count
    serves_max INTEGER,       -- (not a volume/weight/piece yield like "2 quarts")
    cooking_time_text TEXT,
    prep_minutes INTEGER,     -- parsed from cooking_time_text where present (~3% of items)
    cook_minutes INTEGER,
    total_minutes INTEGER,    -- explicit "Total Time" if stated, else prep+cook when both known
    calories_text TEXT,
    dietary_tags TEXT,
    notes_text TEXT,          -- concatenated *Note:*/*Tip:*/*Notes:*/*Cooking Tip:* lines, verbatim
    num_ingredients INTEGER,
    num_steps INTEGER
);

CREATE TABLE item_ingredients (
    id INTEGER PRIMARY KEY,   -- stable hash of (article, anchor, position, line_text)
    item_id INTEGER NOT NULL REFERENCES items(id),
    sub_component TEXT,
    line_text TEXT NOT NULL
);

-- Free-text search: title = heading text, body = section's source text
-- verbatim (never an LLM-authored summary), item_id = join key to items.id.
CREATE VIRTUAL TABLE items_fts USING fts5(
    title,
    body,
    item_id UNINDEXED
);
"""

# --- additional-information-retrieval companion tables --------------------
# Populated by the `classify`/`mark-classified` commands, NOT by `rebuild`
# (see rebuild()'s docstring). Unlike the tables above, these hold LLM
# judgments, not facts mechanically read off the page — every tag carries a
# `confidence` and is traceable to the exact item_ingredients row that
# justified it via `ingredient_id`, never a freestanding claim. See
# ../SKILL.md for the full workflow and the CLAUDE.md '## ADDITIONAL
# INFORMATION' category-definition format this is driven by.
ADDITIONAL_INFO_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS ingredient_tags (
    id INTEGER PRIMARY KEY,
    ingredient_id INTEGER NOT NULL REFERENCES item_ingredients(id),
    category TEXT NOT NULL,   -- e.g. "allergen"
    tag TEXT NOT NULL,        -- e.g. "nuts", "gluten", "soy"
    confidence TEXT NOT NULL  -- "explicit" (the ingredient names it directly)
                               -- "inferred" (world knowledge needed, e.g.
                               -- "soy sauce" usually contains wheat/gluten)
);

-- One row per (item, category) once every ingredient of that item has been
-- run through classification for that category — regardless of whether any
-- tag was actually assigned. Absence of a tag is only meaningful evidence
-- of "not present" when the item is ALSO marked here; an item missing from
-- classified_items for a category has simply not been checked yet.
CREATE TABLE IF NOT EXISTS classified_items (
    item_id INTEGER NOT NULL REFERENCES items(id),
    category TEXT NOT NULL,
    PRIMARY KEY (item_id, category)
);
"""

_DIETARY_VOCAB = [
    "Gluten-Free Option",
    "Gluten-Free",
    "Soy-Free Option",
    "Soy-Free",
    "Nut-Free Option",
    "Nut-Free",
    "Oil-Free",
]

# Anchored at (stripped) line start so prose that merely contains these
# words ("this recipe makes a great lunch") doesn't get mistaken for a
# yield/time label line.
_YIELD_LINE_RE = re.compile(
    r"^\*?\s*(?:Serves\s+\d|Servings?\s*:?\s*\d|Yields?\s*:?\s*.*?\d|Makes\s*:?\s*\d)",
    re.I,
)
_TIME_LINE_RE = re.compile(
    r"\b(?:Prep\s*Time|Cook\s*Time|Total\s*Time|Ready\s*[Ii]n)\s*:", re.I
)
_CALORIE_RE = re.compile(r"^.*\d[\d,]*\s*(?:kcal\b|calories?\b).*$|^.*\bcalories?\s*:\s*\d.*$", re.M | re.I)
_ITALIC_LINE_RE = re.compile(r"^\*(.+?)\*\s*$")
_STEP_RE = re.compile(r"^\d+\.\s", re.M)
_BULLET_RE = re.compile(r"^-\s+(.+)$", re.M)
_INLINE_LABEL_RE = re.compile(r"^\*\*([^*]+?):\*\*\s*(.+)$", re.M)
_BOLD_LABEL_RE = re.compile(r"^\*\*([^*]+?)\*\*\s*$", re.M)
_NOTE_LINE_RE = re.compile(
    r"^\*(?:Note|Notes|Tip|Cooking Tip|Pro Tip)\s*:\s*(.+?)\*\s*$", re.M | re.I
)

# People-count only — deliberately narrower than _YIELD_LINE_RE so a plain
# quantity/piece yield ("Makes: 2 quarts", "Yield: 1 large cake") doesn't get
# misread as a serving count.
_SERVES_NUM_RE = re.compile(
    r"(?:Serves?\s*:?\s*|Servings?\s*:?\s*)(\d+)(?:\s*(?:to|[–-])\s*(\d+))?"
    r"|(\d+)(?:\s*(?:to|[–-])\s*(\d+))?\s*servings?\b",
    re.I,
)
_PREP_MIN_RE = re.compile(r"Prep\s*Time\s*:\s*(\d+)(?:\s*to\s*\d+)?\s*min", re.I)
_COOK_MIN_RE = re.compile(r"Cook\s*Time\s*:\s*(\d+)(?:\s*to\s*\d+)?\s*min", re.I)
_TOTAL_MIN_RE = re.compile(r"Total\s*Time\s*:\s*(\d+)(?:\s*to\s*\d+)?\s*min", re.I)


def _parse_serves(yield_text):
    if not yield_text:
        return None, None
    m = _SERVES_NUM_RE.search(yield_text)
    if not m:
        return None, None
    lo = m.group(1) or m.group(3)
    hi = m.group(2) or m.group(4) or lo
    return int(lo), int(hi)


def _parse_times(cooking_time_text):
    if not cooking_time_text:
        return None, None, None
    prep_m = _PREP_MIN_RE.search(cooking_time_text)
    cook_m = _COOK_MIN_RE.search(cooking_time_text)
    total_m = _TOTAL_MIN_RE.search(cooking_time_text)
    prep = int(prep_m.group(1)) if prep_m else None
    cook = int(cook_m.group(1)) if cook_m else None
    if total_m:
        total = int(total_m.group(1))
    elif prep is not None and cook is not None:
        total = prep + cook
    else:
        total = None
    return prep, cook, total


def _stable_id(*parts: str) -> int:
    """Deterministic id derived from content, not autoincrement — so that a
    mechanical `rebuild` (drop + recreate items/item_ingredients) doesn't
    invalidate the foreign keys held by ingredient_tags/classified_items,
    which are expensive to (re)populate and therefore not rebuilt. Same
    content -> same id across reruns; changed content -> a new id, which
    correctly orphans any stale classification (cleaned up by rebuild()).
    """
    digest = hashlib.sha1("\x1f".join(parts).encode("utf-8")).hexdigest()
    return int(digest[:15], 16)  # 60 bits, well within SQLite's signed 64-bit id range


def _anchor(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^\w\s-]", "", text)
    text = text.replace(" ", "-")
    return text


def _parse_front_matter(preamble: str, h1: str):
    """Return (book, author) from whichever front-matter convention this
    article uses. Three conventions exist across this wiki's ingest history:
      1. '> Source: [Book](path) by Author'           (majority of books)
      2. '> Raw: [Book](path)' + '> Sources: Author, Date'  (earliest books)
      3. no blockquote metadata; book name in the H1 parenthetical, e.g.
         '# Drinks (La Vida Verde)', author not recoverable structurally
    """
    m = re.search(r"^> Source:\s*\[(.+?)\]\([^)]*\)(?:\s+by\s+(.+))?\s*$", preamble, re.M)
    if m:
        return m.group(1).strip(), (m.group(2).strip() if m.group(2) else None)

    m_book = re.search(r"^> Raw:\s*\[(.+?)\]\([^)]*\)\s*$", preamble, re.M)
    if m_book:
        author = None
        m_auth = re.search(r"^> Sources?:\s*([^,\n]+)", preamble, re.M)
        if m_auth:
            author = m_auth.group(1).strip()
        return m_book.group(1).strip(), author

    m_paren = re.search(r"\(([^()]+)\)\s*$", h1.strip())
    if m_paren:
        return m_paren.group(1).strip(), None

    return None, None


def _extract_header_fields(header: str):
    """From the text before the ingredients zone, pull yield/cooking-time/
    description without assuming which comes first (order varies across the
    wiki's ingest history — see _parse_front_matter for why)."""
    yield_text = None
    cooking_time_text = None
    desc_lines = []
    for line in header.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        bare = stripped.strip("*").strip()
        if yield_text is None and _YIELD_LINE_RE.match(stripped):
            yield_text = bare
            continue
        if cooking_time_text is None and _TIME_LINE_RE.search(stripped):
            cooking_time_text = bare
            continue
        italic = _ITALIC_LINE_RE.match(stripped)
        desc_lines.append(italic.group(1).strip() if italic else stripped)
    description = " ".join(desc_lines).strip() or None

    return description, yield_text, cooking_time_text


def _extract_ingredients(block: str):
    """Yield (sub_component, line_text) for each ingredient in the zone
    between the ingredients marker and '**Method**'.

    Handles three conventions found in this wiki:
    - the standard template: '- bullet' lines, optionally grouped under a
      lone '*Sub-component*' italic line or a '**Sub-component**' bold line;
    - an older, sparser template (~3% of articles, from the earliest-
      ingested books) with no bullets at all: a bold inline label like
      '**Salad:** 1 can chickpeas, 1 tsp oil, ...' where everything after
      the colon is one comma-separated blob. That blob is stored verbatim
      as a single line_text (not split on commas — nested parenthetical
      unit conversions like "(15 oz/425 g)" make comma-splitting unsafe,
      and LIKE/FTS matching against the whole blob still works for
      ingredient-presence filtering).
    """
    sub_component = None
    for line in block.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        bullet = _BULLET_RE.match(stripped)
        if bullet:
            yield sub_component, bullet.group(1).strip()
            continue
        inline = _INLINE_LABEL_RE.match(stripped)
        if inline:
            label, rest = inline.group(1).strip(), inline.group(2).strip()
            yield (None if label.lower() == "ingredients" else label), rest
            continue
        italic = _ITALIC_LINE_RE.match(stripped)
        if italic:
            sub_component = italic.group(1).strip()
            continue
        bold = _BOLD_LABEL_RE.match(stripped)
        if bold and bold.group(1).strip().lower() != "ingredients":
            sub_component = bold.group(1).strip()


def extract_records(wiki_root: Path):
    """Walk wiki/vegan-cooking/*.md, split each file into '## ' recipe
    sections (skipping 'Overview'), and yield items/item_ingredients/
    items_fts rows for each."""
    for path in sorted((wiki_root / "vegan-cooking").glob("*.md")):
        text = path.read_text(encoding="utf-8")
        article = f"vegan-cooking/{path.name}"

        h1_m = re.match(r"^#\s+(.+)$", text, re.M)
        h1 = h1_m.group(1).strip() if h1_m else path.stem

        first_h2 = re.search(r"^## ", text, re.M)
        preamble = text[: first_h2.start()] if first_h2 else text
        book, author = _parse_front_matter(preamble, h1)
        chapter = re.sub(r"\s*\([^()]*\)\s*$", "", h1).strip()

        sections = re.split(r"^## (.+)$", text, flags=re.M)
        for i in range(1, len(sections), 2):
            title = sections[i].strip()
            body = sections[i + 1] if i + 1 < len(sections) else ""
            if title.lower() == "overview":
                continue

            method_m = re.search(r"\*\*Method\*\*", body)
            search_zone = body[: method_m.start() if method_m else None]
            ing_m = re.search(r"^\*\*Ingredients\*\*\s*$", search_zone, re.M)
            if ing_m is None:
                # Older/sparser templates: no standalone "**Ingredients**"
                # marker. Ingredients start either at the first inline bold
                # label ("**Salad:** ...") or the first standalone bold
                # sub-component header ("**Salad**") — whichever comes
                # first (see _extract_ingredients docstring).
                candidates = [
                    m for m in (
                        _INLINE_LABEL_RE.search(search_zone),
                        _BOLD_LABEL_RE.search(search_zone),
                        _BULLET_RE.search(search_zone),
                    )
                    if m is not None
                ]
                ing_m = min(candidates, key=lambda m: m.start()) if candidates else None
            ing_start = ing_m.start() if ing_m else None
            header = body[:ing_start] if ing_start is not None else body
            if ing_start is not None:
                ing_block = body[ing_start : method_m.start() if method_m else None]
            else:
                ing_block = ""
            method_block = body[method_m.end() :] if method_m else ""

            description, yield_text, cooking_time_text = _extract_header_fields(header)

            calorie_m = _CALORIE_RE.search(body)
            calories_text = calorie_m.group(0).strip(" *") if calorie_m else None

            search_scope = description or ""
            tags = [t for t in _DIETARY_VOCAB if t.lower() in search_scope.lower()]
            # collapse "X Option" duplicates when the bare tag was also matched
            tags = [t for t in tags if not any(t != o and t in o for o in tags)]
            dietary_tags = ", ".join(dict.fromkeys(tags)) or None

            notes = _NOTE_LINE_RE.findall(body)
            notes_text = " / ".join(n.strip() for n in notes) or None

            serves_min, serves_max = _parse_serves(yield_text)
            prep_minutes, cook_minutes, total_minutes = _parse_times(cooking_time_text)

            ingredients = list(_extract_ingredients(ing_block))
            num_ingredients = len(ingredients)
            num_steps = len(_STEP_RE.findall(method_block))

            anchor = _anchor(title)
            item_id = _stable_id(article, anchor)

            yield (
                "items",
                {
                    "id": item_id,
                    "title": title,
                    "article": article,
                    "anchor": anchor,
                    "book": book,
                    "author": author,
                    "chapter": chapter,
                    "description": description,
                    "yield_text": yield_text,
                    "serves_min": serves_min,
                    "serves_max": serves_max,
                    "cooking_time_text": cooking_time_text,
                    "prep_minutes": prep_minutes,
                    "cook_minutes": cook_minutes,
                    "total_minutes": total_minutes,
                    "calories_text": calories_text,
                    "dietary_tags": dietary_tags,
                    "notes_text": notes_text,
                    "num_ingredients": num_ingredients,
                    "num_steps": num_steps,
                },
            )
            for position, (sub_component, line_text) in enumerate(ingredients):
                yield (
                    "item_ingredients",
                    {
                        "id": _stable_id(article, anchor, str(position), line_text),
                        "item_id": item_id,
                        "sub_component": sub_component,
                        "line_text": line_text,
                    },
                )
            yield (
                "items_fts",
                {"title": title, "body": body.strip(), "item_id": item_id},
            )


def rebuild(wiki_root: Path) -> None:
    """Drop + recreate items/item_ingredients/items_fts from the wiki
    markdown (cheap, mechanical, safe after every ingest). The
    additional-information-retrieval companion tables (ingredient_tags,
    classified_items) are deliberately NOT dropped here — they hold
    expensive LLM classification results — but any rows left orphaned by
    content that changed or disappeared are cleaned up, since a stale tag
    pointing at a since-changed ingredient line is worse than no tag."""
    if not wiki_root.exists():
        print(f"{wiki_root} does not exist.", file=sys.stderr)
        sys.exit(1)

    db_path = wiki_root / DB_FILE_NAME
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        for table in MECHANICAL_TABLES:
            cur.execute(f"DROP TABLE IF EXISTS {table}")
        cur.executescript(SCHEMA_SQL)
        cur.executescript(ADDITIONAL_INFO_SCHEMA_SQL)

        rows_by_table: dict[str, list[dict]] = {}
        for table, columns in extract_records(wiki_root):
            rows_by_table.setdefault(table, []).append(columns)

        total = 0
        for table, rows in rows_by_table.items():
            if not rows:
                continue
            cols = list(rows[0].keys())
            col_list = ", ".join(cols)
            placeholders = ", ".join("?" for _ in cols)
            cur.executemany(
                f"INSERT INTO {table} ({col_list}) VALUES ({placeholders})",
                [tuple(row[c] for c in cols) for row in rows],
            )
            total += len(rows)

        cur.execute(
            "DELETE FROM ingredient_tags WHERE ingredient_id NOT IN "
            "(SELECT id FROM item_ingredients)"
        )
        orphaned_tags = cur.rowcount
        cur.execute(
            "DELETE FROM classified_items WHERE item_id NOT IN (SELECT id FROM items)"
        )
        orphaned_marks = cur.rowcount

        conn.commit()
        print(f"Rebuilt {db_path} — {total} rows across {len(rows_by_table)} tables.")
        if orphaned_tags or orphaned_marks:
            print(
                f"Cleaned up {orphaned_tags} orphaned ingredient_tags and "
                f"{orphaned_marks} orphaned classified_items rows (source "
                "content changed since they were classified)."
            )
    finally:
        conn.close()


def classify(wiki_root: Path, category: str, payload_json: str) -> None:
    """Insert additional-information-retrieval classification results for
    one category. payload_json is either the JSON directly, or `@<path>` to
    read it from a file — use the file form for large batches; a big book's
    payload can exceed the OS command-line length limit as an inline arg
    (hit in practice on Windows). Shape:
        {"tags": [{"ingredient_id": int, "tag": str, "confidence": "explicit"|"inferred"}, ...],
         "classified_item_ids": [int, ...]}
    `classified_item_ids` should include every item whose ingredients were
    checked for this category, even if no tag was assigned for some of
    them — that's what lets a later query tell "checked, no match" apart
    from "never checked" (see classified_items in ADDITIONAL_INFO_SCHEMA_SQL).
    Only inserts — never deletes existing tags for other categories/items,
    so multiple categories/incremental batches can be layered safely.
    """
    db_path = wiki_root / DB_FILE_NAME
    if not db_path.exists():
        print(f"{db_path} does not exist yet — run `rebuild` first.", file=sys.stderr)
        sys.exit(1)

    if payload_json.startswith("@"):
        payload_json = Path(payload_json[1:]).read_text(encoding="utf-8")
    payload = json.loads(payload_json)
    tags = payload.get("tags", [])
    classified_item_ids = payload.get("classified_item_ids", [])
    for t in tags:
        if not {"ingredient_id", "tag", "confidence"} <= t.keys():
            print(
                "Each tag needs ingredient_id, tag, confidence.", file=sys.stderr
            )
            sys.exit(1)
        if t["confidence"] not in ("explicit", "inferred"):
            print("confidence must be 'explicit' or 'inferred'.", file=sys.stderr)
            sys.exit(1)

    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.executemany(
            "INSERT INTO ingredient_tags (ingredient_id, category, tag, confidence) "
            "VALUES (?, ?, ?, ?)",
            [(t["ingredient_id"], category, t["tag"], t["confidence"]) for t in tags],
        )
        cur.executemany(
            "INSERT OR IGNORE INTO classified_items (item_id, category) VALUES (?, ?)",
            [(item_id, category) for item_id in classified_item_ids],
        )
        conn.commit()
        print(
            f"Inserted {len(tags)} ingredient_tags and marked "
            f"{len(classified_item_ids)} items classified for category '{category}'."
        )
    finally:
        conn.close()


def reset_category(wiki_root: Path, category: str) -> None:
    """Wipe all ingredient_tags/classified_items rows for one category, so
    it can be fully reclassified (e.g. after improving the classification
    rules). Never touches other categories."""
    db_path = wiki_root / DB_FILE_NAME
    if not db_path.exists():
        print(f"{db_path} does not exist yet — run `rebuild` first.", file=sys.stderr)
        sys.exit(1)

    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM ingredient_tags WHERE category = ?", (category,))
        tags_deleted = cur.rowcount
        cur.execute("DELETE FROM classified_items WHERE category = ?", (category,))
        marks_deleted = cur.rowcount
        conn.commit()
        print(
            f"Reset category '{category}': removed {tags_deleted} ingredient_tags "
            f"and {marks_deleted} classified_items rows."
        )
    finally:
        conn.close()


def query(wiki_root: Path, sql: str) -> None:
    stripped = sql.strip().rstrip(";").strip()
    if not re.match(r"(?is)^select\b", stripped):
        print("Only SELECT statements are allowed.", file=sys.stderr)
        sys.exit(1)

    db_path = wiki_root / DB_FILE_NAME
    if not db_path.exists():
        print(f"{db_path} does not exist yet — run `rebuild` first.", file=sys.stderr)
        sys.exit(1)

    conn = sqlite3.connect(db_path)
    try:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(stripped).fetchall()
        if not rows:
            print("(no rows)")
            return
        cols = rows[0].keys()
        print(" | ".join(cols))
        for row in rows:
            print(" | ".join(str(row[c]) for c in cols))
    finally:
        conn.close()


_COMMANDS = ("rebuild", "query", "classify", "reset-category")


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in _COMMANDS:
        print(__doc__)
        sys.exit(1)

    command = sys.argv[1]
    if command == "rebuild":
        wiki_root = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("wiki")
        rebuild(wiki_root)
    elif command == "query":
        if len(sys.argv) < 3:
            print("query requires a SQL string as the second argument", file=sys.stderr)
            sys.exit(1)
        sql = sys.argv[2]
        wiki_root = Path(sys.argv[3]) if len(sys.argv) > 3 else Path("wiki")
        query(wiki_root, sql)
    elif command == "classify":
        if len(sys.argv) < 4:
            print(
                "classify requires <category> <json payload>", file=sys.stderr
            )
            sys.exit(1)
        category = sys.argv[2]
        payload_json = sys.argv[3]
        wiki_root = Path(sys.argv[4]) if len(sys.argv) > 4 else Path("wiki")
        classify(wiki_root, category, payload_json)
    else:  # reset-category
        if len(sys.argv) < 3:
            print("reset-category requires <category>", file=sys.stderr)
            sys.exit(1)
        category = sys.argv[2]
        wiki_root = Path(sys.argv[3]) if len(sys.argv) > 3 else Path("wiki")
        reset_category(wiki_root, category)


if __name__ == "__main__":
    main()
