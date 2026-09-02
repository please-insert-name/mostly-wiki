# Mein eigenes KI-Wiki: Wie ein Assistent lernt, nur das zu sagen, was er wirklich weiß

Die meisten Chatbots antworten aus ihrem trainierten Wissen — beeindruckend breit, aber im Zweifel unzuverlässig, wenn es um mein *eigenes* Material geht: meine Kochbücher, meine Notizen, meine Quellen. Ich wollte etwas anderes: einen Assistenten, der ausschließlich auf Basis einer selbst aufgebauten Wissensbasis antwortet, sich an meine Vorlieben und Einschränkungen erinnert, und der über die Zeit besser wird, ohne dass ich ihn jedes Mal neu einlerne.

Herausgekommen ist "Mostly Wiki" — am konkreten Beispiel einer Sammlung veganer Kochbücher, aber die Architektur dahinter ist generisch. In diesem Artikel möchte ich die drei Ideen vorstellen, die mir am meisten gebracht haben, und kurz zeigen, wie Installation und Alltag aussehen.

## Das Grundproblem

Ein einzelnes, naives "wirf alles in einen Vektorindex und suche per Ähnlichkeit"-Setup (klassisches RAG) hat einen blinden Fleck: harte, eindeutige Fakten — *enthält dieses Rezept Knoblauch?*, *dauert das unter 20 Minuten?* — lassen sich damit nur unzuverlässig beantworten. Ähnlichkeitssuche ist gut für "was ist ungefähr vergleichbar", aber schlecht für "ja oder nein, exakt". Umgekehrt ist eine reine Datenbank-Lösung blind für Bedeutung: Sie findet nur, wonach exakt gesucht wird, nicht was inhaltlich passt.

Die Lösung war, beides sauber zu trennen und nacheinander zu nutzen.

## Idee 1: Zweiphasige Suche statt einer großen Blackbox

**Phase 1 — strukturiert und hart.** Aus den Wiki-Artikeln wird eine kleine, lokale SQLite-Datenbank gebaut, die ausschließlich das enthält, was *mechanisch* aus dem Text extrahierbar ist: Zutatenlisten, Zeitangaben, Kategorien. Keine Interpretation, keine Bewertung — reine Fakten. Darüber lässt sich präzise vorfiltern: "alle Hauptgerichte ohne Knoblauch und Tomate, die in unter 30 Minuten fertig sind" ist eine einfache, zuverlässige Abfrage, kein Ratespiel.

Eine zweite, ausdrücklich als *Einschätzung* markierte Schicht kommt dazu, wo reine Extraktion nicht reicht — etwa "enthält diese Zutatenliste versteckten Fruchtzucker?". Das erfordert Urteilsvermögen, wird also von der KI bewertet, aber jede Einschätzung bleibt mit einer Konfidenz (*explizit* vs. *abgeleitet*) und einem Verweis auf die genaue Textstelle nachvollziehbar. Nichts wird als bloße Behauptung präsentiert.

**Phase 2 — semantisch und weich.** Erst *nachdem* Phase 1 harte Kandidaten geliefert hat, kommt die Bedeutungsebene ins Spiel: eine lokale Embedding-Suche, die zu einem bereits gefundenen Rezept inhaltlich ähnliche findet — auch wenn kein einziges Wort übereinstimmt. "Zeig mir was Ähnliches wie dieses Curry" funktioniert so, ohne dass die Suche stur nach dem Wort "Curry" filtert.

Der Clou: Auch diese semantische Suche kennt meine Präferenzen. Ein Ähnlichkeitstreffer, der zufällig eine meiner Unverträglichkeiten enthält, wird automatisch aus dem Ranking entfernt, *bevor* er mir überhaupt angezeigt wird — nicht als nachträglicher manueller Schritt, sondern fest im Code verankert. Das war keine Nebensächlichkeit: Genau diese Lücke ist mir einmal live passiert (dazu gleich mehr).

## Idee 2: Der Index wird aus echten Fragen gebaut, nicht am Reißbrett entworfen

Der zweite Punkt, der sich im Alltag als überraschend wichtig herausgestellt hat: Das Datenbankschema wurde nicht abstrakt "möglichst vollständig" entworfen, sondern aus einer konkreten Sammlung typischer Nutzerfragen abgeleitet — am Ende über 180 Beispielfragen aus ganz unterschiedlichen Kategorien (Zutaten, Zeit, Anlass, Nährwerte, Zubereitungsschritte, Fehlerdiagnose, Herkunft …).

Für jede Fragenkategorie wurde geprüft: Welches Feld im Text beantwortet das wirklich? Nur was durch echten Bedarf gedeckt ist, bekommt eine eigene Spalte. Das klingt banal, hat aber zwei sehr praktische Effekte:

- **Keine Datenleichen.** Es gibt keine Tabellenspalten "für den Fall der Fälle", die nie befüllt oder abgefragt werden.
- **Ehrliche Lücken statt stiller Fehlannahmen.** Wenn eine Frage aus der Sammlung sich *nicht* beantworten lässt (z. B. gibt es im Korpus keine Nährwertangaben in strukturierter Form), steht das explizit als bekannte Grenze dokumentiert da — der Assistent sagt dann "das steht nicht im Wiki", statt eine Zahl zu schätzen und als Fakt zu verkaufen.

Jede Schema-Erweiterung folgt seitdem demselben Muster: neue Beispielfragen sammeln → Schema-Vorschlag → Freigabe einholen → erst dann umsetzen. Keine stillen Erweiterungen.

## Idee 3: Skill Evolution — das System lernt aus sich selbst heraus, aber nie unbeaufsichtigt

Das ist der Teil, der mich am meisten fasziniert hat, weil er ziemlich genau in eine aktuelle Forschungsrichtung fällt: Wie verbessern sich KI-Agenten aus eigener Erfahrung, ohne dass man das Modell neu trainiert? Arbeiten wie *EvoSkill*, *SkillOpt* (Microsoft) und *WikiSkill* (Google Research) untersuchen genau das — meist vollautomatisch, mit einem Benchmark-Score als Freigabe-Kriterium.

Mir fehlt dieses Score-Signal — es gibt kein "richtig/falsch" pro Rezeptempfehlung, an dem ein Algorithmus automatisch messen könnte, ob eine Änderung eine Verbesserung war. Also habe ich das Grundprinzip übernommen, aber die Freigabe durch ein menschliches Gate ersetzt:

Auffälligkeiten aus dem täglichen Gebrauch — eine Filterlücke, ein unerwarteter Datenverlust, eine Annahme, die sich als falsch herausstellt — werden in einer separaten Datei (`LEARNED_LESSONS.md`) protokolliert, *bevor* daraus eine tatsächliche Änderung wird. Jeder Eintrag trägt dabei nicht nur eine vage Beobachtung, sondern einen konkreten, begrenzten Änderungsvorschlag: was genau, an welcher Stelle, wie dringend. Zu Beginn jeder neuen Sitzung sichtet der Assistent offene Einträge von selbst, fasst sie mir zusammen, und wir entscheiden gemeinsam: umsetzen oder bewusst verwerfen. Beides wird protokolliert — nichts verschwindet stillschweigend.

Konkret ist das bereits zweimal passiert: Ein Datenfeld, das nur "live" in der Datenbank existierte statt im versionierten Code, ist bei einem Rebuild verloren gegangen — jetzt ist es fest im Schema verankert und kann nicht mehr so verschwinden. Und die oben erwähnte Präferenzen-Lücke in der semantischen Suche wurde genau so entdeckt, besprochen und behoben.

## Installation

Vorweg ehrlich: Das ist kein Ein-Klick-Produkt, sondern ein Setup, das man gemeinsam mit einem KI-Coding-Assistenten (ich nutze Claude Code) aufbaut — man muss dafür aber selbst keinen Code schreiben. Grob läuft es so:

1. **Umgebung**: Ein Projektordner mit Python und einem KI-Coding-Assistenten, der Dateien lesen/schreiben und Kommandozeilenbefehle ausführen kann.
2. **Quellmaterial ablegen**: Die eigenen Dokumente (EPUB, PDF, DOCX, PPTX, XLSX …) kommen unverändert in einen `sources/`-Ordner.
3. **Pipeline durchlaufen lassen** — jeder Schritt ist ein eigenständiges, wiederverwendbares "Skill"-Paket, das der Assistent auf Zuruf ausführt:
   - Dokumente zu sauberem Markdown konvertieren,
   - daraus thematisch strukturierte Wiki-Artikel kompilieren (inkl. Index und Änderungsprotokoll),
   - eine durchsuchbare, lokale Datenbank aus den Artikeln bauen,
   - optional: Zusatzkategorien (z. B. Allergene) klassifizieren,
   - optional: die semantische Ähnlichkeitssuche aktivieren (lokales Embedding-Modell, keine Cloud-API nötig).
4. **Rolle definieren**: In einer zentralen Konfigurationsdatei legt man fest, wer der Assistent sein soll (in meinem Fall: "Assistent für vegane Ernährung"), wo die Präferenzen-Datei liegt, und welche Beispielfragen das System später beherrschen soll.

Alles läuft lokal — die Wissensbasis, die Datenbank, die Embeddings. Es entsteht kein Cloud-Dienst, den man dauerhaft betreiben oder bezahlen müsste.

## Verwendung im Alltag

Im Betrieb ist es ein ganz normales Gespräch: Ich frage nach einem schnellen Abendessen unter Berücksichtigung meiner Unverträglichkeiten, der Assistent filtert zuerst hart (Phase 1), liest die vielversprechendsten Treffer inhaltlich gegen, und schlägt mir eine Auswahl vor — mit Fundstellen, nicht mit bloßen Behauptungen. Meine Vorlieben und harten Ausschlüsse merkt sich das System automatisch über eine `preferences.md`, die vor jeder Antwort geprüft und danach fortgeschrieben wird — ich muss meine Fruktoseintoleranz nicht in jeder neuen Sitzung wiederholen. Auf Wunsch findet die semantische Suche zu einem bereits gefundenen Rezept inhaltlich ähnliche Alternativen. Und am Ende lässt sich das Ganze bei Bedarf sogar als PDF exportieren.

## Fazit

Damit ist die erste Version fertig, und ich werde ab jetzt wirklich damit arbeiten. Der interessante Teil beginnt aus meiner Sicht aber erst jetzt: Nicht die Architektur selbst ist das Ziel, sondern der eingebaute Mechanismus, mit dem sie sich aus echtem, alltäglichem Gebrauch heraus — nachvollziehbar und mit mir gemeinsam — weiterentwickelt.
