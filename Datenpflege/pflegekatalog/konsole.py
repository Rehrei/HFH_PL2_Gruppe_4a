"""Abfrage in der Konsole, welcher Eintrag bei einem Unterschied gilt."""

from __future__ import annotations

from collections.abc import Callable

from pflegekatalog.abgleich import Abbruch, Konflikt
from pflegekatalog.konstanten import TYP_NAMEN
from pflegekatalog.modell import FELDNAMEN

ANTWORTEN_LOKAL = {"l", "lokal"}
ANTWORTEN_IMPORT = {"i", "import"}
ANTWORTEN_ENDE = {"q", "abbrechen"}


def _anzeige(wert) -> str:
    if wert is None or wert == "":
        return "(leer)"
    return str(wert)


def _tabelle(konflikt: Konflikt) -> list[str]:
    zeilen = [
        (FELDNAMEN[feld], _anzeige(getattr(konflikt.lokal, feld)), _anzeige(getattr(konflikt.importiert, feld)))
        for feld in konflikt.felder
    ]
    kopf = ("Feld", "Lokal (Datenbank)", "Import")
    breiten = [max(len(zeile[spalte]) for zeile in [kopf, *zeilen]) for spalte in range(3)]
    return [
        "  ".join(zelle.ljust(breiten[spalte]) for spalte, zelle in enumerate(zeile)).rstrip()
        for zeile in [kopf, *zeilen]
    ]


def frage_konsole(
    konflikt: Konflikt,
    nummer: int,
    gesamt: int,
    eingabe: Callable[[str], str] | None = None,
    ausgabe: Callable[[str], None] = print,
) -> bool:
    """True: Import übernehmen. False: lokalen Eintrag behalten. Abbruch bei q."""
    eingabe = eingabe or input
    lokal = konflikt.lokal
    ausgabe("")
    ausgabe(f"--- Unterschied {nummer} von {gesamt} ---")
    ausgabe(f"{TYP_NAMEN[lokal.typ]}: {lokal.name}")
    ausgabe(f"{lokal.plz} {lokal.ort}, {lokal.strasse} {lokal.hausnummer}".strip())
    for zeile in _tabelle(konflikt):
        ausgabe("  " + zeile)
    while True:
        try:
            antwort = eingabe("[l] lokal behalten  [i] Import übernehmen  [q] abbrechen > ")
        except EOFError:
            raise Abbruch(
                "Keine Eingabe möglich. Ohne Konsole bitte mit -f (Import gewinnt) "
                "oder -c (lokal gewinnt) starten."
            ) from None
        antwort = antwort.strip().casefold()
        if antwort in ANTWORTEN_LOKAL:
            return False
        if antwort in ANTWORTEN_IMPORT:
            return True
        if antwort in ANTWORTEN_ENDE:
            raise Abbruch("Abgebrochen. Es wurde nichts in die Datenbank geschrieben.")
        ausgabe("Bitte l, i oder q eingeben.")
