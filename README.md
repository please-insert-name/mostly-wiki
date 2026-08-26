# Strong Wiki – Übersicht

Dieses Projekt baut einen Assistenten, der Fragen ausschließlich auf Basis einer selbst
aufgebauten, aus Quelldokumenten kompilierten Wissensbasis (einem "Wiki") beantwortet —
statt auf trainiertes Modellwissen zurückzugreifen. Die konkrete Rolle des Assistenten
(z. B. "Assistent für vegane Ernährung") sowie der fachliche Workflow werden in `CLAUDE.md`
definiert; dieses README beschreibt die generische Architektur dahinter.

## 1. Ablage der Eingangsdaten

- **`sources/`** — unveränderte Original-Dokumente (EPUB, PDF, DOCX, PPTX, XLSX), so wie sie
  bereitgestellt wurden.
- **`library/`** — optionaler Ort für weiteres Referenzmaterial, das nicht direkt ins Wiki
  einfließt.

## 2. Workflow: Neues Wiki generieren

Die Pipeline führt von unstrukturierten Quelldateien zu einer abfragbaren Wissensbasis. Jeder
Schritt ist als eigener Skill unter `.agents/skills/` gekapselt:

1. **`markitdown-processor`** — konvertiert Dateien aus `sources/` in sauberes Markdown
   (`markdown/<stem>/<stem>.md`, inkl. extrahierter Bilder) und überbrückt bekannte Lücken der
   `markitdown`-Bibliothek (z. B. verworfene Bilder in EPUB/DOCX/PPTX, kaputte Merged-Cells in
   XLSX). Ein Bridge-Skript (`to_wiki_raw.py`) übergibt das Ergebnis anschließend im vom
   nächsten Skill erwarteten Format nach `raw/<topic>/`.
2. **`karpathy-llm-wiki`** — kompiliert die Rohdateien aus `raw/` zu themenstrukturierten
   Wiki-Artikeln unter `wiki/<topic>/*.md`, inklusive laufend gepflegtem Index
   (`wiki/index.md`) und Änderungsprotokoll (`wiki/log.md`). Neue Quellen werden mit
   bestehenden Artikeln zusammengeführt oder legen neue Artikel an; Widersprüche zwischen
   Quellen werden mit Quellenangabe im Artikel vermerkt statt stillschweigend aufgelöst.
3. **`retrieval-index`** — baut aus den Wiki-Artikeln eine SQLite-Datenbank
   (`wiki/retrieval-index.db`) für schnelles, strukturiertes Vorfiltern per SQL (z. B. nach
   Zutaten, Zeitangaben, Kategorien), bevor ganze Artikel gelesen werden. Das Schema ist
   projektspezifisch und wird aus konkreten Beispielfragen abgeleitet; die Datenbank enthält
   ausschließlich mechanisch aus dem Text extrahierbare Fakten, keine Bewertungen. Sie wird bei
   jedem Ingest vollständig neu aufgebaut (billig, da rein regelbasiert) und ist damit
   verlustfrei wegwerfbar.
4. **`additional-information-retrieval`** — ergänzt den Retrieval-Index um Kategorien, die
   sich nicht mechanisch extrahieren lassen, sondern eine Einschätzung des LLM erfordern (z. B.
   Allergene/Unverträglichkeiten auf Basis der Zutatenliste). Jede solche Einschätzung bleibt
   über eine feste, eng begrenzte Textgrundlage nachvollziehbar (Beleg + Konfidenz
   `explicit`/`inferred`) und wird — anders als der mechanische Index — nicht bei jedem Ingest
   automatisch neu berechnet, sondern gezielt klassifiziert bzw. aktualisiert.

Ergebnis dieser Pipeline: ein Wiki (`wiki/`), das per SQL vorgefiltert und anschließend inhaltlich
gelesen werden kann, plus eine auditierbare Zusatzschicht für Kategorien, die Urteilsvermögen statt
reiner Extraktion erfordern.

## 3. Umgang mit dem fertigen Wiki

Der eigentliche fachliche Ablauf (welche Fragen beantwortet werden, welche Reihenfolge aus
Vorfilterung/Volltextsuche/Artikellektüre gewählt wird) steht in `CLAUDE.md` unter
`## ARBEITSWEISE`. Kurzfassung, allgemein:

1. Benutzerfrage analysieren und (falls das Wiki nicht in Deutsch vorliegt) in die Sprache des
   Wikis übersetzen.
2. Bekannte Präferenzen/Einschränkungen des Nutzers prüfen (siehe unten).
3. Über `retrieval-index.db` vorfiltern (inkl. harter Ausschlüsse aus den Präferenzen, sofern
   eine passende `additional-information-retrieval`-Kategorie existiert) und/oder per Volltext
   in `wiki/index.md`/den Artikeln selbst suchen.
4. Passende Treffer inhaltlich lesen und bewerten — der Index liefert nur Kandidaten, nie die
   endgültige Antwort.
5. Antworten und mit dem Nutzer diskutieren.

### Präferenzen und Feedback erfassen

Damit der Assistent über mehrere Sitzungen hinweg dazulernt, wird eine `preferences.md`
(Speicherort projektspezifisch in `CLAUDE.md` festgelegt, im Beispielprojekt
`./wiki/preferences.md`) laufend gepflegt:

- **Ausgegebene Empfehlungen** — was wurde wann empfohlen, inkl. Kontext und (falls vorhanden)
  Nutzer-Feedback dazu.
- **Harte Einschränkungen** — z. B. Unverträglichkeiten, die Ergebnisse aktiv ausschließen und
  sich (wo möglich) mit einer `additional-information-retrieval`-Kategorie verzahnen, statt bei
  jeder Anfrage erneut abgefragt zu werden.
- **Weiche Vorlieben** — beeinflussen die Auswahl/Reihenfolge von Empfehlungen, schließen aber
  nichts hart aus.

Diese Datei wird vor jeder Antwort geprüft und nach jeder Antwort fortgeschrieben — der
Assistent baut so über die Zeit ein Nutzerprofil auf, ohne dass Vorlieben oder Einschränkungen
wiederholt erklärt werden müssen.

## Beispielprojekt: Vegan Cooking

Die aktuelle Instanz dieses Wikis ist mit veganen Kochbüchern befüllt (`wiki/vegan-cooking/`).
`CLAUDE.md` enthält für dieses Beispiel konkrete Aufgaben, Beispielfragen und einen 182 Fragen
umfassenden Testplan — als Referenz dafür, wie man den generischen Aufbau oben für eine eigene
Domäne konkretisiert (eigene Rolle, eigenes Schema, eigene Zusatzkategorien, eigene
Präferenzfelder).
