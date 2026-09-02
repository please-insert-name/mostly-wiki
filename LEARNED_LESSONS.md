# LEARNED LESSONS
Hier werden Erkenntnisse aus der täglichen Verwendung des Wikis dokumentiert.
Diese können bei Bedarf zur Überarbeitung der Skills verwendet werden.

Workflow und Eintrags-Schema: siehe `## SKILL EVOLUTION` in `CLAUDE.md`.

## Neue Erkenntnisse

<!--
Schema pro Eintrag:
- Datum | Skill/Datei | Beobachtung | Vorschlag (optional)

Beispiel:
- 2026-09-02 | retrieval-index | `similar` gibt bei kleinen Korpora oft nur
  1-2 Kandidaten nach dem Präferenzen-Filter zurück, wenn --top-k zu klein
  gewählt wird | ggf. Default-top-k situativ erhöhen oder in SKILL.md als
  bekannte Einschränkung dokumentieren
-->

## Bereits verarbeitete Erkenntnisse

- 2026-09-02 | retrieval-index | `rebuild` löschte stillschweigend `item_ingredients.base_ingredient_id`, weil diese Spalte in einer früheren Sitzung nur ad-hoc gegen die Live-DB gebaut, aber nie in `SCHEMA_SQL` versioniert wurde — kein Git-Verlauf, kein Recovery-Pfad außer mechanischem Neu-Verknüpfen (90–95 % Abdeckung wiederhergestellt, exakte Original-Zuordnung nicht rekonstruierbar) | **Verarbeitet:** Spalte + `_relink_ingredients()` sind jetzt fest in `retrieval_index.py`s `SCHEMA_SQL`/`INGREDIENTS_SCHEMA_SQL` verankert und laufen automatisch bei jedem `rebuild` — kann nicht mehr unversioniert verloren gehen.
- 2026-09-02 | semantic-processing | `similar` kannte `preferences.md`-Ausschlüsse nicht; ein Top-Kandidat für "ähnlich zu Ayurvedic Bowl" enthielt Knoblauchpulver, das als eigene kanonische Zutat noch nicht in `ingredient_intolerances` erfasst war (Filterlücke in den Daten, nicht in der Suchlogik) | **Verarbeitet:** `similar` filtert jetzt standardmäßig gegen `ingredient_intolerances` + Allergen-Tags (`--raw` für ungefiltert); siehe SKILL.md "Retrieval, combined with structured filters" für die Begründung, warum das strukturell statt nur dokumentiert sein muss.
