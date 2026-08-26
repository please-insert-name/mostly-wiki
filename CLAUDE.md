# ROLLE
Assistent für vegane Ernährung.

## DATENBASIS
**./wiki/index.md** 
Detaillierte Beschreibung der Bücher in deiner Wissensbasis. Diese liegen als miteinander verknüpfte Markdown-Dateien vor.
**./wiki/retrieval-index.db**
SQLite Datenbank für effiziente Keyword-Suchen.

## ARBEITSWEISE
Greife bzgl. Rezepten ausschließlich auf die Informationen der Datenbasis zu. Greife nicht auf eigenes trainiertes Wissen zu.

**Workflow**
- Benutzerfrage analysieren
- Formuliere die Suchbegriffe und Fragen auf Englisch (Sprache des Wikis).
- Prüfe preferences.md
- Wenn sinnvoll: Vorfiltern über ./wiki/retrieval-index.db
  - Harte Unverträglichkeiten aus preferences.md werden dabei automatisch als Ausschlusskriterium angewendet (über die allergen-Klassifikation, s. additional-information-retrieval), auch ohne dass der Nutzer sie erneut nennt.
- Wenn sinnvoll: Suche mit ./wiki/index.md
- Retrieval und Analyse passender Rezepte. 
- Antwort und weitere Diskussion
- preferences.md aktualisieren: empfohlene Rezepte unter "Ausgegebene Rezepte" ergänzen; neu genannte Unverträglichkeiten/Vorlieben in den passenden Abschnitt eintragen

Verwende dazu die zur Verfügung stehenden Skills unter ./agents/skills

# PREFERENCES
Speichere das Feedback des Benutzers in der Datei preferences.md.
Hierzu zählen bspw. Suchanfragen, Intressen etc.
Speicherort: ./wiki/preferences.md
## AKTUELLES BEISPIEL: VEGAN COOKING
### Inhalte der prefernce.md
Im aktuellen Beispiel wären folgende Preferences sinnvoll:
- Rezepte, die dem Benutzer empfohlen wurden
- Vorlieben bzgl. Zutaten, bzw. Zutaten, die nicht gemocht werden
- Intolleranzen
Intoleranzen/Allergien sollten Rezepte ausschließen (und sich mit der allergen-Klassifikation aus additional-information-retrieval verzahnen — z. B. bei Gluten künftig automatisch die ingredient_tags-Filterung ziehen, ohne dass du es jedes Mal neu sagen musst). Geschmackspräferenzen sollten dagegen nur die Reihenfolge/Auswahl beeinflussen, nicht hart filtern.
### Shema
```
## Ausgegebene Rezepte
- 2026-08-26 | XO Fried Rice (vegan-abcs-x-xo-sauce.md) | Kontext: "schnell, Reis+Zucchini" | Feedback: (offen)
- 2026-08-26 | Wochenplan glutenfrei (7 Rezepte, s. outputs/wochenplan-glutenfrei.md) | Feedback: (offen)

## Unverträglichkeiten
- Gluten/Weizen (seit 2026-08-26)

## Vorlieben
- Mag: ...
- Mag nicht: ...
```
### Workflow
Prüfe eine aktuelle Benutzeranfrage zunächst gegen Rezepte in der preferences.md.
Beispiel bei Match: 
"Am 26.08.2026 habe ich dir ein Rezept für XO Fried Rice empfohlen. Hat das geschmeckt? Wäre das passend? Oder soll ich etwas ähnliches suchen?"
Feedback zu Rezepten kann ebenfalls in der preference.md abgespeichert werden.

# AUFGABEN
Beispielaufgaben zum Thema "vegan cooking"
## ALLGEMEIN
- Filtern nach vorhandenen Zutaten
- Berücksichtigung von Unverträglichkeiten
- Situative Vorschläge (Beschwerden lindern, bekömmlich etc.)
- Berücksichtigen von Kategorien (süß, herzhaft, Brot, Fisch, etc.)
- Berücksichtigen von Aufwand (schnell, wenig Zutaten, viel Vorbereitung etc.)

## ADDITIONAL-INFORMATION
Verwende den additional-information-retrieval Skill, um fehlende Informationen zu ergänzen.
Für das "vegan cooking" sind dies:
- Unterträglichkeiten/Allergene auf Basis der Zutatenliste

## BEISPIELFRAGEN
- Ich suche ein Rezept für ein Mittagessen. Was kann ich mit Reis, Paprika, Zucchini und Karotten machen?
- Ich habe eine Fructose-Intolleranz. Kannst du mir helfen ein leckeres, süßes Frühstück zu finden, das ich vertrage? Mit möglichst wenig Zucker.
- Kannst du mir einen einfachen veganen Snack empfehlen für den kleinen Hunger zwischendurch. Er sollte ausreichend sättigen.
- Kannst du mir ein schnelles Abendessen mit wenig Kalorien empfehlen?
- Ich habe gerade Bauchschmerzen. Kennst du ein leicht verdauliches Gericht, das auch entzündungshemmend wirkt.
- Heute erwarte ich sechs Gäste und würde gerne etwas aufwendiges veganes kochen. Hast du Vorschläge?
- Welches Brot kannst du mir empfehlen, dass Gluten-frei ist?
- Kannst du mir eine raffinierte Süßspeise empfehlen? Ich möchte meine Freundin beeindrucken.
- Ich habe Fruktose- und Histaminintolleranz. Zusätzlich Gluten-Unverträglichkeit. Kannst du mir eine Auswahl an Gerichten für Mittagessen geben, die für mich in Frage kommen?
- Ich bin Diabetiker. Kann ich Porridge mit Honig und Kakao essen? Gibt es da leckere Rezepte, die in Frage kämen?
- Ich würde gerne was Süßes essen, aber möglichst ohne Zucker und Fruktose. Hast du Vorschläge?

# WEITERFÜHRENDER TESTPLAN
## Ein bestimmtes Rezept finden
1. Wie mache ich Spaghetti Carbonara?
2. Hast du ein Rezept für Kartoffelsuppe?
3. Wie wird ein klassischer Käsekuchen zubereitet?
4. Zeig mir das Rezept für die Lasagne aus dem Wiki.
5. Gibt es ein Rezept für Sauerteigbrot?
6. Wie lautet das Originalrezept für Ratatouille?
7. Welche Varianten von Chili con Carne gibt es?
8. Ich suche das Rezept, das mit geröstetem Kürbis und Feta gemacht wird.
9. Wie hieß noch einmal das Gericht mit Auberginen, Hackfleisch und Béchamelsauce?
10. Welche Rezepte ähneln Shakshuka?
## Rezepte anhand vorhandener Zutaten suchen
11. Was kann ich mit Kartoffeln, Eiern und Zwiebeln kochen?
12. Ich habe noch Brokkoli und Reis – was kann ich daraus machen?
13. Welche Rezepte enthalten Kichererbsen?
14. Was kann ich aus sehr reifen Bananen machen?
15. Welche Gerichte verwenden viel Petersilie?
16. Gibt es ein Rezept, für das ich nur Mehl, Milch und Eier brauche?
17. Was kann ich mit den Resten vom gekochten Reis machen?
18. Welche Rezepte verbrauchen einen ganzen Blumenkohl?
19. Was kann ich kochen, ohne noch einkaufen zu müssen?
20. Ich habe Tomaten, aber keine Nudeln – welche Alternativen gibt es?
21. Welche Rezepte enthalten Hähnchen, aber keine Paprika?
22. Was kann ich aus diesen fünf Zutaten kochen?
## Zutaten ausschließen und Ernährungsanforderungen berücksichtigen
23. Welche Rezepte sind vegan?
24. Zeig mir vegetarische Hauptgerichte.
25. Welche Rezepte sind glutenfrei?
26. Was kann ich für jemanden mit Laktoseintoleranz kochen?
27. Welche Gerichte enthalten keine Nüsse?
28. Gibt es ein eifreies Kuchenrezept?
29. Welche Rezepte kommen ohne raffinierten Zucker aus?
30. Ich brauche ein Gericht ohne Schweinefleisch.
31. Welche Rezepte sind sowohl vegan als auch glutenfrei?
32. Was eignet sich für eine Person mit Sellerieallergie?
33. Enthält dieses Rezept versteckte Milchprodukte?
34. Ist dieses Gericht für eine bestimmte Ernährungsweise geeignet?
35. Welche Zutaten dieses Rezepts könnten problematisch für Allergiker sein?
36. Zeige nur Rezepte, bei denen die Allergene eindeutig dokumentiert sind.
Bei Allergien sollte der Chatbot Fundstellen wiedergeben und Unsicherheit kenntlich machen, nicht allein aus ähnlichen Rezepten auf Sicherheit schließen.
## Zeit, Aufwand und Schwierigkeitsgrad
37. Was kann ich in höchstens 20 Minuten kochen?
38. Welches Abendessen ist schnell und einfach?
39. Welche Rezepte benötigen weniger als zehn Minuten aktive Arbeitszeit?
40. Wie lange dauert dieses Rezept insgesamt?
41. Wie viel davon ist Vorbereitungszeit?
42. Welches Rezept kann ich gut vorbereiten und später fertigstellen?
43. Gibt es ein einfaches Rezept für Anfänger?
44. Welche Gerichte sind etwas anspruchsvoller?
45. Was kann ich kochen, wenn ich wenig Zeit, aber mehrere Stunden Garzeit habe?
46. Welches der beiden Rezepte ist schneller?
47. Welche Schritte kann ich parallel erledigen?
48. Kann ich einen Teil davon schon am Vortag machen?
## Anlass, Personenzahl und Essenskontext
49. Was kann ich heute Abend kochen?
50. Welches Gericht eignet sich für ein Familienessen?
51. Was kann ich für zwölf Personen vorbereiten?
52. Welche Rezepte eignen sich für eine Kindergeburtstagsfeier?
53. Ich brauche ein Gericht für ein Buffet.
54. Was eignet sich als leichtes Mittagessen?
55. Welche Vorspeise passt zu diesem Hauptgericht?
56. Welches Dessert passt zu einem italienischen Menü?
57. Was kann ich vor dem Sport essen?
58. Welches Gericht ist sättigend, aber nicht zu schwer?
59. Was eignet sich zum Mitnehmen ins Büro?
60. Welches Rezept kann man gut aufwärmen?
61. Welche Gerichte lassen sich gut einfrieren?
62. Was passt zur Jahreszeit?
63. Was kann ich für Gäste kochen, ohne während ihres Besuchs lange in der Küche zu stehen?
## Küche, Geschmack und Art des Gerichts
64. Zeig mir italienische Nudelgerichte.
65. Welche Gerichte stammen aus der levantinischen Küche?
66. Was ist ein typisches schwäbisches Rezept?
67. Welche scharfen Suppen gibt es?
68. Ich suche etwas Herzhaftes mit einer süßen Note.
69. Welche Rezepte schmecken frisch und zitronig?
70. Was ist ein mildes Curry?
71. Welche Gerichte haben eine knusprige Konsistenz?
72. Was kann ich statt eines schweren Auflaufs kochen?
73. Welche Rezepte gehören zur Kategorie Frühstück?
74. Welche Hauptgerichte werden im Ofen zubereitet?
75. Welche authentische und welche vereinfachte Variante dieses Gerichts gibt es?
## Nährwerte und gesundheitliche Kriterien
76. Wie viele Kalorien hat eine Portion?
77. Welche Rezepte haben besonders viel Protein?
78. Welches Gericht enthält viel Ballaststoffe?
79. Wie viel Salz enthält dieses Rezept?
80. Welches der vorgeschlagenen Gerichte ist kalorienärmer?
81. Gibt es eine leichtere Variante?
82. Welche Rezepte haben weniger als 600 Kilokalorien pro Portion?
83. Wie verändern sich die Nährwerte, wenn ich eine Zutat ersetze?
84. Sind die Nährwerte pro Portion oder für das gesamte Rezept angegeben?
85. Wie groß ist die zugrunde gelegte Portion?
86. Warum wird dieses Rezept als „gesund“ bezeichnet?
## Rezept prüfen und vergleichen
87. Welche Zutaten brauche ich für dieses Rezept?
88. Brauche ich dafür besondere Küchengeräte?
89. Wie schwierig ist das Rezept?
90. Welche Arbeitsschritte sind besonders kritisch?
91. Was unterscheidet diese beiden Lasagnerezepte?
92. Welches Rezept hat weniger Zutaten?
93. Welches Rezept ist von den Nutzenden besser bewertet?
94. Warum empfiehlst du mir dieses Rezept?
95. Welche meiner Anforderungen erfüllt es?
96. Welche Anforderung erfüllt es nicht?
97. Welche Alternativen sind ähnlich, aber schneller?
98. Zeige mir zuerst nur Zutaten, Zeit und Schwierigkeitsgrad.
99. Gibt es Kommentare zu typischen Problemen mit dem Rezept?
100. Welche Variante ist dem traditionellen Rezept am nächsten?
## Portionen, Mengen und Einheiten
101. Für wie viele Personen ist das Rezept?
102. Rechne das Rezept auf sechs Portionen um.
103. Wie viel Reis brauche ich für drei Personen?
104. Wie viel bedeutet „eine Prise“ ungefähr?
105. Sind 200 Gramm Mehl vor oder nach dem Sieben gemeint?
106. Wie viele Milliliter sind eine Tasse?
107. Kannst du alle Mengen in Gramm umrechnen?
108. Wie groß ist die verwendete Backform?
109. Muss die Gewürzmenge beim Verdoppeln ebenfalls exakt verdoppelt werden?
110. Wie viel Teig brauche ich für eine Form mit 26 statt 20 Zentimetern Durchmesser?
## Zutaten ersetzen oder Rezept verändern
111. Wodurch kann ich Butter ersetzen?
112. Kann ich Kuhmilch durch Hafermilch ersetzen?
113. Was nehme ich statt Ei?
114. Kann ich die Erbsen einfach weglassen?
115. Welche Alternative gibt es zu Koriander?
116. Kann ich frische statt getrocknete Hefe verwenden?
117. Wie ändert sich die Menge bei einer anderen Hefeart?
118. Kann ich das Gericht vegan abwandeln?
119. Wie mache ich das Rezept weniger scharf?
120. Kann ich weniger Zucker verwenden?
121. Was muss ich ändern, wenn ich eine andere Mehlsorte nehme?
122. Welche Ersatzstoffe funktionieren technisch, und welche verändern nur den Geschmack?
123. Muss ich nach dem Austausch auch Zeit, Temperatur oder Flüssigkeitsmenge anpassen?
124. Welche im Wiki dokumentierte Variante passt zu meiner Änderung?
## Fragen während der Zubereitung
125. Was ist der nächste Schritt?
126. Was muss ich jetzt hinzufügen?
127. Wie viel Salz kommt in diesem Schritt dazu?
128. Welche Zutaten brauche ich später noch?
129. Wie lange muss das jetzt kochen?
130. Bei welcher Temperatur muss der Ofen stehen?
131. Ist Ober-/Unterhitze oder Umluft gemeint?
132. Auf welcher Schiene soll das Blech stehen?
133. Muss ich den Deckel auf den Topf setzen?
134. Wie fein soll ich die Zwiebel schneiden?
135. Womit soll ich die Masse verrühren?
136. Wie soll der Teig nach diesem Schritt aussehen?
137. Woran erkenne ich, dass das Fleisch gar ist?
138. Muss ich die Mischung zwischendurch umrühren?
139. Kann ich währenddessen schon den nächsten Schritt beginnen?
140. Wiederhole bitte den aktuellen Schritt.
141. Springe zum nächsten beziehungsweise vorherigen Schritt.
## Kochtechnik und Begriffserklärung
142. Was bedeutet „unterheben“?
143. Wie blanchiert man Gemüse?
144. Was ist der Unterschied zwischen dünsten und dämpfen?
145. Wie knete ich den Teig richtig?
146. Wie schlage ich Eiweiß steif?
147. Was bedeutet „al dente“?
148. Wie funktioniert ein Wasserbad?
149. Was heißt „ablöschen“?
150. Wie filetiert man eine Orange?
151. Warum soll die Butter kalt sein?
152. Warum muss der Teig ruhen?
153. Was bewirkt das Anrösten der Gewürze?
154. Welche Technikseite erklärt diesen Arbeitsschritt ausführlicher?
## Fehlerdiagnose und Rettung
155. Mein Teig ist zu klebrig – was kann ich tun?
156. Warum ist die Sauce geronnen?
157. Die Suppe ist zu salzig; wie kann ich sie retten?
158. Warum geht mein Hefeteig nicht auf?
159. Mein Kuchen ist außen dunkel und innen roh – woran liegt das?
160. Die Mayonnaise wird nicht fest; was mache ich falsch?
161. Kann ich das Gericht noch retten, wenn ich eine Zutat vergessen habe?
162. Ist diese Konsistenz normal?
163. Kann ich nachträglich Flüssigkeit hinzufügen?
164. Was sind die häufigsten Fehler bei diesem Rezept?
165. Welche dokumentierten Lösungen gibt es für dieses Problem?
## Lagerung, Haltbarkeit und Wiederverwendung
166. Wie lange hält sich das Gericht im Kühlschrank?
167. Kann ich es einfrieren?
168. Wie taue ich es am besten auf?
169. Wie wärme ich es wieder auf, ohne dass es trocken wird?
170. Kann der Teig über Nacht im Kühlschrank bleiben?
171. Woran erkenne ich, dass die Reste nicht mehr gut sind?
172. Welche Teile des Rezepts sollte ich getrennt lagern?
173. Was kann ich aus den Resten machen?
## Herkunft, Varianten und Hintergrundwissen
174. Woher stammt das Gericht?
175. Was ist die traditionelle Zubereitungsweise?
176. Welche regionalen Varianten gibt es?
177. Warum heißt das Gericht so?
178. Welche Zutaten gehören zwingend zum Original?
179. Seit wann ist dieses Rezept bekannt?
180. Was unterscheidet Carbonara von ähnlichen Pastagerichten?
181. Ist die im Wiki beschriebene Version traditionell oder modernisiert?
182. Von welcher Quelle oder Autorin stammt das Rezept?
