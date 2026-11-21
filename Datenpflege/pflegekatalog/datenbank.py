"""Zugriff auf die MySQL-Datenbank pflege_db (Schema siehe pflege_db_backup.sql).

Das Schema bleibt unverändert. Telefon und E-Mail einer Einrichtung haben dort
keine eigene Spalte, sondern nur beim Ansprechpartner. Der Import führt je
Einrichtung genau einen Kontakt mit der Funktion KONTAKT_FUNKTION. Von Hand
angelegte Ansprechpartner fasst er nicht an.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

import pymysql

from pflegekatalog.abgleich import Plan
from pflegekatalog.config import DbConfig
from pflegekatalog.konstanten import TYP_NAMEN
from pflegekatalog.modell import Einrichtung

KONTAKT_VORNAME = ""
KONTAKT_NACHNAME = "Zentrale"
KONTAKT_FUNKTION = "Einrichtung (Import)"

# Namen, unter denen ein Typ schon in 01_einrichtungstyp stehen kann.
TYP_ALIASSE = {
    "ambulant": ("ambulanter pflegedienst", "pflegedienst"),
    "tagespflege": ("tagespflege",),
    "nachtpflege": ("nachtpflege",),
    "pflegeheim": ("pflegeheim",),
}

# Importfeld -> Spalte in 22_pflegeeinrichtung
EINRICHTUNGS_SPALTEN = {
    "strasse": "strasse",
    "hausnummer": "hausnummer",
    "ort": "ort",
    "gemeinde_stadt": "gemeinde_stadt",
    "landkreis": "landkreis",
    "bundesland": "bundesland",
    "webseite": "webseite",
    "breitengrad": "breitengrad",
    "laengengrad": "laengengrad",
}
KONTAKT_SPALTEN = {"telefon": "telefon", "email": "e-mail"}


class DatenbankFehler(Exception):
    pass


@dataclass
class Ergebnis:
    neu: int = 0
    ueberschrieben: int = 0
    typen_angelegt: list[str] | None = None


def _fehlertext(fehler: pymysql.MySQLError) -> str:
    code = fehler.args[0] if fehler.args else "?"
    text = fehler.args[1] if len(fehler.args) > 1 else str(fehler)
    return f"Datenbankfehler {code}: {text}"


def _text(wert) -> str:
    return "" if wert is None else str(wert)


def _oder_null(wert):
    return None if wert in ("", None) else wert


class Datenbank:
    def __init__(self, verbindung: pymysql.connections.Connection):
        self._verbindung = verbindung

    @classmethod
    def verbinden(cls, config: DbConfig) -> "Datenbank":
        try:
            verbindung = pymysql.connect(
                host=config.host,
                port=config.port,
                user=config.user,
                password=config.passwort,
                database=config.name,
                charset="utf8mb4",
                autocommit=True,
                connect_timeout=10,
            )
        except pymysql.MySQLError as fehler:
            raise DatenbankFehler(
                f"Keine Verbindung zu {config.name} auf {config.host}:{config.port}. "
                + _fehlertext(fehler)
            ) from None
        return cls(verbindung)

    def __enter__(self) -> "Datenbank":
        return self

    def __exit__(self, *_) -> None:
        self.schliessen()

    def schliessen(self) -> None:
        try:
            self._verbindung.close()
        except pymysql.MySQLError:
            pass

    def _abfrage(self, sql: str, parameter: tuple = ()) -> tuple:
        try:
            with self._verbindung.cursor() as cursor:
                cursor.execute(sql, parameter)
                return cursor.fetchall()
        except pymysql.MySQLError as fehler:
            raise DatenbankFehler(_fehlertext(fehler)) from None

    # --- Einrichtungen lesen ---------------------------------------------

    def typ_ids(self) -> dict[str, list[int]]:
        """Typ-Kürzel (z. B. 'pflegeheim') -> IDs in 01_einrichtungstyp. Fehlende Typen fehlen hier."""
        ergebnis: dict[str, list[int]] = {}
        for typ_id, name in self._abfrage(
            "SELECT einrichtungstyp_id, einrichtungstyp FROM `01_einrichtungstyp` ORDER BY einrichtungstyp_id"
        ):
            klein = (name or "").strip().casefold()
            for typ, aliasse in TYP_ALIASSE.items():
                if klein in aliasse:
                    ergebnis.setdefault(typ, []).append(typ_id)
        return ergebnis

    def lokale_einrichtungen(
        self, typ_ids: dict[str, list[int]]
    ) -> dict[tuple[str, str, str, str], Einrichtung]:
        typ_von_id = {typ_id: typ for typ, ids in typ_ids.items() for typ_id in ids}
        if not typ_von_id:
            return {}
        platzhalter = ",".join(["%s"] * len(typ_von_id))
        zeilen = self._abfrage(
            "SELECT e.pflegeeinrichtung_id, e.einrichtungstyp_id, e.einrichtungsname, e.webseite, "
            "e.strasse, e.hausnummer, e.plz, e.ort, e.gemeinde_stadt, e.landkreis, e.bundesland, "
            "e.breitengrad, e.laengengrad, a.ansprechpartner_id, a.telefon, a.`e-mail` "
            "FROM `22_pflegeeinrichtung` e "
            "LEFT JOIN `21_ansprechpartner` a "
            "ON a.pflegeeinrichtung_id = e.pflegeeinrichtung_id AND a.funktion = %s "
            f"WHERE e.einrichtungstyp_id IN ({platzhalter}) "
            "ORDER BY e.pflegeeinrichtung_id, a.ansprechpartner_id",
            (KONTAKT_FUNKTION, *typ_von_id),
        )
        lokal: dict[tuple[str, str, str, str], Einrichtung] = {}
        for z in zeilen:
            einrichtung = Einrichtung(
                typ=typ_von_id[z[1]],
                name=_text(z[2]),
                webseite=_text(z[3]),
                strasse=_text(z[4]),
                hausnummer=_text(z[5]),
                plz=_text(z[6]),
                ort=_text(z[7]),
                gemeinde_stadt=_text(z[8]),
                landkreis=_text(z[9]),
                bundesland=_text(z[10]),
                breitengrad=None if z[11] is None else Decimal(z[11]),
                laengengrad=None if z[12] is None else Decimal(z[12]),
                telefon=_text(z[14]),
                email=_text(z[15]),
                id=z[0],
                kontakt_id=z[13],
            )
            lokal.setdefault(einrichtung.schluessel(), einrichtung)
        return lokal

    # --- Schreiben ---------------------------------------------------------

    def schreiben(self, plan: Plan, typ_ids: dict[str, list[int]]) -> Ergebnis:
        """Legt neue Einrichtungen an und überschreibt die freigegebenen. Alles oder nichts."""
        verbindung = self._verbindung
        ergebnis = Ergebnis(typen_angelegt=[])
        ids = {typ: liste[0] for typ, liste in typ_ids.items()}
        try:
            verbindung.begin()
            with verbindung.cursor() as cursor:
                for typ in sorted({e.typ for e in plan.neu} - ids.keys()):
                    cursor.execute(
                        "INSERT INTO `01_einrichtungstyp` (einrichtungstyp) VALUES (%s)",
                        (TYP_NAMEN[typ],),
                    )
                    ids[typ] = cursor.lastrowid
                    ergebnis.typen_angelegt.append(TYP_NAMEN[typ])

                for nummer, e in enumerate(plan.neu, start=1):
                    cursor.execute(
                        "INSERT INTO `22_pflegeeinrichtung` (einrichtungstyp_id, einrichtungsname, "
                        "webseite, strasse, hausnummer, plz, ort, gemeinde_stadt, landkreis, "
                        "bundesland, breitengrad, laengengrad) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                        (
                            ids[e.typ],
                            e.name,
                            _oder_null(e.webseite),
                            e.strasse,
                            e.hausnummer,
                            e.plz,
                            e.ort,
                            _oder_null(e.gemeinde_stadt),
                            _oder_null(e.landkreis),
                            _oder_null(e.bundesland),
                            e.breitengrad,
                            e.laengengrad,
                        ),
                    )
                    if e.telefon or e.email:
                        self._kontakt_anlegen(cursor, cursor.lastrowid, e)
                    if nummer % 5000 == 0:
                        print(f"  {nummer} von {len(plan.neu)} neuen Einträgen geschrieben ...")
                ergebnis.neu = len(plan.neu)

                for konflikt in plan.ueberschreiben:
                    self._aktualisieren(cursor, konflikt.lokal, konflikt.importiert, konflikt.felder)
                ergebnis.ueberschrieben = len(plan.ueberschreiben)
            verbindung.commit()
        except pymysql.MySQLError as fehler:
            verbindung.rollback()
            raise DatenbankFehler(_fehlertext(fehler) + " Nichts wurde geschrieben.") from None
        except BaseException:
            verbindung.rollback()
            raise
        return ergebnis

    @staticmethod
    def _kontakt_anlegen(cursor, einrichtung_id: int, e: Einrichtung) -> None:
        cursor.execute(
            "INSERT INTO `21_ansprechpartner` (pflegeeinrichtung_id, vorname, nachname, telefon, "
            "`e-mail`, funktion) VALUES (%s, %s, %s, %s, %s, %s)",
            (
                einrichtung_id,
                KONTAKT_VORNAME,
                KONTAKT_NACHNAME,
                _oder_null(e.telefon),
                _oder_null(e.email),
                KONTAKT_FUNKTION,
            ),
        )

    def _aktualisieren(self, cursor, lokal: Einrichtung, neu: Einrichtung, felder: list[str]) -> None:
        zuweisungen = [f"`{EINRICHTUNGS_SPALTEN[f]}` = %s" for f in felder if f in EINRICHTUNGS_SPALTEN]
        if zuweisungen:
            werte = [getattr(neu, f) for f in felder if f in EINRICHTUNGS_SPALTEN]
            cursor.execute(
                f"UPDATE `22_pflegeeinrichtung` SET {', '.join(zuweisungen)} "
                "WHERE pflegeeinrichtung_id = %s",
                (*werte, lokal.id),
            )
        kontakt_felder = [f for f in felder if f in KONTAKT_SPALTEN]
        if not kontakt_felder:
            return
        if lokal.kontakt_id is None:
            self._kontakt_anlegen(cursor, lokal.id, neu)
            return
        zuweisungen = [f"`{KONTAKT_SPALTEN[f]}` = %s" for f in kontakt_felder]
        cursor.execute(
            f"UPDATE `21_ansprechpartner` SET {', '.join(zuweisungen)} WHERE ansprechpartner_id = %s",
            (*[getattr(neu, f) for f in kontakt_felder], lokal.kontakt_id),
        )
