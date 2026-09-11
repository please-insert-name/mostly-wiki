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

    python retrieval_index.py embed [--model NAME] [wiki_root]
        semantic-processing: compute sentence embeddings for every item
        missing one (or whose source text changed since it was last
        embedded), using a local sentence-transformers model — see
        ../../semantic-processing/SKILL.md. Incremental and safe to rerun,
        same pattern as `classify`. Requires the `sentence-transformers`
        package (not a hard dependency of this script otherwise).

    python retrieval_index.py similar <item_id> [--top-k N] [--raw] [wiki_root]
        semantic-processing: rank every other embedded item by cosine
        similarity to <item_id> and print the top N (default 10). Requires
        `embed` to have been run first. By default also enforces this
        project's hard exclusions from wiki/preferences.md (curated
        ingredient_intolerances + histamine_high/fructose_high allergen
        tags) — candidates violating one are silently dropped from
        ranking, with a note on how many were hidden. Pass --raw to see
        the unfiltered ranking instead (e.g. for debugging). Even
        filtered, this is a candidate shortlist like `query`, not a final
        answer — read the actual articles before presenting "similar
        recipes" to the user.

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
    line_text TEXT NOT NULL,
    -- Canonical ingredient this line refers to, if recognized — see
    -- INGREDIENTS_SCHEMA_SQL below and _relink_ingredients(), which
    -- (re)computes this column mechanically at the end of every rebuild
    -- (word-boundary, plural-tolerant match against `ingredients`).
    base_ingredient_id INTEGER REFERENCES ingredients(id)
);

-- Free-text search: title = heading text, body = section's source text
-- verbatim (never an LLM-authored summary), item_id = join key to items.id.
CREATE VIRTUAL TABLE items_fts USING fts5(
    title,
    body,
    item_id UNINDEXED
);
"""

# --- ingredient vocabulary / linking ---------------------------------------
# `ingredients` holds one row per canonical ingredient name (e.g. "tomato",
# "sun-dried tomato"). `rebuild` creates it if missing but — unlike
# MECHANICAL_TABLES — never drops it, so a curated vocabulary survives
# future rebuilds. item_ingredients.base_ingredient_id (see SCHEMA_SQL
# above) links each ingredient line to its canonical entry when one is
# recognized; that link is purely mechanical (word-boundary + plural-
# tolerant text match, no judgment call), so rebuild() recomputes it for
# every item_ingredients row right after repopulating that table (see
# _relink_ingredients()) — it can never again go silently missing/stale
# the way it did before this table was tracked here (see project history:
# an earlier ad-hoc build of this column lived only in the live database,
# not in any versioned schema, and was lost by a rebuild that predated
# this block).
INGREDIENTS_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS ingredients (
    id INTEGER PRIMARY KEY,
    name TEXT UNIQUE NOT NULL
);
"""


def _relink_ingredients(cur: sqlite3.Cursor) -> int:
    """(Re)compute item_ingredients.base_ingredient_id for every row,
    matching line_text against `ingredients.name` word-boundary-wise,
    tolerant of a trailing plural "s"/"es" on the (often singular)
    canonical name. Longest name first so multi-word/more specific
    canonical ingredients win over shorter substrings that would also
    match (e.g. "sun-dried tomato" over plain "tomato"). Purely
    mechanical — no judgment call, safe to rerun/recompute from scratch
    any time `ingredients` or item_ingredients changes."""
    ingredients = cur.execute("SELECT id, name FROM ingredients").fetchall()
    if not ingredients:
        return 0
    ingredients_sorted = sorted(ingredients, key=lambda r: len(r[1]), reverse=True)
    patterns = [
        (ing_id, re.compile(r"\b" + re.escape(name) + r"(?:es|s)?\b", re.IGNORECASE))
        for ing_id, name in ingredients_sorted
    ]

    rows = cur.execute("SELECT id, line_text FROM item_ingredients").fetchall()
    updates = []
    for row_id, text in rows:
        for ing_id, pat in patterns:
            if pat.search(text):
                updates.append((ing_id, row_id))
                break

    cur.executemany(
        "UPDATE item_ingredients SET base_ingredient_id = ? WHERE id = ?", updates
    )
    return len(updates)


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

# --- semantic-processing companion table -----------------------------------
# Populated by the `embed` command, NOT by `rebuild` — computing embeddings
# for the whole corpus is comparatively expensive (a local model pass per
# item), same reasoning as ingredient_tags above. One row per item; `embed`
# is incremental (only (re)computes rows missing or whose source_hash no
# longer matches items_fts.body), so it's safe to rerun after every ingest
# instead of needing a separate reset step. See ../../semantic-processing/SKILL.md.
SEMANTIC_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS item_embeddings (
    item_id INTEGER PRIMARY KEY REFERENCES items(id),
    model TEXT NOT NULL,        -- sentence-transformers model name used
    dim INTEGER NOT NULL,
    vector BLOB NOT NULL,       -- float32, little-endian, dim * 4 bytes
    source_hash TEXT NOT NULL,  -- sha256 of the embedded text, staleness check
    computed_at TEXT NOT NULL   -- ISO date, for auditability
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
    """Walk wiki_root/library/*.md, split each file into '## ' recipe
    sections (skipping 'Overview'), and yield items/item_ingredients/
    items_fts rows for each."""
    wiki_name = wiki_root.name  # e.g. "vegan-cooking" or "keto-cooking"
    for path in sorted((wiki_root / "library").glob("*.md")):
        text = path.read_text(encoding="utf-8")
        article = f"{wiki_name}/library/{path.name}"

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
        cur.executescript(INGREDIENTS_SCHEMA_SQL)
        cur.executescript(ADDITIONAL_INFO_SCHEMA_SQL)
        cur.executescript(SEMANTIC_SCHEMA_SQL)

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

        linked = _relink_ingredients(cur)

        cur.execute(
            "DELETE FROM ingredient_tags WHERE ingredient_id NOT IN "
            "(SELECT id FROM item_ingredients)"
        )
        orphaned_tags = cur.rowcount
        cur.execute(
            "DELETE FROM classified_items WHERE item_id NOT IN (SELECT id FROM items)"
        )
        orphaned_marks = cur.rowcount
        cur.execute(
            "DELETE FROM item_embeddings WHERE item_id NOT IN (SELECT id FROM items)"
        )
        orphaned_embeddings = cur.rowcount

        conn.commit()
        print(f"Rebuilt {db_path} — {total} rows across {len(rows_by_table)} tables.")
        num_ingredient_rows = len(rows_by_table.get("item_ingredients", []))
        print(f"Linked {linked} of {num_ingredient_rows} item_ingredients "
              "rows to a canonical ingredient (base_ingredient_id).")
        if orphaned_tags or orphaned_marks:
            print(
                f"Cleaned up {orphaned_tags} orphaned ingredient_tags and "
                f"{orphaned_marks} orphaned classified_items rows (source "
                "content changed since they were classified)."
            )
        if orphaned_embeddings:
            print(
                f"Cleaned up {orphaned_embeddings} orphaned item_embeddings rows "
                "(source content changed since they were embedded — rerun `embed`)."
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


DEFAULT_SEMANTIC_MODEL = "intfloat/multilingual-e5-base"


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def embed(wiki_root: Path, model_name: str = DEFAULT_SEMANTIC_MODEL) -> None:
    """Compute/refresh sentence embeddings for every item, using
    items_fts.body (title + full verbatim section text) as the embedded
    text. Incremental: only (re)embeds items with no row in item_embeddings
    for this model, or whose source_hash no longer matches the current
    body (content changed since last embed). Never touches embeddings for
    a different model name, so switching models doesn't require a manual
    wipe — just rerun `embed --model <new-name>` (old rows become dead
    weight; drop them by hand if you don't intend to keep multiple models).
    """
    db_path = wiki_root / DB_FILE_NAME
    if not db_path.exists():
        print(f"{db_path} does not exist yet — run `rebuild` first.", file=sys.stderr)
        sys.exit(1)

    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        print(
            "The 'sentence-transformers' package is required for `embed`.\n"
            "Install it with: pip install sentence-transformers",
            file=sys.stderr,
        )
        sys.exit(1)
    import numpy as np
    import datetime

    conn = sqlite3.connect(db_path)
    try:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        rows = cur.execute(
            """
            SELECT items.id AS item_id, items.title AS title, items_fts.body AS body,
                   item_embeddings.source_hash AS existing_hash
            FROM items
            JOIN items_fts ON items_fts.item_id = items.id
            LEFT JOIN item_embeddings
                ON item_embeddings.item_id = items.id AND item_embeddings.model = ?
            """,
            (model_name,),
        ).fetchall()

        pending = []
        for row in rows:
            text = f"{row['title']}\n\n{row['body']}"
            h = _sha256(text)
            if row["existing_hash"] != h:
                pending.append((row["item_id"], text, h))

        if not pending:
            print(f"Nothing to embed — all {len(rows)} items already up to date for model '{model_name}'.")
            return

        print(f"Embedding {len(pending)} of {len(rows)} items with '{model_name}' "
              "(new or changed since last embed)...")
        model = SentenceTransformer(model_name)
        # e5 models expect a "passage: " prefix for indexed documents (and a
        # "query: " prefix at search time) to match their training format.
        texts = ["passage: " + t for (_, t, _) in pending]
        vectors = model.encode(texts, batch_size=32, show_progress_bar=True,
                                convert_to_numpy=True, normalize_embeddings=True)
        dim = vectors.shape[1]
        now = datetime.date.today().isoformat()

        cur.executemany(
            "INSERT OR REPLACE INTO item_embeddings "
            "(item_id, model, dim, vector, source_hash, computed_at) VALUES (?, ?, ?, ?, ?, ?)",
            [
                (item_id, model_name, dim, np.asarray(vec, dtype=np.float32).tobytes(), h, now)
                for (item_id, _, h), vec in zip(pending, vectors)
            ],
        )
        conn.commit()
        print(f"Stored {len(pending)} embeddings (dim={dim}) in item_embeddings.")
    finally:
        conn.close()


# Tags within the allergen category that count as a hard exclusion here —
# see wiki/preferences.md "Unverträglichkeiten" and CLAUDE.md's PREFERENCES
# workflow. Project-specific, like the rest of this script's schema.
_HARD_EXCLUSION_ALLERGEN_TAGS = ("histamine_high", "fructose_high")


def _table_exists(cur: sqlite3.Cursor, name: str) -> bool:
    return cur.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def _hard_excluded_item_ids(cur: sqlite3.Cursor) -> set[int]:
    """Item ids that violate a hard exclusion from wiki/preferences.md:
    a curated ingredient_intolerances override, or an ingredient tagged
    with one of _HARD_EXCLUSION_ALLERGEN_TAGS in the allergen category
    (see additional-information-retrieval). Degrades to "nothing excluded"
    if this project hasn't set up those tables/preferences yet, so this
    stays safe to call unconditionally."""
    excluded: set[int] = set()
    if _table_exists(cur, "ingredient_intolerances") and _table_exists(cur, "item_ingredients"):
        excluded.update(
            row[0] for row in cur.execute(
                "SELECT DISTINCT item_id FROM item_ingredients "
                "WHERE base_ingredient_id IN (SELECT ingredient_id FROM ingredient_intolerances)"
            ).fetchall()
        )
    if _table_exists(cur, "ingredient_tags"):
        placeholders = ", ".join("?" for _ in _HARD_EXCLUSION_ALLERGEN_TAGS)
        excluded.update(
            row[0] for row in cur.execute(
                "SELECT DISTINCT item_ingredients.item_id FROM item_ingredients "
                "JOIN ingredient_tags ON ingredient_tags.ingredient_id = item_ingredients.id "
                f"WHERE ingredient_tags.category = 'allergen' AND ingredient_tags.tag IN ({placeholders})",
                _HARD_EXCLUSION_ALLERGEN_TAGS,
            ).fetchall()
        )
    return excluded


def similar(wiki_root: Path, item_id: int, top_k: int = 10,
            model_name: str = DEFAULT_SEMANTIC_MODEL, filtered: bool = True) -> None:
    """Rank every other embedded item by cosine similarity to item_id and
    print the top_k. Vectors are stored L2-normalized (see embed()), so
    cosine similarity reduces to a plain dot product.

    By default (filtered=True) this also enforces the project's hard
    exclusions from wiki/preferences.md (see _hard_excluded_item_ids) —
    the semantic ranking itself has no notion of user preferences, so
    without this a similarity match could recommend something the user
    is intolerant to (this happened once: a top result contained garlic
    powder, missed because it wasn't yet in ingredient_intolerances).
    Pass filtered=False (`--raw` on the CLI) to see the unfiltered
    ranking, e.g. for debugging or auditing what got excluded and why.
    """
    db_path = wiki_root / DB_FILE_NAME
    if not db_path.exists():
        print(f"{db_path} does not exist yet — run `rebuild` first.", file=sys.stderr)
        sys.exit(1)
    import numpy as np

    conn = sqlite3.connect(db_path)
    try:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        target = cur.execute(
            "SELECT vector, dim FROM item_embeddings WHERE item_id = ? AND model = ?",
            (item_id, model_name),
        ).fetchone()
        if target is None:
            print(
                f"No embedding for item_id {item_id} with model '{model_name}'. "
                "Run `embed` first.", file=sys.stderr,
            )
            sys.exit(1)
        target_vec = np.frombuffer(target["vector"], dtype=np.float32)

        rows = cur.execute(
            """
            SELECT item_embeddings.item_id, item_embeddings.vector,
                   items.title, items.article, items.anchor
            FROM item_embeddings
            JOIN items ON items.id = item_embeddings.item_id
            WHERE item_embeddings.model = ? AND item_embeddings.item_id != ?
            """,
            (model_name, item_id),
        ).fetchall()
        if not rows:
            print("(no other embedded items)")
            return

        excluded_note = ""
        if filtered:
            excluded_ids = _hard_excluded_item_ids(cur)
            before = len(rows)
            rows = [r for r in rows if r["item_id"] not in excluded_ids]
            removed = before - len(rows)
            if removed:
                excluded_note = (
                    f" ({removed} candidate(s) hidden — violate a hard exclusion from "
                    "wiki/preferences.md; rerun with --raw to see them)"
                )
        if not rows:
            print(f"(no candidates left after preference filtering{excluded_note})")
            return

        matrix = np.stack([np.frombuffer(r["vector"], dtype=np.float32) for r in rows])
        scores = matrix @ target_vec
        order = np.argsort(-scores)[:top_k]

        print(f"score | item_id | title | article | anchor{excluded_note}")
        for i in order:
            r = rows[i]
            print(f"{scores[i]:.4f} | {r['item_id']} | {r['title']} | {r['article']} | {r['anchor']}")
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


_COMMANDS = ("rebuild", "query", "classify", "reset-category", "embed", "similar")


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
    elif command == "reset-category":
        if len(sys.argv) < 3:
            print("reset-category requires <category>", file=sys.stderr)
            sys.exit(1)
        category = sys.argv[2]
        wiki_root = Path(sys.argv[3]) if len(sys.argv) > 3 else Path("wiki")
        reset_category(wiki_root, category)
    elif command == "embed":
        rest = sys.argv[2:]
        model_name = DEFAULT_SEMANTIC_MODEL
        if "--model" in rest:
            i = rest.index("--model")
            model_name = rest[i + 1]
            rest = rest[:i] + rest[i + 2:]
        wiki_root = Path(rest[0]) if rest else Path("wiki")
        embed(wiki_root, model_name)
    else:  # similar
        rest = sys.argv[2:]
        if not rest:
            print("similar requires <item_id>", file=sys.stderr)
            sys.exit(1)
        item_id = int(rest[0])
        rest = rest[1:]
        top_k = 10
        if "--top-k" in rest:
            i = rest.index("--top-k")
            top_k = int(rest[i + 1])
            rest = rest[:i] + rest[i + 2:]
        filtered = True
        if "--raw" in rest:
            rest = [a for a in rest if a != "--raw"]
            filtered = False
        wiki_root = Path(rest[0]) if rest else Path("wiki")
        similar(wiki_root, item_id, top_k, filtered=filtered)


if __name__ == "__main__":
    main()
