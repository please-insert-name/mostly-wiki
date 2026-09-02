# LEARNED LESSONS
Hier werden Erkenntnisse aus der täglichen Verwendung des Wikis dokumentiert.
Diese können bei Bedarf zur Überarbeitung der Skills verwendet werden.

Workflow und Eintrags-Schema: siehe `## SKILL EVOLUTION` in `CLAUDE.md`.
Jeder Eintrag trägt einen **begrenzten, konkreten Edit-Vorschlag** (Add/Delete/Replace an
einer genannten Datei/Stelle) statt offener Prosa — angelehnt an SkillOpts Konzept bewerteter,
begrenzter Edits (arXiv:2605.23904), hier aber mit menschlicher statt algorithmischer
Freigabe, da kein automatisches Score-Signal existiert.

## Neue Erkenntnisse

<!--
Schema pro Eintrag:
- Datum | Skill/Datei | Beobachtung | Impact (niedrig/mittel/hoch) | Edit-Typ (Add/Delete/Replace) | Ziel (genaue Datei/Abschnitt) | Vorschlag (der konkrete Text-/Code-Vorschlag, kein vager Hinweis)

Beispiel:
- 2026-09-02 | retrieval-index | `similar` gibt bei kleinen Korpora oft nur
  1-2 Kandidaten nach dem Präferenzen-Filter zurück, wenn --top-k zu klein
  gewählt wird | niedrig | Add | semantic-processing/SKILL.md, Abschnitt
  "Known limitations" | Neuen Punkt ergänzen: "Bei stark gefilterten Korpora
  kann --top-k 10 zu wenige Kandidaten liefern — bei 0 oder sehr wenigen
  Treffern --top-k erhöhen (z.B. auf 50-200), bevor man 'keine ähnlichen
  Rezepte gefunden' meldet."
-->

## Bereits verarbeitete Erkenntnisse

- 2026-09-02 | retrieval-index | `rebuild` löschte stillschweigend `item_ingredients.base_ingredient_id`, weil diese Spalte in einer früheren Sitzung nur ad-hoc gegen die Live-DB gebaut, aber nie in `SCHEMA_SQL` versioniert wurde — kein Git-Verlauf, kein Recovery-Pfad außer mechanischem Neu-Verknüpfen (90–95 % Abdeckung wiederhergestellt, exakte Original-Zuordnung nicht rekonstruierbar) | **Verarbeitet:** Spalte + `_relink_ingredients()` sind jetzt fest in `retrieval_index.py`s `SCHEMA_SQL`/`INGREDIENTS_SCHEMA_SQL` verankert und laufen automatisch bei jedem `rebuild` — kann nicht mehr unversioniert verloren gehen.
- 2026-09-02 | semantic-processing | `similar` kannte `preferences.md`-Ausschlüsse nicht; ein Top-Kandidat für "ähnlich zu Ayurvedic Bowl" enthielt Knoblauchpulver, das als eigene kanonische Zutat noch nicht in `ingredient_intolerances` erfasst war (Filterlücke in den Daten, nicht in der Suchlogik) | **Verarbeitet:** `similar` filtert jetzt standardmäßig gegen `ingredient_intolerances` + Allergen-Tags (`--raw` für ungefiltert); siehe SKILL.md "Retrieval, combined with structured filters" für die Begründung, warum das strukturell statt nur dokumentiert sein muss.

## Nicht umgesetzte Erkenntnisse

<!--
Schema: wie oben, plus **Verworfen:** <kurze Begründung, warum nach Rücksprache
nicht umgesetzt — z.B. "zu geringer Nutzen", "Nutzer hält Verhalten für
gewünscht", "Edge Case zu selten">
-->

