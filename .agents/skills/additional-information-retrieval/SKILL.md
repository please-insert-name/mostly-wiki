---
name: additional-information-retrieval
description: "Use when a karpathy-llm-wiki question asks about a category of information that is NOT a literal stored fact in the wiki or retrieval-index, but can be reliably classified per item from one specific, project-defined basis field (e.g., classifying allergens or dietary suitability from a recipe's ingredient list, classifying an API's stability level from its changelog entries). Unlike retrieval-index, this index is LLM-derived, not mechanically extracted — every tag carries its evidence (a foreign key to the exact source row) and a confidence marker, so it stays auditable and is never presented as a bare fact. Triggers: a question in a category listed under the project's CLAUDE.md '## ADDITIONAL INFORMATION' section, building/updating that classification index, or a Query step that wants to pre-filter on one of these categories before reading full articles."
---

# Additional Information Retrieval

A companion to `retrieval-index` (see `../retrieval-index/SKILL.md`) and, through it, to `karpathy-llm-wiki`. `retrieval-index` stores only facts mechanically read off the page — explicit text, or something structurally countable. This skill exists for the other kind of question: one whose answer requires *judgment* against a narrowly-scoped part of the text (e.g. "does this ingredient list contain a tree nut?"), where that judgment is still worth pre-computing and pre-filtering on, not just reasoned about live per query.

It reuses `retrieval-index`'s database (`wiki/retrieval-index.db`) and script (`../retrieval-index/scripts/retrieval_index.py`) rather than standing up a separate one — see "Why the same database" below.

## Principles

- **Judgment, not extraction — and every judgment is traceable.** A tag is never a bare claim. It always references the exact `item_ingredients` row (via `ingredient_id`) that justified it, and carries a `confidence`: `explicit` (the ingredient names the thing directly — "peanut butter" → tag `peanut`) or `inferred` (world knowledge was needed — "soy sauce" → tag `gluten`, since most soy sauce contains wheat). Never collapse this distinction away when presenting results.
- **One fixed, narrow basis per category — never the whole article.** Each category in CLAUDE.md declares exactly which field the classification is allowed to read (for allergens/dietary-suitability: only `item_ingredients.line_text`, nothing else — not the description, not the method). This keeps classification auditable and prevents scope creep where the model starts "reasoning" from irrelevant context.
- **Absence of a tag is only meaningful if the item was checked.** `classified_items(item_id, category)` records that every ingredient of an item was run through classification for that category, independent of whether any tag was produced. Never treat "no `ingredient_tags` rows for this item" as a fact unless `classified_items` also confirms it was checked — otherwise "not yet classified" and "checked, nothing found" are indistinguishable, and the former silently masquerading as "safe" is exactly the failure mode this skill exists to prevent.
- **Expensive, so not rebuilt automatically.** Classification requires an LLM judgment per item, unlike `retrieval-index`'s regex-based extraction — it is not cheap enough to rerun after every `karpathy-llm-wiki` ingest. `rebuild` (the mechanical command) never touches `ingredient_tags`/`classified_items`; population and maintenance are separate, deliberate steps (see Maintenance below).
- **Full re-classification only at the category level, never partial/silent.** If a category's classification rules change, wipe and redo that whole category (`reset-category`) rather than patching individual rows — partial correctness is worse than an honest "not yet reclassified" gap, which `classified_items` makes visible.

## CLAUDE.md format

Categories live under an `## ADDITIONAL-INFORMATION` (or `## ADDITIONAL INFORMATION`) section. No fixed sub-structure is required — a flat list naming each category and its basis is enough, e.g. (this project's actual section, `CLAUDE.md`):

```markdown
## ADDITIONAL-INFORMATION
Verwende den additional-information-retrieval Skill, um fehlende Informationen zu ergänzen.
Für das "vegan cooking" sind dies:
- Unterträglichkeiten/Allergene auf Basis der Zutatenliste
- Nährwertdaten
```

What each category needs, however written: a **name** (becomes the `category` value — keep it stable once classification has run against it), and the **basis** (which field(s) classification may read — keep this narrow; "auf Basis der Zutatenliste" above means `item_ingredients.line_text` only, nothing else). Example questions can live here or in the project's existing question list (e.g. `BEISPIELFRAGEN`/`WEITERFÜHRENDER TESTPLAN`) — either is fine, they just need to exist somewhere durable so the tag vocabulary is derived from real need, same discipline as `retrieval-index`'s setup workflow. Tag vocabulary itself is open-ended, no need to enumerate it upfront.

If a category's basis is ambiguous or doesn't reduce to "classify each ingredient line," don't guess — resolve it with the user before classifying (see "A category that doesn't fit the ingredient-tagging shape" below).

If this section doesn't exist yet, ask the user for it (or draft one from the categories they describe in conversation) and make sure it lands in CLAUDE.md — don't let category definitions live only in conversation history.

### A category that doesn't fit the ingredient-tagging shape

`ingredient_tags` is built for *presence classification* per ingredient line ("does this line contain gluten?" → yes/no + evidence). Not every category reduces to that. Nutrition data is the clear example in this project: there's no nutrition panel in the source text (see `../retrieval-index/SKILL.md` "Known limitations"), so answering "how many calories" would mean *estimating* a number from ingredient quantities — that's the model's trained knowledge doing arithmetic/nutrition-science inference, not a classification of what's written on the page. That conflicts with this project's core instruction ("Greife nicht auf eigenes trainiertes Wissen zu") in a way allergen tagging does not: naming that "peanut butter" contains peanuts is reading the text, not inventing a number the text never stated.

Don't silently force such a category into `ingredient_tags`. Flag the mismatch to the user and get direction before building anything — options include: scope the category down to what genuinely is classifiable (e.g. "recipes that explicitly state a calorie count" is just a `retrieval-index` filter on `calories_text IS NOT NULL`, no classification needed), or accept that estimation is wanted despite the trained-knowledge caveat and mark every such result as an explicit estimate, never as sourced fact.

## Setup / classification workflow

1. **Confirm the category is defined** in CLAUDE.md (name, basis, example questions). If not, propose one and get it approved before classifying anything — this is a rules commitment, same checkpoint discipline as `retrieval-index`'s schema approval.
2. **Find pending items** for the category:
   ```sql
   SELECT DISTINCT item_id FROM item_ingredients
   WHERE item_id NOT IN (SELECT item_id FROM classified_items WHERE category = '<category>');
   ```
   Run this via `python ../retrieval-index/scripts/retrieval_index.py query "..."`.
3. **Classify in batches.** For each pending item, read *only* the category's declared basis (e.g. `SELECT id, line_text FROM item_ingredients WHERE item_id = ?`) and judge which tags apply per ingredient row, with `confidence`. Given corpus scale, do this via forked/batched agents the same way `karpathy-llm-wiki`'s book-by-book ingest was — don't try to classify thousands of items in one pass of your own context.
4. **Write results** with the `classify` command, once per batch:
   ```
   python ../retrieval-index/scripts/retrieval_index.py classify <category> '{"tags": [...], "classified_item_ids": [...]}'
   ```
   For a large book, pass `@<path to a json file>` instead of the JSON inline — a big payload can exceed the OS command-line length limit.
   Always include the full set of `classified_item_ids` covered by the batch, even items that produced zero tags — that's what marks them "checked."
5. **Verify** a sample: spot-check that `ingredient_tags` rows actually match their referenced `item_ingredients.line_text` before considering a category done.

## Maintenance

- `retrieval-index`'s `rebuild` (run after every `karpathy-llm-wiki` ingest) never drops `ingredient_tags`/`classified_items`, and cleans up any rows left orphaned by content that changed or disappeared — safe to run freely, no reclassification forced.
- After a `rebuild` that added new books/chapters, re-run step 2 above to find newly-pending items and classify them — this is the "incremental" part; there is no automatic trigger for it, it's a deliberate step you take (or the user asks for).
- To change a category's classification rules, run `reset-category <category>` (wipes that category's `ingredient_tags`/`classified_items` only) and redo the classification workflow from scratch for it.

## Retrieval

Pre-filter like any other `retrieval-index` query, joining through `item_ingredients`:

```sql
-- Rezepte ohne Nüsse, aber nur unter denen, die für 'allergen' bereits klassifiziert sind
SELECT items.title, items.article
FROM items
WHERE items.id IN (SELECT item_id FROM classified_items WHERE category = 'allergen')
  AND items.id NOT IN (
      SELECT item_ingredients.item_id FROM item_ingredients
      JOIN ingredient_tags ON ingredient_tags.ingredient_id = item_ingredients.id
      WHERE ingredient_tags.category = 'allergen' AND ingredient_tags.tag = 'nuts'
  );
```

- **Always report classification coverage alongside the answer.** If the candidate set includes items outside `classified_items` for the relevant category, say so explicitly rather than silently dropping or silently including them — the user (per this project's CLAUDE.md) needs "Fundstellen wiedergeben und Unsicherheit kenntlich machen, nicht allein aus ähnlichen Rezepten auf Sicherheit schließen."
- **Surface the evidence.** When presenting a match (or a exclusion), cite the actual `item_ingredients.line_text` and the `confidence` that produced the tag — never just the tag name in isolation.
- Treat results as a candidate shortlist like `retrieval-index` does, not a final verdict — an `inferred`-confidence tag in particular should be flagged as such to the user, not stated as flatly as an `explicit` one.

## Why the same database

Sharing `retrieval-index.db` (rather than a separate file) means `ingredient_tags.ingredient_id` is a real foreign key into `item_ingredients.id`, so a tag's evidence is *the actual row*, not a duplicated copy of its text that could drift. It also means one `rebuild` keeps both the mechanical and the classification layers consistent (via the orphan cleanup described above) instead of needing two artifacts kept in sync by hand.

## Conventions

- Category names are free-form strings (`category` column) — no enum enforced in SQL, so a new category needs no schema migration, only a CLAUDE.md entry and a classification pass.
- Tag vocabulary is likewise open — don't force existing items into an ill-fitting tag; add a new one.
- `confidence` is exactly `explicit` or `inferred` (enforced by the `classify` command) — no third value; if genuinely unsure whether a tag applies at all, don't emit it, and let the item's classification stand on whatever other tags were confidently produced.
