---
name: semantic-processing
description: "Use after a primary retrieval-index search (structured SQL filter and/or items_fts free-text match) has already narrowed the wiki down to one or a few relevant items, and the user wants more like those — 'ähnliche Rezepte', 'was ist vergleichbar', 'zeig mir Alternativen zu X'. Ranks the rest of the corpus by embedding-space similarity to a chosen item ('match answers with answers'), not a replacement for the primary search. Triggers: an explicit request for similar/alternative items to an already-identified one, or a karpathy-llm-wiki Query step whose candidate set should be expanded via nearest neighbors instead of another keyword search."
---

# Semantic Processing

A second companion to `retrieval-index` (see `../retrieval-index/SKILL.md`) and, through it, to `karpathy-llm-wiki`. Where `retrieval-index` narrows on hard facts (SQL filters) and lexical relevance (`items_fts` keyword matching), this skill narrows on *meaning*: given one item the user already cares about, which other items in the corpus read as similar in substance, even if they share no keywords?

It reuses `retrieval-index`'s database (`wiki/<namespace>/retrieval-index.db`) and script (`../retrieval-index/scripts/retrieval_index.py`) rather than a separate vector store — see "Why the same database, why not a vector DB" below.

## Principles

- **Downstream of the primary search, not a replacement for it.** This skill answers "what else is like *this specific item*", not "what matches this free-text question" — that's still `items_fts`. The typical flow: primary search (SQL + FTS) → user or assistant picks one relevant `item_id` from the results → `similar` ranks the rest of the corpus against it.
- **Local, offline, reproducible.** Embeddings come from a local `sentence-transformers` model (default: `intfloat/multilingual-e5-base`), never a paid API — no network dependency, no per-run cost, no sending recipe text to a third-party service, and the exact same input always produces the exact same vector (unlike a hosted model that can change version under you).
- **Derived and disposable, like the rest of the index — but expensive, so not auto-rebuilt.** `item_embeddings` is fully recomputable from `items_fts.body` at any time (`embed` command), so nothing is lost if it's dropped. But computing it requires a model pass over every item, which is not free the way `rebuild`'s mechanical extraction is — same reasoning as `additional-information-retrieval`'s `ingredient_tags`. `embed` is therefore incremental (only touches items that are new or whose source text changed, tracked via `source_hash`) and never runs automatically as part of `rebuild`.
- **A candidate shortlist, never a final answer.** A high cosine-similarity score means "reads as similar in the embedding space" — it can surface a dish with a completely different name that shares technique/mood/ingredients, but it can just as easily surface a false positive (e.g. two dishes that are both "quick weeknight pasta" but otherwise unrelated). Always read the actual candidate articles before presenting them as "similar" to the user, exactly like `retrieval-index`'s own shortlist discipline.
- **Preference-filtering is structural, not a step you have to remember.** `similar` enforces this project's hard exclusions from `wiki/<namespace>/preferences.md` (curated `ingredient_intolerances` + `histamine_high`/`fructose_high` allergen tags) *by default* — see "Retrieval, combined with structured filters" below for why this isn't optional-by-convention. Only pass `--raw` when you deliberately want the unfiltered ranking (debugging, auditing what got hidden).

## Why the same database, why not a vector DB

A dedicated vector database (ChromaDB, etc.) makes sense once a corpus needs approximate nearest-neighbor search to stay fast — typically hundreds of thousands of vectors and up. At this project's scale (~4,000 items), a brute-force cosine similarity over all embeddings in NumPy is single-digit milliseconds; an ANN index would add a second storage engine, a second file/process to keep in sync with `wiki/<namespace>/retrieval-index.db`, and a new dependency, for zero measurable benefit. Storing embeddings as BLOBs in one more table in the existing SQLite file keeps the "one derived, disposable database" model the whole pipeline already follows (see `../retrieval-index/SKILL.md`). If the corpus ever grows into ANN territory, the natural upgrade path is the `sqlite-vec` extension (stays in the same file) before reaching for a separate vector database.

## Setup / usage workflow

1. **Make sure the corpus is embedded:**
   ```
   python ../retrieval-index/scripts/retrieval_index.py embed
   ```
   Requires the `sentence-transformers` package (`pip install sentence-transformers`) — not a hard dependency of the rest of the pipeline, only needed for this skill. First run downloads the model (~1 GB) and embeds every item; subsequent runs only (re)embed items that are new or changed since the last `embed` (compares `source_hash` against the current `items_fts.body`). Safe to rerun after every `karpathy-llm-wiki` ingest, same as `rebuild`.
2. **Identify the seed item.** Run the primary search (SQL pre-filter and/or `items_fts` free-text) as usual, per this project's `CLAUDE.md` workflow. Pick the `item_id` of the specific recipe the user wants alternatives/similar dishes to.
3. **Find similar items:**
   ```
   python ../retrieval-index/scripts/retrieval_index.py similar <item_id> --top-k 10
   ```
   Prints a ranked table (`score | item_id | title | article | anchor`), highest cosine similarity first, excluding the seed item itself and — by default — anything that violates a hard exclusion from `wiki/<namespace>/preferences.md` (see below). If candidates were hidden, the header line says how many; rerunning with a higher `--top-k` (or, in a pinch, `--raw`) shows what's beneath them.
4. **Read before presenting.** Treat the ranked list as candidates — open the actual articles (or their `items_fts.body`) for at least the top few before telling the user "this is similar", and say *why* in terms of what's actually in both recipes (shared technique, ingredient profile, meal type, etc.), not just "the model said so".

## Retrieval, combined with structured filters

**This is enforced in code, not left as a step to remember.** `similar` (in `retrieval_index.py`) joins its ranking against the same hard-exclusion logic used elsewhere — curated `ingredient_intolerances` overrides plus any ingredient tagged `histamine_high`/`fructose_high` in the `allergen` category (see `../additional-information-retrieval/SKILL.md`'s Retrieval section for the underlying query shape) — and drops matching items *before* ranking, by default. This exists because the embedding space itself has no notion of user preferences: a semantic match is "reads as similar," not "safe to eat." Concretely, `--top-k 5` on "Ayurvedic Bowl" once returned a coconut-and-garlic soup as a top candidate purely because garlic *powder* (a separate canonical ingredient from plain "garlic") hadn't yet been added to `ingredient_intolerances` — the hard-exclusion tables were incomplete, not the enforcement mechanism, but it's exactly the failure mode automatic enforcement is meant to catch early, loudly, in the output itself (via the "N candidate(s) hidden" note), rather than relying on a human or a future session remembering to re-filter by hand.

Use `--raw` only when you deliberately want the unfiltered ranking — debugging the model, auditing exactly what got hidden and why, or working with a wiki/user that has no `wiki/<namespace>/preferences.md` exclusions defined. Never present a `--raw` result to the user as if it were preference-checked.

If `similar` ever surfaces something that clearly should have been excluded (a known intolerance slipped through), that almost always means the underlying tables are incomplete — a canonical ingredient missing from `ingredient_intolerances`, or an item not yet covered by the `allergen` category's `classified_items` — not that the filtering logic itself needs bypassing. Fix the data (see `../additional-information-retrieval/SKILL.md`), not the call site.

## Maintenance

- After a `karpathy-llm-wiki` ingest + `retrieval-index` `rebuild`, rerun `embed` to pick up new/changed items — there is no automatic trigger, same deliberate-step discipline as `additional-information-retrieval`'s classification.
- `rebuild` itself never drops `item_embeddings` (it's not in `MECHANICAL_TABLES`), but does clean up rows orphaned by items that changed id or disappeared — safe to run freely.
- To switch embedding models, just rerun `embed --model <new-name>`; rows for the old model stay in the table (the `model` column scopes both `embed` and `similar`) unless you delete them by hand — useful for comparing models, wasteful otherwise.

## Conventions

- Table: `item_embeddings(item_id, model, dim, vector BLOB, source_hash, computed_at)` in `wiki/<namespace>/retrieval-index.db` (see `SEMANTIC_SCHEMA_SQL` in `../retrieval-index/scripts/retrieval_index.py`).
- Vectors are stored L2-normalized, float32, little-endian — so `similar`'s cosine similarity is a plain dot product, no renormalization needed at query time.
- Default model `intfloat/multilingual-e5-base`: multilingual (matches this wiki's German-question/English-article split), 768-dim, ~1.1 GB. e5 models expect a `"passage: "` prefix on indexed text and a `"query: "` prefix on ad-hoc search text — `embed` already applies the former; if this skill is ever extended to embed a free-text *question* directly (rather than only item-to-item), prefix it with `"query: "` to match the model's training format.
- Hard-exclusion tag list lives as `_HARD_EXCLUSION_ALLERGEN_TAGS` near `similar()` in `retrieval_index.py` (currently `histamine_high`, `fructose_high` — this project's two active intolerances per `wiki/<namespace>/preferences.md`). Extending it to a newly relevant category is a one-line change there, not a schema migration.
