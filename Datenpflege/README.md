# Datenpflege

Konsolenwerkzeug, das die AOK-Pflege-Navigator-Exporte einliest und die Pflegeeinrichtungen
direkt in die Datenbank `pflege_db` schreibt. Es läuft unter Linux und Windows und braucht
nur Python und den MySQL-Treiber PyMySQL.

Die Einrichtung auf einem frischen Linux-Server steht in der [README im Projektordner](../README.md).
Hier stehen Befehle, Konfiguration und Verhalten.

## Schnellstart

```bash
python3 -m venv .venv                      # einmalig
.venv/bin/pip install -r requirements.txt  # einmalig
cp .env.example .env && chmod 600 .env     # einmalig, danach DB_USER und DB_PASS eintragen
.venv/bin/python run.py einlesen           # Import starten
```

Unter Windows: `python -m venv .venv`, `.venv\Scripts\pip install -r requirements.txt` und
`.venv\Scripts\python run.py einlesen`.

Voraussetzung ist Python ab 3.10 (getestet mit 3.12 und 3.14).

## Befehle

Alle Befehle werden im Ordner `Datenpflege` ausgeführt. Statt `python` steht auf dem Server
`.venv/bin/python`, oder du aktivierst die Umgebung einmal mit `source .venv/bin/activate`.

| Befehl | Beschreibung |
| --- | --- |
| `python run.py einlesen` | Liest den Dateneingang und schreibt in die Datenbank. Neue Einrichtungen werden angelegt. Unterscheidet sich ein vorhandener Eintrag vom Import, fragt die Konsole für jeden einzelnen Eintrag, welcher gelten soll. |
| `python run.py einlesen -f` (`--force`) | Wie `einlesen`, aber ohne Rückfrage: Der Import überschreibt abweichende lokale Einträge. |
| `python run.py einlesen -c` (`--care`) | Wie `einlesen`, aber ohne Rückfrage: Der lokale Eintrag bleibt, der abweichende Import wird verworfen. Neue Einrichtungen werden trotzdem angelegt. |
| `python run.py einlesen -h` | Zeigt die Hilfe. |
| `python -m pflegekatalog einlesen` | Gleich wie `python run.py einlesen`, auch mit `-f` und `-c`. |
| `python -m unittest discover -s tests` | Führt die Tests aus (siehe Abschnitt Tests). |

`-f` und `-c` lassen sich nicht kombinieren.

### Abfrage bei Unterschieden

Ohne `-f` und `-c` zeigt die Konsole nur die Felder, die sich unterscheiden:

```
--- Unterschied 1 von 3 ---
Pflegeheim: Haus Sonne
12345 Musterstadt, Hauptstraße 5
  Feld         Lokal (Datenbank)  Import
  Landkreis    Kreis M            Landkreis Muster
  Telefon      0123 111           0123 222
[l] lokal behalten  [i] Import übernehmen  [q] abbrechen >
```

- `l` behält den lokalen Eintrag.
- `i` übernimmt die Importwerte für die angezeigten Felder.
- `q` bricht ab. Dann wurde nichts in die Datenbank geschrieben.

Ohne Konsole (zum Beispiel im Cron-Job) gibt es keine Eingabe. Dort bricht der Lauf beim ersten
Unterschied ab und schreibt nichts. Deshalb braucht ein automatischer Lauf immer `-f` oder `-c`.

### Was bei einem Lauf passiert

1. Die Zugangsdaten werden gelesen und die Verbindung zur Datenbank wird aufgebaut.
2. Eine Sperre in der Datenbank verhindert, dass zwei Importe gleichzeitig laufen.
3. Alle XML-Dateien im Dateneingang werden gelesen und mit der Postleitzahl-Tabelle angereichert.
4. Der Import wird mit der Datenbank verglichen.
5. Neue Einträge werden angelegt, freigegebene Änderungen werden überschrieben. Das geschieht
   in einer einzigen Transaktion: Bei einem Fehler oder bei Strg+C bleibt die Datenbank unverändert.
6. Eine Zusammenfassung zeigt, wie viele Einträge neu, unverändert, überschrieben oder lokal
   behalten wurden.

Ein Lauf mit allen Bundesländern (rund 35.500 Einträge) dauert bei einer lokalen Datenbank etwa
15 Sekunden, der erste Import mit allen Schreibvorgängen etwa 35 Sekunden.

### Exit-Codes

| Code | Bedeutung |
| --- | --- |
| 0 | Lauf erfolgreich beendet |
| 1 | Fehler: Zugangsdaten fehlen, Datenbank nicht erreichbar oder Schreibfehler, Dateneingang fehlt, anderer Import läuft, Abbruch mit `q` |
| 2 | Ungültige Argumente, zum Beispiel `-f` zusammen mit `-c` |
| 130 | Abbruch mit Strg+C |

## Konfiguration

Die Zugangsdaten stehen in der Datei `.env` neben `run.py`. Sie bleibt lokal und ist in der
`.gitignore` eingetragen. Als Vorlage dient `.env.example`.

| Schlüssel | Bedeutung | Standard |
| --- | --- | --- |
| `DB_HOST` | Server der Datenbank | `localhost` |
| `DB_PORT` | Port | `3306` |
| `DB_NAME` | Name der Datenbank | `pflege_db` |
| `DB_USER` | MySQL-Benutzer (Pflicht) | |
| `DB_PASS` | Passwort des Benutzers | leer |

- Umgebungsvariablen mit denselben Namen haben Vorrang vor der Datei.
- `PFLEGE_ENV=/pfad/zur/datei.env` verwendet eine andere Datei. Das Format entspricht dem
  des Mailversands (`KEY=VALUE`, `#` für Kommentare).
- Unter Linux warnt das Programm, wenn andere Benutzer die `.env` lesen können.
  Abhilfe: `chmod 600 .env`.

Der Benutzer braucht nur diese Rechte, mehr nicht (der Befehl steht in der README im Projektordner):

| Tabelle | Rechte |
| --- | --- |
| `01_einrichtungstyp` | `SELECT`, `INSERT` |
| `21_ansprechpartner` | `SELECT`, `INSERT`, `UPDATE` |
| `22_pflegeeinrichtung` | `SELECT`, `INSERT`, `UPDATE` |

Das Programm löscht nie Einträge.

## Abgleich mit der Datenbank

**Wann gilt ein Eintrag als schon vorhanden?** Wenn Einrichtungstyp, Postleitzahl, Name und
Anschrift (Straße plus Hausnummer) übereinstimmen. Groß- und Kleinschreibung sowie
mehrfache Leerzeichen spielen dabei keine Rolle.

**Wann gilt er als unterschiedlich?** Sobald der Import für eines der folgenden Felder einen
Wert liefert, der vom lokalen abweicht: Straße, Hausnummer, Ort, Gemeinde/Stadt, Landkreis,
Bundesland, Internetseite, Telefon, E-Mail, Breitengrad, Längengrad.
Ein leeres Importfeld ist kein Unterschied und löscht nie einen lokalen Wert.
Bei einer Übernahme (`i` oder `-f`) werden nur die abweichenden Felder überschrieben.

## Zuordnung der Daten

| Quelle (AOK-XML) | Ziel in der Datenbank |
| --- | --- |
| `name` | `22_pflegeeinrichtung.einrichtungsname` |
| `strasse_hnr` | `strasse` und `hausnummer` (getrennt) |
| `plz`, `ort` | `plz`, `ort` |
| `web` | `webseite` |
| `telefon`, `email` | `21_ansprechpartner` (siehe unten) |
| Dateiname der XML (zum Beispiel `Hessen.xml`) | `bundesland` |
| Postleitzahl, nachgeschlagen in `referenz/geonames/DE.txt` | `landkreis`, `gemeinde_stadt`, `breitengrad`, `laengengrad` |

- **Einrichtungstyp:** Dateien in `ambulant/` ergeben "Ambulanter Pflegedienst". In `stationaer/`
  ergeben Vollstationäre Pflege und Kurzzeitpflege ein "Pflegeheim", Tagespflege eine
  "Tagespflege". Kommen beide vor, entstehen zwei Einträge. Fehlt ein Typ in
  `01_einrichtungstyp`, wird er angelegt. Vorhandene Namen wie "Pflegedienst" werden
  weiterverwendet.
- **Telefon und E-Mail:** `22_pflegeeinrichtung` hat dafür keine Spalten. Der Import legt je
  Einrichtung einen Ansprechpartner mit dem Nachnamen "Zentrale" und der Funktion
  "Einrichtung (Import)" an. Von Hand gepflegte Ansprechpartner fasst er nicht an.
- **Koordinaten** sind das Zentrum der Postleitzahl und keine exakte Hausadresse.
- Nicht befüllt werden die Öffnungszeiten (`20_oeffnungszeiten`), die Quelle enthält keine.
- **Übersprungen** werden Einträge ohne Namen und Einträge, die nicht in die Spalten der
  Datenbank passen (zum Beispiel ein Name über 150 Zeichen). Sie werden am Ende aufgelistet.
- Doppelte Einträge im Import (gleicher Schlüssel) ersetzen einander, der letzte gilt.

## Daten aktualisieren

Die Daten liegen im Repository:

```
Dateneingang/Pflegenavigator/data/ambulant/<Bundesland>.xml
Dateneingang/Pflegenavigator/data/stationaer/<Bundesland>.xml
referenz/geonames/DE.txt        # Postleitzahlen (GeoNames)
```

Der Dateiname ohne `.xml` gilt als Bundesland, zum Beispiel `Baden-Württemberg.xml`.
Neue Exporte ersetzt du in diesen Ordnern, committest sie und holst sie auf dem Server mit
`git pull`. Danach startest du den Import erneut. Er legt nur Neues an und fragt (oder
verfährt nach `-f` und `-c`) bei Unterschieden.

## Automatischer Lauf (Cron)

Für regelmäßige Läufe eignet sich `-c`: Von Hand gepflegte Daten bleiben erhalten, nur neue
Einrichtungen kommen dazu. `-f` überschreibt abweichende Felder bei jedem Lauf.

```cron
# sonntags 03:30 Uhr
30 3 * * 0 cd /pfad/zum/projekt/Datenpflege && .venv/bin/python run.py einlesen -c >> $HOME/pflegekatalog.log 2>&1
```

Der Exit-Code zeigt Fehler an (siehe Tabelle oben), die Meldungen stehen im Log.

## Tests

```bash
.venv/bin/python -m unittest discover -s tests
```

Die Logik-Tests (Abgleich, Abfrage, Konfiguration) laufen ohne Datenbank. Die Tests gegen eine
echte Datenbank werden übersprungen, solange `PFLEGE_TEST_SCHEMA` nicht gesetzt ist. Sie legen
eine eigene Datenbank `pflege_test_…` an und löschen sie wieder. `pflege_db` rühren sie nie an.

```bash
export PFLEGE_TEST_SCHEMA=/pfad/zu/pflege_db_backup.sql
export DB_HOST=localhost DB_PORT=3306 DB_USER=root DB_PASS=...   # Benutzer mit CREATE/DROP-Recht
.venv/bin/python -m unittest discover -s tests -v
```

## Fehlerbehebung

| Meldung | Ursache und Lösung |
| --- | --- |
| `No module named 'pymysql'` | Es läuft ein Python ohne die Abhängigkeiten. Mit `.venv/bin/python` starten oder `pip install -r requirements.txt` ausführen. |
| `DB_USER fehlt` | `.env` fehlt oder ist leer. `cp .env.example .env` und ausfüllen. |
| `Datenbankfehler 1045` | Benutzer oder Passwort falsch. `DB_USER` und `DB_PASS` prüfen. |
| `Datenbankfehler 1044` | Der Benutzer darf nicht auf `DB_NAME` zugreifen. Rechte prüfen. |
| `Datenbankfehler 1142` | Dem Benutzer fehlt ein Recht an einer Tabelle (siehe Tabelle bei Konfiguration). |
| `Datenbankfehler 1146` | Tabelle nicht vorhanden. Wurde das Schema (`pflege_db_backup.sql`) geladen? |
| `Datenbankfehler 2003` | Der Datenbankdienst läuft nicht oder `DB_HOST`/`DB_PORT` stimmen nicht. |
| `Es läuft bereits ein anderer Import` | Ein anderer Lauf ist aktiv. Warten. Die Sperre endet mit der Verbindung, auch nach einem Absturz. |
| `Dateneingang fehlt` | Der Ordner `Dateneingang/Pflegenavigator/data` fehlt oder ist leer. |
| `Keine Eingabe möglich` | Unterschied gefunden, aber keine Konsole vorhanden. Mit `-f` oder `-c` starten. |
| `Warnung: ... ist für andere Benutzer zugänglich` | `chmod 600 .env` ausführen. |

## Aufbau

```
Datenpflege/
  run.py                  Startpunkt
  requirements.txt        Abhängigkeiten (PyMySQL)
  .env.example            Vorlage für die Zugangsdaten
  pflegekatalog/
    cli.py                Befehle und Ablauf
    config.py             Zugangsdaten
    importer.py           XML lesen, Straße und Hausnummer trennen, Einrichtungen bilden
    plz.py                Postleitzahl zu Landkreis, Gemeinde und Koordinaten
    abgleich.py           Vergleich Import und Datenbank, Modi fragen/-f/-c
    konsole.py            Abfrage bei Unterschieden
    datenbank.py          SQL, Transaktion, Sperre
    modell.py             Datensatz und Feldlängen
  Dateneingang/           AOK-Exporte (XML)
  referenz/geonames/      Postleitzahlen (GeoNames)
  tests/
```

## Quellen

- AOK Pflege-Navigator (XML-Exporte)
- [GeoNames](https://www.geonames.org/) Postleitzahlen für Deutschland, Lizenz
  [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)
