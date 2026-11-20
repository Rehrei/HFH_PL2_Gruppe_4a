"""Konsolenaufruf für Linux und Windows."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from pflegekatalog.importer import umwandeln
from pflegekatalog.pfade import AUSGABE_ORDNER


def baue_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pflegekatalog",
        description="Wandelt Pflege-Navigator-Exporte der AOK in eine CSV-Datei um.",
    )
    befehle = parser.add_subparsers(dest="befehl", required=True)
    einlesen = befehle.add_parser(
        "einlesen",
        help="Dateneingang einlesen und nach Export schreiben",
    )
    einlesen.add_argument(
        "--ausgabe",
        type=Path,
        help=f"Zieldatei, sonst {AUSGABE_ORDNER / 'pflegeeinrichtungen.csv'}",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = baue_parser().parse_args(argv)
    if args.befehl == "einlesen":
        try:
            bericht = umwandeln(args.ausgabe)
        except FileNotFoundError as fehler:
            print(fehler, file=sys.stderr)
            return 1
        except PermissionError:
            print(
                "Die CSV-Datei ist geöffnet. Bitte schließen und den Befehl erneut ausführen.",
                file=sys.stderr,
            )
            return 1
        print(
            f"Fertig: {bericht.neu} Einrichtungen in {bericht.ausgabe} "
            f"({bericht.aktualisiert} Dubletten ersetzt, {bericht.ohne_name} ohne Namen, "
            f"{bericht.dateien} Dateien, {bericht.sekunden:.1f} s, "
            f"Bundesland wich ab: {bericht.bundesland_abweichung})"
        )
        return 0
    return 2
