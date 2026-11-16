from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from pflegekatalog.konstanten import BUNDESLAENDER
from pflegekatalog.pfade import DB_PATH
from pflegekatalog.plz import name_oder_nichts, schluessel

SCHEMA = """
CREATE TABLE IF NOT EXISTS bundesland (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS landkreis (
    id INTEGER PRIMARY KEY,
    bundesland_id INTEGER NOT NULL REFERENCES bundesland(id),
    name TEXT NOT NULL,
    UNIQUE (bundesland_id, name)
);

CREATE TABLE IF NOT EXISTS stadt (
    id INTEGER PRIMARY KEY,
    bundesland_id INTEGER NOT NULL REFERENCES bundesland(id),
    landkreis_id INTEGER REFERENCES landkreis(id),
    name TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_stadt_mit_kreis
    ON stadt(landkreis_id, name) WHERE landkreis_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_stadt_ohne_kreis
    ON stadt(bundesland_id, name) WHERE landkreis_id IS NULL;

CREATE TABLE IF NOT EXISTS gemeinde (
    id INTEGER PRIMARY KEY,
    stadt_id INTEGER NOT NULL REFERENCES stadt(id),
    name TEXT NOT NULL,
    UNIQUE (stadt_id, name)
);

CREATE TABLE IF NOT EXISTS einrichtung (
    id INTEGER PRIMARY KEY,
    typ TEXT NOT NULL CHECK (typ IN (
        'pflegestuetzpunkt', 'ambulant', 'tagespflege', 'nachtpflege', 'pflegeheim'
    )),
    name TEXT NOT NULL,
    name_norm TEXT NOT NULL,
    strasse TEXT NOT NULL DEFAULT '',
    strasse_norm TEXT NOT NULL DEFAULT '',
    plz TEXT NOT NULL DEFAULT '',
    bundesland_id INTEGER REFERENCES bundesland(id),
    landkreis_id INTEGER REFERENCES landkreis(id),
    stadt_id INTEGER REFERENCES stadt(id),
    gemeinde_id INTEGER REFERENCES gemeinde(id),
    ansprechpartner TEXT NOT NULL DEFAULT '',
    telefon TEXT NOT NULL DEFAULT '',
    email TEXT NOT NULL DEFAULT '',
    web TEXT NOT NULL DEFAULT '',
    oeffnungszeiten TEXT NOT NULL DEFAULT '',
    beratungsleistungen TEXT NOT NULL DEFAULT '',
    zustaendigkeitsbereich TEXT NOT NULL DEFAULT '',
    breitengrad REAL,
    laengengrad REAL,
    koordinaten_herkunft TEXT CHECK (
        koordinaten_herkunft IN ('plz', 'manuell') OR koordinaten_herkunft IS NULL
    ),
    quelle TEXT NOT NULL DEFAULT '',
    angelegt_am TEXT NOT NULL DEFAULT (datetime('now')),
    geaendert_am TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_einrichtung_ident
    ON einrichtung(typ, plz, name_norm, strasse_norm);

CREATE INDEX IF NOT EXISTS idx_einrichtung_bundesland ON einrichtung(bundesland_id);
CREATE INDEX IF NOT EXISTS idx_einrichtung_typ ON einrichtung(typ);
CREATE INDEX IF NOT EXISTS idx_einrichtung_plz ON einrichtung(plz);
"""

AUSGABE = """
SELECT
    e.*,
    b.name AS bundesland,
    k.name AS landkreis,
    s.name AS stadt,
    g.name AS gemeinde
FROM einrichtung e
LEFT JOIN bundesland b ON b.id = e.bundesland_id
LEFT JOIN landkreis k ON k.id = e.landkreis_id
LEFT JOIN stadt s ON s.id = e.stadt_id
LEFT JOIN gemeinde g ON g.id = e.gemeinde_id
"""


def verbinden(pfad=DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(pfad)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def datenbank_anlegen(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.executemany(
        "INSERT INTO bundesland(name) VALUES (?) ON CONFLICT(name) DO NOTHING",
        [(name,) for name in BUNDESLAENDER],
    )
    conn.commit()


@dataclass(frozen=True)
class OrtIds:
    bundesland_id: int | None
    landkreis_id: int | None
    stadt_id: int | None
    gemeinde_id: int | None


class Hierarchie:
    """Legt Bundesland, Landkreis, Stadt und Gemeinde an und merkt sich die Ids."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.laender: dict[str, int] = {}
        self.kreise: dict[tuple[int, str], int] = {}
        self.staedte: dict[tuple[int, int | None, str], int] = {}
        self.gemeinden: dict[tuple[int, str], int] = {}
        self._laden()

    def _laden(self) -> None:
        for zeile in self.conn.execute("SELECT id, name FROM bundesland"):
            self.laender[zeile["name"]] = zeile["id"]
        for zeile in self.conn.execute("SELECT id, bundesland_id, name FROM landkreis"):
            self.kreise[(zeile["bundesland_id"], zeile["name"])] = zeile["id"]
        for zeile in self.conn.execute(
            "SELECT id, bundesland_id, landkreis_id, name FROM stadt"
        ):
            self.staedte[(zeile["bundesland_id"], zeile["landkreis_id"], zeile["name"])] = zeile["id"]
        for zeile in self.conn.execute("SELECT id, stadt_id, name FROM gemeinde"):
            self.gemeinden[(zeile["stadt_id"], zeile["name"])] = zeile["id"]

    def sicherstellen(
        self,
        bundesland: str | None,
        landkreis: str | None,
        stadt: str | None,
        gemeinde: str | None,
    ) -> OrtIds:
        bundesland = name_oder_nichts(bundesland)
        landkreis = name_oder_nichts(landkreis)
        stadt = name_oder_nichts(stadt)
        gemeinde = name_oder_nichts(gemeinde)
        if not stadt and gemeinde:
            stadt = gemeinde
        if not bundesland:
            return OrtIds(None, None, None, None)
        bundesland_id = self._bundesland(bundesland)
        landkreis_id = self._landkreis(bundesland_id, landkreis) if landkreis else None
        stadt_id = self._stadt(bundesland_id, landkreis_id, stadt) if stadt else None
        gemeinde_id = self._gemeinde(stadt_id, gemeinde) if stadt_id and gemeinde else None
        return OrtIds(bundesland_id, landkreis_id, stadt_id, gemeinde_id)

    def _bundesland(self, name: str) -> int:
        if name not in self.laender:
            cursor = self.conn.execute("INSERT INTO bundesland(name) VALUES (?)", (name,))
            self.laender[name] = cursor.lastrowid
        return self.laender[name]

    def _landkreis(self, bundesland_id: int, name: str) -> int:
        schluessel_kreis = (bundesland_id, name)
        if schluessel_kreis not in self.kreise:
            cursor = self.conn.execute(
                "INSERT INTO landkreis(bundesland_id, name) VALUES (?, ?)",
                (bundesland_id, name),
            )
            self.kreise[schluessel_kreis] = cursor.lastrowid
        return self.kreise[schluessel_kreis]

    def _stadt(self, bundesland_id: int, landkreis_id: int | None, name: str) -> int:
        schluessel_stadt = (bundesland_id, landkreis_id, name)
        if schluessel_stadt not in self.staedte:
            cursor = self.conn.execute(
                "INSERT INTO stadt(bundesland_id, landkreis_id, name) VALUES (?, ?, ?)",
                (bundesland_id, landkreis_id, name),
            )
            self.staedte[schluessel_stadt] = cursor.lastrowid
        return self.staedte[schluessel_stadt]

    def _gemeinde(self, stadt_id: int, name: str) -> int:
        schluessel_gemeinde = (stadt_id, name)
        if schluessel_gemeinde not in self.gemeinden:
            cursor = self.conn.execute(
                "INSERT INTO gemeinde(stadt_id, name) VALUES (?, ?)",
                (stadt_id, name),
            )
            self.gemeinden[schluessel_gemeinde] = cursor.lastrowid
        return self.gemeinden[schluessel_gemeinde]


def bekannte_schluessel(conn: sqlite3.Connection) -> set[tuple[str, str, str, str]]:
    zeilen = conn.execute("SELECT typ, plz, name_norm, strasse_norm FROM einrichtung")
    return {(zeile["typ"], zeile["plz"], zeile["name_norm"], zeile["strasse_norm"]) for zeile in zeilen}


def einrichtung_schreiben(
    conn: sqlite3.Connection,
    *,
    typ: str,
    name: str,
    strasse: str,
    plz: str,
    orte: OrtIds,
    telefon: str,
    email: str,
    web: str,
    breitengrad: float | None,
    laengengrad: float | None,
    koordinaten_herkunft: str | None,
    quelle: str,
) -> None:
    conn.execute(
        """
        INSERT INTO einrichtung (
            typ, name, name_norm, strasse, strasse_norm, plz,
            bundesland_id, landkreis_id, stadt_id, gemeinde_id,
            telefon, email, web,
            breitengrad, laengengrad, koordinaten_herkunft, quelle
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(typ, plz, name_norm, strasse_norm) DO UPDATE SET
            name = excluded.name,
            strasse = excluded.strasse,
            telefon = excluded.telefon,
            email = excluded.email,
            web = excluded.web,
            bundesland_id = COALESCE(einrichtung.bundesland_id, excluded.bundesland_id),
            landkreis_id = COALESCE(einrichtung.landkreis_id, excluded.landkreis_id),
            stadt_id = COALESCE(einrichtung.stadt_id, excluded.stadt_id),
            gemeinde_id = COALESCE(einrichtung.gemeinde_id, excluded.gemeinde_id),
            breitengrad = CASE
                WHEN einrichtung.koordinaten_herkunft = 'manuell' THEN einrichtung.breitengrad
                ELSE excluded.breitengrad
            END,
            laengengrad = CASE
                WHEN einrichtung.koordinaten_herkunft = 'manuell' THEN einrichtung.laengengrad
                ELSE excluded.laengengrad
            END,
            koordinaten_herkunft = CASE
                WHEN einrichtung.koordinaten_herkunft = 'manuell' THEN 'manuell'
                ELSE excluded.koordinaten_herkunft
            END,
            quelle = excluded.quelle,
            geaendert_am = datetime('now')
        """,
        (
            typ,
            name,
            schluessel(name),
            strasse,
            schluessel(strasse),
            plz,
            orte.bundesland_id,
            orte.landkreis_id,
            orte.stadt_id,
            orte.gemeinde_id,
            telefon,
            email,
            web,
            breitengrad,
            laengengrad,
            koordinaten_herkunft,
            quelle,
        ),
    )
