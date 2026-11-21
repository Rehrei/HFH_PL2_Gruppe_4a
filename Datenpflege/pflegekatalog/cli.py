"""Konsolenaufruf für Linux und Windows."""

from __future__ import annotations

import argparse
import sys

from pflegekatalog.abgleich import Abbruch, Modus, abgleichen
from pflegekatalog.config import KonfigurationsFehler, laden
from pflegekatalog.datenbank import Datenbank, DatenbankFehler
from pflegekatalog.importer import lese_dateneingang
from pflegekatalog.konsole import frage_konsole


def baue_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pflegekatalog",
        description="Liest Pflege-Navigator-Exporte der AOK in die Datenbank pflege_db ein.",
    )
    befehle = parser.add_subparsers(dest="befehl", required=True)
    einlesen = befehle.add_parser(
        "einlesen",
        help="Dateneingang einlesen und in die Datenbank schreiben",
        description=(
            "Unterscheidet sich ein Eintrag in der Datenbank vom Import, entscheidet "
            "der Benutzer in der Konsole. Ein leeres Importfeld überschreibt nie "
            "einen lokalen Wert."
        ),
    )
    modus = einlesen.add_mutually_exclusive_group()
    modus.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="Import überschreibt abweichende lokale Einträge automatisch",
    )
    modus.add_argument(
        "-c",
        "--care",
        action="store_true",
        help="Lokale Einträge bleiben, abweichende Importeinträge werden verworfen",
    )
    return parser


def _einlesen(force: bool, care: bool) -> int:
    modus = Modus.IMPORT if force else Modus.LOKAL if care else Modus.FRAGEN
    config = laden()
    with Datenbank.verbinden(config) as datenbank:
        print(f"Modus: {modus.value}")
        einrichtungen, bericht = lese_dateneingang()
        typ_ids = datenbank.typ_ids()
        lokal = datenbank.lokale_einrichtungen(typ_ids)
        plan = abgleichen(einrichtungen, lokal, modus, frage_konsole)
        ergebnis = datenbank.schreiben(plan, typ_ids)

    for zeile in bericht.zu_lang:
        print(f"Übersprungen: {zeile}")
    if ergebnis.typen_angelegt:
        print(f"Einrichtungstypen neu angelegt: {', '.join(ergebnis.typen_angelegt)}")
    print(
        f"Fertig: {len(einrichtungen)} Einträge geprüft: {ergebnis.neu} neu, "
        f"{plan.unveraendert} unverändert, {ergebnis.ueberschrieben} überschrieben, "
        f"{plan.lokal_behalten} lokal behalten. "
        f"({bericht.dubletten} Dubletten im Import, {bericht.ohne_name} ohne Namen, "
        f"{len(bericht.zu_lang)} zu lang, {bericht.dateien} Dateien, "
        f"{bericht.sekunden:.1f} s, Bundesland wich ab: {bericht.bundesland_abweichung})"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    args = baue_parser().parse_args(argv)
    try:
        if args.befehl == "einlesen":
            return _einlesen(args.force, args.care)
    except (KonfigurationsFehler, DatenbankFehler, FileNotFoundError, Abbruch) as fehler:
        print(fehler, file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nAbgebrochen. Es wurde nichts in die Datenbank geschrieben.", file=sys.stderr)
        return 130
    return 2
