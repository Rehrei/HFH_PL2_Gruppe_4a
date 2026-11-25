# HFH_PL2_Gruppe_4a

Project Lab 2, Teilprojekt 4: Datenbank für Pflegeeinrichtungen.

| Teil | Beschreibung |
| --- | --- |
| [`Datenpflege/`](Datenpflege/README.md) | Konsolenwerkzeug: liest die AOK-Pflege-Navigator-Exporte und schreibt die Einrichtungen in die Datenbank |
| `pflege_db_backup.sql` | Schema der Datenbank `pflege_db` (MySQL/MariaDB), ohne Daten |
| `index.php` | Mailversand (PHP 8.2+ mit `pdo_mysql` und `mbstring`). Die Einrichtung steht im Kopfkommentar der Datei. |
| `PL2_Thema4_Aufteilung.pptx` | Präsentation zur Aufgabenverteilung |

Diese Anleitung richtet `Datenpflege` auf einem frischen Linux-Server ein (Debian oder Ubuntu).
Die Befehle von `Datenpflege` stehen in der [README im Ordner `Datenpflege`](Datenpflege/README.md).

## Datenpflege auf einem frischen Linux-Server einrichten

Die Schritte gelten für Debian 12 oder neuer und Ubuntu 22.04 oder neuer. Die Befehle brauchen
`sudo`, der Betrieb danach nicht.

### 1. Pakete installieren

```bash
sudo apt update
sudo apt install -y git python3 python3-venv mariadb-server
python3 --version        # muss 3.10 oder neuer sein
```

`python3-venv` darf nicht fehlen. Ohne das Paket schlägt `python3 -m venv` mit der Meldung
"ensurepip is not available" fehl. Läuft die Datenbank auf einem anderen Server, entfällt
`mariadb-server` und es genügt der Client (`mariadb-client`).

### 2. Projekt holen

```bash
git clone --depth 1 https://github.com/Rehrei/HFH_PL2_Gruppe_4a.git
cd HFH_PL2_Gruppe_4a
```

`--depth 1` lädt nur den aktuellen Stand und spart Zeit und Platz. Das Repository enthält die
Datenquellen (rund 180 MB).

### 3. Datenbank anlegen (nur wenn es sie noch nicht gibt)

```bash
sudo mysql -e "CREATE DATABASE pflege_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
sudo mysql pflege_db < pflege_db_backup.sql
```

Achtung: Die Datei beginnt jede Tabelle mit `DROP TABLE IF EXISTS`. Sie löscht also vorhandene
Tabellen samt Inhalt. Nie in eine Datenbank laden, die schon Daten enthält.

### 4. Datenbank-Benutzer für Datenpflege anlegen

Ein eigener Benutzer mit den nötigen Rechten statt `root`. Das Passwort ersetzt du durch ein eigenes.

```bash
sudo mysql <<'SQL'
CREATE USER 'datenpflege'@'localhost' IDENTIFIED BY 'HIER_EIN_STARKES_PASSWORT';
GRANT SELECT, INSERT         ON pflege_db.`01_einrichtungstyp`   TO 'datenpflege'@'localhost';
GRANT SELECT, INSERT, UPDATE ON pflege_db.`21_ansprechpartner`   TO 'datenpflege'@'localhost';
GRANT SELECT, INSERT, UPDATE ON pflege_db.`22_pflegeeinrichtung` TO 'datenpflege'@'localhost';
SQL
```

### 5. Datenpflege einrichten

```bash
cd Datenpflege
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
chmod 600 .env
nano .env
```

In der `.env` trägst du ein:

```
DB_HOST=localhost
DB_PORT=3306
DB_NAME=pflege_db
DB_USER=datenpflege
DB_PASS=das_passwort_aus_schritt_4
```

Die `.env` bleibt auf dem Server und wird nicht ins Repository übernommen.

### 6. Prüfen und starten

```bash
.venv/bin/python -m unittest discover -s tests   # Tests ohne Datenbank, alle müssen OK sein
.venv/bin/python run.py einlesen                 # Import, fragt bei Unterschieden
```

Beim ersten Import in eine leere Datenbank gibt es keine Unterschiede, es wird nur angelegt.
Am Ende steht eine Zeile wie `Fertig: 35571 Einträge geprüft: 35571 neu, ...`.
Mit `-f` und `-c` und für den Cron-Betrieb siehe die [README von Datenpflege](Datenpflege/README.md).

### 7. Aktualisieren

```bash
cd HFH_PL2_Gruppe_4a
git pull
cd Datenpflege
.venv/bin/pip install -r requirements.txt     # nur nötig, wenn sich requirements.txt geändert hat
.venv/bin/python run.py einlesen -c
```

## Häufige Probleme auf dem Server

| Meldung | Lösung |
| --- | --- |
| `ensurepip is not available` | `sudo apt install python3-venv` |
| `externally-managed-environment` | Nicht mit dem System-`pip` installieren, sondern in der Umgebung `.venv` (Schritt 5). |
| `Datenbankfehler 2003` | Datenbankdienst prüfen: `sudo systemctl status mariadb`, gegebenenfalls `sudo systemctl enable --now mariadb`. |
| `Datenbankfehler 1045` | Benutzer oder Passwort in der `.env` stimmen nicht mit Schritt 4 überein. |
| `Datenbankfehler 1142` | Rechte aus Schritt 4 fehlen. |
| `Datenbankfehler 1146` | Das Schema wurde nicht geladen (Schritt 3). |

Weitere Meldungen und ihre Ursachen stehen in der [README von Datenpflege](Datenpflege/README.md#fehlerbehebung).
