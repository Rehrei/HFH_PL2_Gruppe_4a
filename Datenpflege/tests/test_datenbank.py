"""Ende-zu-Ende-Test gegen einen echten MySQL/MariaDB-Server.

Läuft nur, wenn PFLEGE_TEST_SCHEMA auf pflege_db_backup.sql zeigt. Verbindung über
DB_HOST, DB_PORT, DB_USER, DB_PASS (Benutzer braucht CREATE/DROP-Rechte).
Der Test legt eine eigene Datenbank pflege_test_<zufall> an und löscht sie wieder.
pflege_db wird nie angefasst.
"""

from __future__ import annotations

import io
import os
import unittest
import uuid
from contextlib import redirect_stderr, redirect_stdout
from decimal import Decimal
from pathlib import Path
from unittest import mock

import pymysql
from pymysql.constants import CLIENT

from pflegekatalog.cli import main
from pflegekatalog.importer import Bericht
from pflegekatalog.modell import Einrichtung

SCHEMA = os.environ.get("PFLEGE_TEST_SCHEMA", "")


def eingang(*eintraege: Einrichtung) -> dict:
    return {e.schluessel(): e for e in eintraege}


def haus(**felder) -> Einrichtung:
    basis = dict(
        typ="pflegeheim",
        name="Haus Sonne",
        strasse="Hauptstraße",
        hausnummer="5",
        plz="12345",
        ort="Musterstadt",
        gemeinde_stadt="Muster",
        landkreis="Kreis M",
        bundesland="Hessen",
        webseite="https://sonne.example",
        telefon="0123 111",
        email="info@sonne.example",
        breitengrad=Decimal("50.123456"),
        laengengrad=Decimal("8.654321"),
    )
    basis.update(felder)
    return Einrichtung(**basis)


@unittest.skipUnless(SCHEMA and Path(SCHEMA).is_file(), "PFLEGE_TEST_SCHEMA nicht gesetzt")
class DatenbankTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.verbindung_args = dict(
            host=os.environ.get("DB_HOST", "localhost"),
            port=int(os.environ.get("DB_PORT", "3306")),
            user=os.environ["DB_USER"],
            password=os.environ.get("DB_PASS", ""),
            charset="utf8mb4",
            autocommit=True,
        )
        cls.name = f"pflege_test_{uuid.uuid4().hex[:8]}"
        with pymysql.connect(**cls.verbindung_args) as admin:
            admin.cursor().execute(f"CREATE DATABASE `{cls.name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
        with pymysql.connect(
            **cls.verbindung_args, database=cls.name, client_flag=CLIENT.MULTI_STATEMENTS
        ) as schema:
            cursor = schema.cursor()
            cursor.execute(Path(SCHEMA).read_text(encoding="utf-8"))
            while cursor.nextset():
                pass
        cls.umgebung = {
            "DB_HOST": cls.verbindung_args["host"],
            "DB_PORT": str(cls.verbindung_args["port"]),
            "DB_NAME": cls.name,
            "DB_USER": cls.verbindung_args["user"],
            "DB_PASS": cls.verbindung_args["password"],
        }

    @classmethod
    def tearDownClass(cls):
        with pymysql.connect(**cls.verbindung_args) as admin:
            admin.cursor().execute(f"DROP DATABASE IF EXISTS `{cls.name}`")

    @classmethod
    def sql(cls, sql: str, parameter: tuple = ()):
        with pymysql.connect(**cls.verbindung_args, database=cls.name) as verbindung:
            cursor = verbindung.cursor()
            cursor.execute(sql, parameter)
            return cursor.fetchall()

    def setUp(self):
        for tabelle in ("21_ansprechpartner", "22_pflegeeinrichtung", "01_einrichtungstyp"):
            self.sql(f"DELETE FROM `{tabelle}`")

    def lauf(self, argv, daten, antworten=()):
        out, err = io.StringIO(), io.StringIO()
        with (
            mock.patch.dict(os.environ, self.umgebung),
            mock.patch("builtins.input", side_effect=list(antworten)),
            mock.patch("pflegekatalog.cli.lese_dateneingang", return_value=(daten, Bericht())),
            redirect_stdout(out),
            redirect_stderr(err),
        ):
            code = main(argv)
        return code, out.getvalue(), err.getvalue()

    def anzahl(self, tabelle: str) -> int:
        return self.sql(f"SELECT COUNT(*) FROM `{tabelle}`")[0][0]

    def telefon(self, name: str):
        return self.sql(
            "SELECT a.telefon FROM `21_ansprechpartner` a JOIN `22_pflegeeinrichtung` e "
            "ON e.pflegeeinrichtung_id = a.pflegeeinrichtung_id "
            "WHERE e.einrichtungsname = %s AND a.funktion = 'Einrichtung (Import)'",
            (name,),
        )[0][0]

    # --- Import ------------------------------------------------------------

    def test_erstimport_und_zweiter_lauf(self):
        daten = lambda: eingang(
            haus(),
            haus(typ="ambulant", name="Pflegedienst Nord", telefon="", email="", webseite=""),
            haus(typ="tagespflege", name="Tag Süd", plz="54321", ort="Süd", telefon="0999", email=""),
        )
        code, ausgabe, fehler = self.lauf(["einlesen"], daten())
        self.assertEqual(code, 0, fehler)
        self.assertIn("3 neu", ausgabe)
        self.assertEqual(self.anzahl("22_pflegeeinrichtung"), 3)
        self.assertEqual(self.anzahl("21_ansprechpartner"), 2)  # nur mit Telefon/E-Mail
        self.assertEqual(
            sorted(z[0] for z in self.sql("SELECT einrichtungstyp FROM `01_einrichtungstyp`")),
            ["Ambulanter Pflegedienst", "Pflegeheim", "Tagespflege"],
        )
        zeile = self.sql(
            "SELECT einrichtungsname, strasse, hausnummer, plz, ort, gemeinde_stadt, landkreis, bundesland, "
            "webseite, breitengrad, laengengrad FROM `22_pflegeeinrichtung` WHERE einrichtungsname='Haus Sonne'"
        )[0]
        self.assertEqual(zeile[:9], ("Haus Sonne", "Hauptstraße", "5", "12345", "Musterstadt", "Muster", "Kreis M", "Hessen", "https://sonne.example"))
        self.assertEqual(zeile[9:], (Decimal("50.123456"), Decimal("8.654321")))
        self.assertEqual(
            self.sql("SELECT vorname, nachname, telefon, `e-mail`, funktion FROM `21_ansprechpartner` WHERE telefon='0123 111'")[0],
            ("", "Zentrale", "0123 111", "info@sonne.example", "Einrichtung (Import)"),
        )
        self.assertIsNone(self.sql("SELECT webseite FROM `22_pflegeeinrichtung` WHERE einrichtungsname='Pflegedienst Nord'")[0][0])

        code, ausgabe, _ = self.lauf(["einlesen"], daten())  # nichts mehr zu tun, keine Frage
        self.assertEqual(code, 0)
        self.assertIn("0 neu, 3 unverändert, 0 überschrieben, 0 lokal behalten", ausgabe)
        self.assertEqual(self.anzahl("22_pflegeeinrichtung"), 3)

    def test_vorhandener_typ_wird_wiederverwendet(self):
        self.sql("INSERT INTO `01_einrichtungstyp` (einrichtungstyp) VALUES ('Pflegedienst'), ('Beratungsstelle')")
        code, ausgabe, fehler = self.lauf(["einlesen"], eingang(haus(typ="ambulant", name="Dienst")))
        self.assertEqual(code, 0, fehler)
        self.assertNotIn("Ambulanter Pflegedienst", ausgabe)
        self.assertEqual(self.anzahl("01_einrichtungstyp"), 2)
        self.assertEqual(
            self.sql("SELECT t.einrichtungstyp FROM `22_pflegeeinrichtung` e JOIN `01_einrichtungstyp` t USING (einrichtungstyp_id)")[0][0],
            "Pflegedienst",
        )

    # --- Unterschiede: Modi ---------------------------------------------------

    def erst_importieren(self):
        code, _, fehler = self.lauf(["einlesen"], eingang(haus()))
        self.assertEqual(code, 0, fehler)

    def test_fragen_lokal_behalten(self):
        self.erst_importieren()
        code, ausgabe, _ = self.lauf(["einlesen"], eingang(haus(telefon="0123 222")), antworten=["l"])
        self.assertEqual(code, 0)
        self.assertEqual(self.telefon("Haus Sonne"), "0123 111")
        self.assertIn("0 überschrieben, 1 lokal behalten", ausgabe)

    def test_fragen_import_uebernehmen(self):
        self.erst_importieren()
        code, ausgabe, _ = self.lauf(
            ["einlesen"], eingang(haus(telefon="0123 222", landkreis="Kreis Neu")), antworten=["i"]
        )
        self.assertEqual(code, 0)
        self.assertEqual(self.telefon("Haus Sonne"), "0123 222")
        self.assertEqual(self.sql("SELECT landkreis FROM `22_pflegeeinrichtung`")[0][0], "Kreis Neu")
        self.assertIn("1 überschrieben, 0 lokal behalten", ausgabe)
        self.assertEqual(self.anzahl("22_pflegeeinrichtung"), 1)

    def test_abbruch_schreibt_nichts(self):
        self.erst_importieren()
        daten = eingang(haus(telefon="0123 222"), haus(name="Neues Haus", plz="99999"))
        code, _, fehler = self.lauf(["einlesen"], daten, antworten=["q"])
        self.assertEqual(code, 1)
        self.assertIn("nichts", fehler.casefold())
        self.assertEqual(self.telefon("Haus Sonne"), "0123 111")
        self.assertEqual(self.anzahl("22_pflegeeinrichtung"), 1)

    def test_force_ueberschreibt_ohne_frage(self):
        self.erst_importieren()
        daten = eingang(haus(telefon="0123 222"), haus(name="Neues Haus", plz="99999"))
        code, ausgabe, _ = self.lauf(["einlesen", "-f"], daten)  # input hätte keine Antworten mehr
        self.assertEqual(code, 0)
        self.assertEqual(self.telefon("Haus Sonne"), "0123 222")
        self.assertEqual(self.anzahl("22_pflegeeinrichtung"), 2)
        self.assertIn("1 neu, 0 unverändert, 1 überschrieben", ausgabe)

    def test_care_behaelt_lokal_legt_neue_an(self):
        self.erst_importieren()
        daten = eingang(haus(telefon="0123 222"), haus(name="Neues Haus", plz="99999"))
        code, ausgabe, _ = self.lauf(["einlesen", "-c"], daten)
        self.assertEqual(code, 0)
        self.assertEqual(self.telefon("Haus Sonne"), "0123 111")
        self.assertEqual(self.anzahl("22_pflegeeinrichtung"), 2)
        self.assertIn("1 neu, 0 unverändert, 0 überschrieben, 1 lokal behalten", ausgabe)

    def test_force_und_care_zusammen_nicht_erlaubt(self):
        with self.assertRaises(SystemExit) as ctx, redirect_stderr(io.StringIO()):
            self.lauf(["einlesen", "-f", "-c"], eingang(haus()))
        self.assertEqual(ctx.exception.code, 2)

    # --- Schutz lokaler Daten -------------------------------------------------

    def test_leeres_importfeld_loescht_lokal_nichts_und_handkontakte_bleiben(self):
        self.erst_importieren()
        einrichtung_id = self.sql("SELECT pflegeeinrichtung_id FROM `22_pflegeeinrichtung`")[0][0]
        self.sql(
            "INSERT INTO `21_ansprechpartner` (pflegeeinrichtung_id, vorname, nachname, telefon, funktion) "
            "VALUES (%s, 'Erika', 'Muster', '0555', 'Leitung')",
            (einrichtung_id,),
        )
        daten = eingang(haus(webseite="", telefon="0123 222", email=""))
        code, _, fehler = self.lauf(["einlesen", "-f"], daten)
        self.assertEqual(code, 0, fehler)
        self.assertEqual(self.sql("SELECT webseite FROM `22_pflegeeinrichtung`")[0][0], "https://sonne.example")
        self.assertEqual(self.telefon("Haus Sonne"), "0123 222")
        self.assertEqual(
            self.sql("SELECT e.`e-mail` FROM `21_ansprechpartner` e WHERE funktion = 'Einrichtung (Import)'")[0][0],
            "info@sonne.example",
        )
        self.assertEqual(
            self.sql("SELECT vorname, telefon FROM `21_ansprechpartner` WHERE funktion = 'Leitung'"), (("Erika", "0555"),)
        )

    def test_lokaler_eintrag_ohne_kontakt_bekommt_kontakt(self):
        self.sql("INSERT INTO `01_einrichtungstyp` (einrichtungstyp) VALUES ('Pflegeheim')")
        typ_id = self.sql("SELECT einrichtungstyp_id FROM `01_einrichtungstyp`")[0][0]
        self.sql(
            "INSERT INTO `22_pflegeeinrichtung` (einrichtungstyp_id, einrichtungsname, strasse, hausnummer, plz, ort) "
            "VALUES (%s, 'Haus Sonne', 'Hauptstraße', '5', '12345', 'Musterstadt')",
            (typ_id,),
        )
        code, _, fehler = self.lauf(["einlesen", "-f"], eingang(haus()))
        self.assertEqual(code, 0, fehler)
        self.assertEqual(self.anzahl("22_pflegeeinrichtung"), 1)  # kein Duplikat
        self.assertEqual(self.telefon("Haus Sonne"), "0123 111")

    # --- Fehlerfall -------------------------------------------------------------

    def test_datenbankfehler_rollt_alles_zurueck(self):
        zu_lang = haus(name="X" * 200, plz="99999")  # umgeht die Längenprüfung des Importers
        code, _, fehler = self.lauf(["einlesen"], eingang(haus(), zu_lang))
        self.assertEqual(code, 1)
        self.assertIn("Nichts wurde geschrieben", fehler)
        self.assertEqual(self.anzahl("22_pflegeeinrichtung"), 0)
        self.assertEqual(self.anzahl("01_einrichtungstyp"), 0)


if __name__ == "__main__":
    unittest.main()
