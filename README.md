# Mostly Wiki – Übersicht

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

Quellen:
Microsoft: MarkItDown (https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f)
Karpathy-Wiki (https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f)

Die Pipeline führt von unstrukturierten Quelldateien zu einer abfragbaren Wissensbasis. Jeder
Schritt ist als eigener Skill unter `.agents/skills/` gekapselt:

1. **`markitdown-processor`** — konvertiert Dateien aus `sources/` in sauberes Markdown
   (`markdown/<stem>/<stem>.md`, inkl. extrahierter Bilder) und überbrückt bekannte Lücken der
   `markitdown`-Bibliothek (z. B. verworfene Bilder in EPUB/DOCX/PPTX, kaputte Merged-Cells in
   XLSX). Ein Bridge-Skript (`to_wiki_raw.py`) übergibt das Ergebnis anschließend im vom
   nächsten Skill erwarteten Format nach `raw/<topic>/`.
2. **`karpathy-llm-wiki`** — kompiliert die Rohdateien aus `raw/` zu themenstrukturierten
   Wiki-Artikeln unter `wiki/<namespace>/library/*.md`, inklusive laufend gepflegtem Index
   (`wiki/<namespace>/index.md`) und Änderungsprotokoll (`wiki/<namespace>/log.md`). Neue Quellen werden mit
   bestehenden Artikeln zusammengeführt oder legen neue Artikel an; Widersprüche zwischen
   Quellen werden mit Quellenangabe im Artikel vermerkt statt stillschweigend aufgelöst.
3. **`retrieval-index`** — baut aus den Wiki-Artikeln eine SQLite-Datenbank
   (`wiki/<namespace>/retrieval-index.db`) für schnelles, strukturiertes Vorfiltern per SQL (z. B. nach
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
5. **`semantic-processing`** — fügt eine semantische Ähnlichkeitssuche hinzu, die der primären
   Suche nachgelagert wird: aus den Treffern von Schritt 3/4 ein für den Nutzer relevantes Item
   auswählen und dazu ähnliche Items finden ("Antworten mit Antworten matchen"), auch ohne
   gemeinsame Stichwörter. Embeddings werden lokal per `sentence-transformers` (Standardmodell
   `intfloat/multilingual-e5-base`) berechnet und bewusst **nicht** in einer separaten
   ChromaDB, sondern als zusätzliche Tabelle `item_embeddings` in derselben
   `wiki/<namespace>/retrieval-index.db` abgelegt — bei Korpusgrößen im niedrigen vierstelligen Bereich
   (hier ~3.925 Items) ist Brute-Force-Cosine-Similarity per NumPy schnell genug, sodass ein
   zweiter Storage-Layer/Vektorindex keinen Mehrwert bringt, aber Komplexität und eine
   zusätzliche Datei einführen würde — konsistent mit dem "eine Datei, disposable,
   regenerierbar"-Prinzip von Schritt 3. Wie `additional-information-retrieval` wird die
   Tabelle nicht bei jedem Rebuild automatisch neu berechnet (teuer), sondern gezielt und
   inkrementell per `embed`-Kommando aktualisiert.

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
   in `wiki/<namespace>/index.md`/den Artikeln selbst suchen.
4. Passende Treffer inhaltlich lesen und bewerten — der Index liefert nur Kandidaten, nie die
   endgültige Antwort.
5. Antworten und mit dem Nutzer diskutieren. Auf Wunsch ähnliche Antworten über semantische Suche
   finden.

## 4. Skill Evolution

Quellen: 
`Compiling Agent Experience into Persistent Knowledge for Skill Evolution` 
(https://arxiv.org/pdf/2608.27454v1)

Skills ändern sich hier nie "leise" — jede Schema- oder Verhaltensänderung durchläuft dieselbe
Zwei-Stufen-Disziplin, die `retrieval-index`/`additional-information-retrieval` schon für
Schema-Erweiterungen vorschreiben (Beispielfragen sammeln → Schema vorschlagen → Freigabe
einholen → erst dann implementieren). `LEARNED_LESSONS.md` (Projekt-Root) ist die dafür nötige
Zwischenablage: Beobachtungen aus dem täglichen Gebrauch werden dort unter "Neue Erkenntnisse"
gesammelt, bevor sie zu einer tatsächlichen Skill-Änderung führen. So kann sich über mehrere
Sitzungen Evidenz ansammeln, statt auf einen einzelnen Vorfall überzureagieren. Angelehnt an
SkillOpt (`Executive Strategy for Self-Evolving Agent Skills`, https://arxiv.org/abs/2605.23904)
trägt jeder Eintrag einen **begrenzten, konkreten Edit-Vorschlag** (Add/Delete/Replace an einer
genannten Datei/Stelle, plus Impact-Einstufung) statt offener Prosa — mit dem Unterschied, dass
die "Bewertung" hier menschliche Rücksprache statt eines automatischen Validierungs-Scores ist,
da kein Benchmark-Signal existiert. Volles Schema als Kommentar in `LEARNED_LESSONS.md`.

Verarbeitung ist ein bewusster, protokollierter Schritt — nie ein automatischer Trigger, und nie
eigenmächtig ohne Rücksprache. Zu Beginn jeder neuen Session werden offene Einträge kurz
gesichtet und dem Nutzer zusammengefasst; zusätzlich auf Zuruf oder proaktiv bevor ein Skill
substantiell geändert wird. Nach Rücksprache wandert jeder Eintrag mit kurzer Begründung entweder
nach "Bereits verarbeitete Erkenntnisse" (inkl. Verweis auf die vorgenommene Änderung; bei
Schema-relevanten Fällen weiterhin mit eigener Freigabe) oder nach "Nicht umgesetzte
Erkenntnisse" (mit Begründung, warum verworfen) — nichts bleibt unentschieden liegen. Zwei reale
Beispiele stehen bereits in `LEARNED_LESSONS.md`: ein Datenverlust durch ein unversioniertes
Schema-Feld (behoben durch Aufnahme ins versionierte `SCHEMA_SQL`) und eine Präferenzen-Filterlücke
in der semantischen Suche (behoben durch fest im Code verankerte statt nur dokumentierte Filterung
— s. Skill `semantic-processing`). Details zum Workflow stehen in `CLAUDE.md` unter `## SKILL
EVOLUTION`.

### Präferenzen und Feedback erfassen

Damit der Assistent über mehrere Sitzungen hinweg dazulernt, wird eine `preferences.md`
(Speicherort projektspezifisch in `CLAUDE.md` festgelegt, im Beispielprojekt
`./wiki/<namespace>/preferences.md`) laufend gepflegt:

- **Ausgegebene Empfehlungen** — was wurde wann empfohlen, inkl. Kontext und (falls vorhanden)
  Nutzer-Feedback dazu.
- **Harte Einschränkungen** — z. B. Unverträglichkeiten, die Ergebnisse bei der Suche nach Kostrezepten aktiv ausschließen und
  sich (wo möglich) mit einer `additional-information-retrieval`-Kategorie verzahnen, statt bei
  jeder Anfrage erneut abgefragt zu werden.
- **Weiche Vorlieben** — beeinflussen die Auswahl/Reihenfolge von Empfehlungen, schließen aber
  nichts hart aus.

Diese Datei wird vor jeder Antwort geprüft und nach jeder Antwort fortgeschrieben — der
Assistent baut so über die Zeit ein Nutzerprofil auf, ohne dass Vorlieben oder Einschränkungen
wiederholt erklärt werden müssen.
