---
name: retrieval-index
description: "Use when a karpathy-llm-wiki needs fast, structured pre-filtering — a derived SQLite index (wiki/<namespace>/retrieval-index.db) queried before reading article content. Triggers: setting up or updating structured retrieval for a wiki, 'retrieval index', 'build a SQL index over the wiki', a karpathy-llm-wiki Query step that needs to shortlist candidates, or a karpathy-llm-wiki Post-Ingest step that needs to refresh the index."
---

# Retrieval Index

A companion to `karpathy-llm-wiki` (see `../karpathy-llm-wiki/SKILL.md`). That skill owns the markdown layer (`raw/`, `wiki/`); this skill owns one derived artifact on top of it: `wiki/<namespace>/retrieval-index.db`, a SQLite database that lets a Query step narrow thousands of wiki items down to a handful of candidates with SQL instead of reading or grepping the whole wiki.

## Principles

- **Derived, disposable, never hand-edited.** The wiki's markdown articles are the only source of truth. The database is fully regenerated from them (`rebuild`, drop + recreate). If it were deleted, nothing would be lost — it would just need rebuilding.
- **Facts only, no judgment calls.** Store only what is explicit in the article text or structurally derivable from it (a heading, a literal "nut-free" label, a chapter name, an ingredient list). Never store inferred or subjective properties the source text doesn't actually state (e.g. "low sugar", "anti-inflammatory") — an LLM guessing those into a table row is a fabricated fact that then looks authoritative. Constraints like that stay a job for the read-and-reason step: the database narrows candidates on hard facts, a human/LLM reading the shortlisted articles judges the soft ones.
- **Schema is project-specific, process is generic.** There is no fixed schema — a cookbook wiki and an API-reference wiki need entirely different tables. What's generic is the *process* below: derive the schema from real example questions, get it approved, then implement it.
- **Full rebuild only — for the tables this skill owns.** `items`, `item_ingredients`, `items_fts` get a full drop + recreate on every `rebuild`, no incremental upsert; rebuilding is cheap at wiki scale and avoids drift between the index and the markdown it's derived from. Safe to rerun any time, including after every ingest. `items`/`item_ingredients` use content-derived, deterministic ids (not autoincrement) specifically so this stays true without breaking foreign keys held by `../additional-information-retrieval`'s tables, which live in the same database but are NOT touched by `rebuild` (see that skill — its classification tables are LLM-derived and too expensive to redo on every ingest).

## Standard shape

Two building blocks recur across domains and are the default starting point for step 3 below — extend or drop them per project, but don't reinvent them from scratch each time:

- **`items`** — one row per retrievable unit (recipe, API entry, glossary term, ...), always carrying `id`, `article` (path relative to `wiki/`), `anchor` (heading anchor), and whatever structured facts the example questions need as their own columns or normalized side tables (e.g. `item_ingredients(item_id, ingredient)` for AND/OR/exclusion filtering).
- **`items_fts`** — an FTS5 virtual table for free-text matching on natural-language questions that don't reduce to exact filters ("a refined dessert", "something easy to digest"): `title` (the heading text), `body` (the section's full source text, verbatim — not an LLM-authored summary; summarizing here reintroduces the fabrication risk the Principles above rule out) and `item_id UNINDEXED` as the join key back to `items`. Populate it in the same extraction pass as `items`, so both stay in sync on every rebuild.

```sql
CREATE VIRTUAL TABLE items_fts USING fts5(
    title,
    body,
    item_id UNINDEXED
);
```

Combine both at query time: structured columns/tables narrow on hard filters (AND/OR/NOT), `items_fts MATCH '...'` (optionally ranked with `bm25(items_fts)`) narrows on free-text relevance, joined on `item_id`.

## Setup workflow (once per project, or when the schema no longer covers a new question)

Run this before the database exists, or whenever a new example question can't be answered by the current schema.

1. **Collect example questions.** Check the project's `CLAUDE.md` first — many projects park these under a task/questions section (this project keeps them under `AUFGABEN`). If none exist there, ask the user for a markdown file or collect them in dialog, then make sure they end up persisted somewhere durable (e.g. appended to `CLAUDE.md`) — don't let them live only in conversation history.
2. **Inspect the wiki.** Read `wiki/<namespace>/index.md` and a representative sample of articles in the relevant topic director(y/ies) under `wiki/<namespace>/`. For each example question, identify exactly which facts in the actual text would let SQL answer or narrow it — not what facts *could theoretically* exist, what's actually there.
3. **Propose a schema.** Start from the Standard shape above (`items` + `items_fts`), then add whatever domain-specific columns/side-tables the example questions actually require. For each table/column, name which example question(s) it serves. Explicitly call out any example question that neither structured filtering nor `items_fts` can serve (it stays a job for reading full articles). Prefer normalized many-to-many tables (e.g. `item_ingredients(item_id, ingredient)`) over comma-packed strings whenever a question needs AND/OR/exclusion logic over a repeated facet.
4. **Get explicit approval** from the user before writing any extraction code or touching the database. This is a schema commitment other tooling will depend on — don't skip the checkpoint.
5. **Implement.** Fill in `scripts/retrieval_index.py`'s `SCHEMA_SQL` and `extract_records()` for this project (see the script's own docstring — same "adapt the config/extraction block per domain" pattern as `karpathy-llm-wiki`'s `build_general_index.py` used, which this skill replaces). Then run:
   ```
   python .agents/skills/retrieval-index/scripts/retrieval_index.py rebuild
   ```
   This creates/repopulates `wiki/<namespace>/retrieval-index.db`.

## Maintenance

- After every `karpathy-llm-wiki` ingest, rerun `rebuild` (that skill's Post-Ingest step calls this — see its SKILL.md). Full drop + recreate, so it's always safe.
- When a new example question arrives that the current schema can't answer, don't quietly bolt on a column — re-enter the setup workflow above from step 2, propose the schema change, get it approved, then re-extract.

## Retrieval

Used by `karpathy-llm-wiki`'s Query workflow, or directly when the user's request is clearly a structured filter (ingredient lists, category/tag combinations, exclusions):

```
python .agents/skills/retrieval-index/scripts/retrieval_index.py query "<SELECT ...>"
```

- Only `SELECT` statements are accepted (enforced by the script).
- For questions that mix exact filters and free-text description, join structured tables with `items_fts` in one query rather than running two separate lookups, e.g.:
  ```sql
  SELECT items.title, items.article, items.anchor
  FROM items
  JOIN item_ingredients ON item_ingredients.item_id = items.id
  JOIN items_fts ON items_fts.item_id = items.id
  WHERE item_ingredients.ingredient IN ('rice', 'bell pepper')
    AND items_fts MATCH 'refined OR impressive'
  ORDER BY bm25(items_fts);
  ```
- Treat results as a **candidate shortlist**, never as the final answer. Read the referenced article/section (via the path + anchor columns the schema should always include) before answering — the database only proves candidacy on the hard facts it stores; anything the user asked about that isn't a stored fact still needs judgment against the actual text. This applies to `items_fts` matches too: a keyword match is lexical, not semantic — it doesn't verify the claim, it only says the word is present.
- If a query returns nothing or looks wrong, don't assume the wiki lacks the content — check whether the schema actually models what was asked before concluding that.

## Known limitations (wiki/vegan-cooking namespace, validated against a 182-question test plan on 2026-08-26)

- **Translate before querying `items_fts`.** All article text is English; user questions are typically German. `MATCH 'Kartoffelsuppe'` returns zero rows even though "potato soup" recipes exist — FTS5 does no cross-language matching. Always translate the user's key terms to English (dish names, ingredients, techniques) before building the query. A query returning nothing is not proof the wiki lacks the content until you've confirmed the search terms were actually English.
- **Always `ORDER BY bm25(items_fts)`.** An unordered `MATCH` returns rows in an arbitrary/rowid-ish order, which can bury the actual best match well below weaker incidental hits (a word appearing once in an ingredient list ranks the same as a word appearing in the title without ranking). For "find this specific dish by name" questions, weight the title column higher, e.g. `bm25(items_fts, 5.0, 1.0)` (title weight, body weight) — a strong title match should usually outrank a passing body mention.
- **Substring filters on `item_ingredients.line_text` produce false positives — use word boundaries or a curated term list, not a bare substring.** Concretely: `LIKE '%nut%'` also matches "nutritional yeast", "nutmeg", and "coconut" (none are tree-nut allergens); `LIKE '%milk%'` matches "coconut milk", "oat milk", "almond milk" (this is a vegan corpus — "milk" essentially never means dairy). Prefer `LIKE '% nut,%' OR LIKE '% nut.%' OR LIKE '% nut '` style boundary matches, or better, an explicit list of the actual allergen terms (peanut, walnut, almond, cashew, pecan, hazelnut, macadamia, pistachio, pine nut, brazil nut for tree/peanut allergies) rather than one generic keyword.
- **The whole corpus is vegan.** Every recipe in this wiki is vegan by construction (see `wiki/<namespace>/index.md`). Questions like "is this vegan / vegetarian / dairy-free / egg-free / pork-free" are trivially "yes, all of them" — don't run a filter query for these, just state the fact. This also means an ingredient literally named "milk", "butter", "cheese", "bacon", etc. is a vegan analogue, not the animal product — don't flag those as allergen/diet violations without reading the actual recipe.
- **Allergen documentation is sparse (`dietary_tags` populated for ~4% of items).** Absence of a tag means *undocumented*, not *allergen-free*. Never state a recipe is safe for an allergy solely because `dietary_tags` doesn't mention it or because no ingredient line matched an exclusion term — cite what was actually checked and flag the uncertainty (per the project's CLAUDE.md: "Fundstellen wiedergeben und Unsicherheit kenntlich machen, nicht allein aus ähnlichen Rezepten auf Sicherheit schließen").
- **No structured nutrition data exists beyond occasional, inconsistent calorie mentions** (`calories_text`, ~10% of items — verbatim text, not a normalized number). Protein/fiber/sodium/salt values are not present in the source text as data (only incidental prose like "adds protein"); don't invent numbers for these. Say the wiki doesn't contain this information rather than estimating from world knowledge (per CLAUDE.md's "Greife nicht auf eigenes trainiertes Wissen zu").
- **No ratings, reviews, or user comments exist anywhere in the corpus.** Questions like "which recipe is better rated" or "what do people say about this recipe" have no answer in this wiki — say so, don't fabricate consensus.
- **`serves_min`/`serves_max`** are populated only when `yield_text` states an actual people-count ("Serves 4", "Yield: 8–10 servings") — about half of items. A quantity/piece yield ("Makes: 2 quarts", "Yield: 1 large cake") deliberately leaves these NULL rather than guessing a serving count.
- **`prep_minutes`/`cook_minutes`/`total_minutes`** are populated only where the source explicitly states timing (~3% of items, concentrated in a couple of "30-minute meals"-style books) — most recipes have no machine-readable time at all. For everything else, "quick"/"easy" claims live only as prose in `description`/`notes_text`, searchable via `items_fts` but not filterable numerically.
- **Step-by-step "what's the next step" questions (mid-cooking Q&A) are not a retrieval-index feature.** Once a specific `item_id` is identified, read that article's `**Method**` section directly (or the full `items_fts.body`) rather than trying to model step sequencing in SQL — the database's job ends at handing back the right candidate article.
- **Technique/glossary questions** ("was bedeutet unterheben?", "wie blanchiert man Gemüse?") are general cooking knowledge, not per-recipe facts, and are usually not separately answerable from this index unless a book happens to have a dedicated technique chapter (check `wiki/<namespace>/index.md` chapter listings first, e.g. "Staple Ingredients and Bakeware" style chapters) — most of the time this falls outside what the wiki documents at all.

## Conventions

- Database file: `wiki/<namespace>/retrieval-index.db`, one per wiki namespace (co-located with `index.md` and `log.md`).
- Script: `.agents/skills/retrieval-index/scripts/retrieval_index.py`, adapted per project.
- Every item-level table should carry enough to locate the source: article path (relative to `wiki/`) and a heading anchor at minimum.
- Free-text search, where the schema includes it, goes through an `items_fts` FTS5 virtual table (`title`, `body`, `item_id UNINDEXED`) — see Standard shape above. Don't roll a bespoke `LIKE`-based text search; FTS5 gives tokenization, phrase/prefix queries, and BM25 ranking for free.
