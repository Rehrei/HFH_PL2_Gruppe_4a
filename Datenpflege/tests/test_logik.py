"""Tests ohne Datenbank: python -m unittest discover -s tests"""

from __future__ import annotations

import contextlib
import io
import os
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from pflegekatalog import config
from pflegekatalog.abgleich import Abbruch, Modus, abgleichen, unterschiede
from pflegekatalog.konsole import frage_konsole
from pflegekatalog.modell import Einrichtung


def einrichtung(**felder) -> Einrichtung:
    basis = dict(typ="pflegeheim", name="Haus Sonne", strasse="Hauptstraße", hausnummer="5", plz="12345", ort="Musterstadt")
    basis.update(felder)
    return Einrichtung(**basis)


def als_dict(*eintraege: Einrichtung) -> dict:
    return {e.schluessel(): e for e in eintraege}


class UnterschiedeTest(unittest.TestCase):
    def test_gleich(self):
        self.assertEqual(unterschiede(einrichtung(telefon="1"), einrichtung(telefon="1")), [])

    def test_abweichender_wert(self):
        self.assertEqual(unterschiede(einrichtung(telefon="1"), einrichtung(telefon="2")), ["telefon"])

    def test_leerer_import_loescht_nichts(self):
        self.assertEqual(unterschiede(einrichtung(telefon="1"), einrichtung(telefon="")), [])

    def test_lokal_leer_import_gefuellt(self):
        self.assertEqual(unterschiede(einrichtung(), einrichtung(webseite="x.de")), ["webseite"])

    def test_koordinaten_als_decimal(self):
        lokal = einrichtung(breitengrad=Decimal("52.100000"))
        self.assertEqual(unterschiede(lokal, einrichtung(breitengrad=Decimal("52.1"))), [])
        self.assertEqual(unterschiede(lokal, einrichtung(breitengrad=Decimal("52.2"))), ["breitengrad"])


class AbgleichTest(unittest.TestCase):
    def setUp(self):
        self.lokal = einrichtung(telefon="111", id=7)
        self.gleich = einrichtung(name="Haus Mond", plz="54321")
        self.lokal_alle = als_dict(self.lokal, self.gleich)
        self.import_alle = als_dict(
            einrichtung(telefon="222"),  # abweichend
            einrichtung(name="Haus Mond", plz="54321"),  # identisch
            einrichtung(name="Haus Stern", plz="99999"),  # neu
        )

    def test_force_ueberschreibt_ohne_frage(self):
        plan = abgleichen(self.import_alle, self.lokal_alle, Modus.IMPORT)
        self.assertEqual([e.name for e in plan.neu], ["Haus Stern"])
        self.assertEqual(len(plan.ueberschreiben), 1)
        self.assertEqual(plan.ueberschreiben[0].lokal.id, 7)
        self.assertEqual((plan.unveraendert, plan.lokal_behalten), (1, 0))

    def test_care_behaelt_lokal_legt_aber_neue_an(self):
        plan = abgleichen(self.import_alle, self.lokal_alle, Modus.LOKAL)
        self.assertEqual([e.name for e in plan.neu], ["Haus Stern"])
        self.assertEqual(plan.ueberschreiben, [])
        self.assertEqual((plan.unveraendert, plan.lokal_behalten), (1, 1))

    def test_fragen_nutzt_entscheidung(self):
        fragen = []

        def ja(konflikt, nummer, gesamt):
            fragen.append((nummer, gesamt))
            return True

        plan = abgleichen(self.import_alle, self.lokal_alle, Modus.FRAGEN, ja)
        self.assertEqual(fragen, [(1, 1)])
        self.assertEqual(len(plan.ueberschreiben), 1)
        plan = abgleichen(self.import_alle, self.lokal_alle, Modus.FRAGEN, lambda *_: False)
        self.assertEqual((len(plan.ueberschreiben), plan.lokal_behalten), (0, 1))

    def test_abbruch_wird_durchgereicht(self):
        def nein(*_):
            raise Abbruch("stop")

        with self.assertRaises(Abbruch):
            abgleichen(self.import_alle, self.lokal_alle, Modus.FRAGEN, nein)


class KonsoleTest(unittest.TestCase):
    def frage(self, antworten):
        konflikt = abgleichen(
            als_dict(einrichtung(telefon="222")), als_dict(einrichtung(telefon="111", id=1)), Modus.IMPORT
        ).ueberschreiben[0]
        eingaben = iter(antworten)
        zeilen: list[str] = []

        def eingabe(_):
            try:
                return next(eingaben)
            except StopIteration:
                raise EOFError from None

        return frage_konsole(konflikt, 1, 1, eingabe, zeilen.append), zeilen

    def test_import(self):
        self.assertTrue(self.frage(["I"])[0])

    def test_lokal_nach_ungueltiger_eingabe(self):
        ergebnis, zeilen = self.frage(["x", "l"])
        self.assertFalse(ergebnis)
        self.assertIn("Bitte l, i oder q eingeben.", zeilen)

    def test_tabelle_zeigt_beide_werte(self):
        _, zeilen = self.frage(["l"])
        text = "\n".join(zeilen)
        self.assertIn("111", text)
        self.assertIn("222", text)

    def test_abbrechen_und_eof(self):
        with self.assertRaises(Abbruch):
            self.frage(["q"])
        with self.assertRaises(Abbruch):
            self.frage([])


class ConfigTest(unittest.TestCase):
    def test_env_datei_und_vorrang_der_umgebung(self):
        with tempfile.TemporaryDirectory() as ordner:
            datei = Path(ordner) / "x.env"
            datei.write_text(
                "# Kommentar\nDB_HOST=dbserver\nDB_PORT=3307\nDB_NAME='mein_db'\nDB_USER=hans\nDB_PASS=\"p=ss\"\n",
                encoding="utf-8",
            )
            cfg = config.laden({"PFLEGE_ENV": str(datei), "DB_USER": "peter"})
        self.assertEqual((cfg.host, cfg.port, cfg.name), ("dbserver", 3307, "mein_db"))
        self.assertEqual((cfg.user, cfg.passwort), ("peter", "p=ss"))
        self.assertNotIn("p=ss", repr(cfg))

    def test_ohne_benutzer_fehler(self):
        with tempfile.TemporaryDirectory() as ordner:
            leer = Path(ordner) / "leer.env"
            leer.write_text("", encoding="utf-8")
            with self.assertRaises(config.KonfigurationsFehler):
                config.laden({"PFLEGE_ENV": str(leer)})

    @unittest.skipUnless(os.name == "posix", "Dateirechte nur unter Linux")
    def test_warnung_bei_offenen_dateirechten(self):
        with tempfile.TemporaryDirectory() as ordner:
            datei = Path(ordner) / "x.env"
            datei.write_text("DB_USER=hans\n", encoding="utf-8")
            for modus, warnung in ((0o644, True), (0o600, False)):
                datei.chmod(modus)
                fehlerausgabe = io.StringIO()
                with contextlib.redirect_stderr(fehlerausgabe):
                    config.laden({"PFLEGE_ENV": str(datei)})
                self.assertEqual("chmod 600" in fehlerausgabe.getvalue(), warnung, oct(modus))

    def test_fehlende_env_datei(self):
        with self.assertRaises(config.KonfigurationsFehler):
            config.laden({"PFLEGE_ENV": "gibt-es-nicht.env"})


if __name__ == "__main__":
    unittest.main()
