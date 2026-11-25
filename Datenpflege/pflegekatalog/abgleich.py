"""Vergleicht importierte Einrichtungen mit den Einträgen in der Datenbank.

Regeln:
- Kein Treffer in der Datenbank: Der Eintrag wird neu angelegt.
- Treffer ohne Unterschied: nichts zu tun.
- Treffer mit Unterschied: Entscheidung je nach Modus (siehe Modus).

Ein Unterschied liegt nur vor, wenn der Import für ein Feld einen Wert liefert,
der vom lokalen Wert abweicht. Ein leeres Importfeld löscht lokale Daten nie.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum

from pflegekatalog.modell import ABGLEICHSFELDER, Einrichtung

Schluessel = tuple[str, str, str, str]


class Abbruch(Exception):
    """Der Benutzer bricht ab. Es wurde noch nichts in die Datenbank geschrieben."""


class Modus(Enum):
    FRAGEN = "fragen"  # Konsole fragt bei jedem Unterschied
    IMPORT = "import"  # -f: Import überschreibt lokal automatisch
    LOKAL = "lokal"  # -c: lokaler Eintrag bleibt, Import wird verworfen


@dataclass
class Konflikt:
    lokal: Einrichtung
    importiert: Einrichtung
    felder: list[str]


@dataclass
class Plan:
    neu: list[Einrichtung] = field(default_factory=list)
    ueberschreiben: list[Konflikt] = field(default_factory=list)
    unveraendert: int = 0
    lokal_behalten: int = 0


# Entscheidung für einen Konflikt (Konflikt, laufende Nummer, Gesamtzahl).
# True übernimmt den Import, False behält den lokalen Eintrag.
Entscheider = Callable[[Konflikt, int, int], bool]


def unterschiede(lokal: Einrichtung, importiert: Einrichtung) -> list[str]:
    felder = []
    for feld in ABGLEICHSFELDER:
        neu = getattr(importiert, feld)
        if neu is None or neu == "":
            continue
        if getattr(lokal, feld) != neu:
            felder.append(feld)
    return felder


def abgleichen(
    importiert: dict[Schluessel, Einrichtung],
    lokal: dict[Schluessel, Einrichtung],
    modus: Modus,
    entscheiden: Entscheider | None = None,
) -> Plan:
    plan = Plan()
    konflikte: list[Konflikt] = []
    for schluessel, einrichtung in importiert.items():
        vorhanden = lokal.get(schluessel)
        if vorhanden is None:
            plan.neu.append(einrichtung)
            continue
        felder = unterschiede(vorhanden, einrichtung)
        if felder:
            konflikte.append(Konflikt(vorhanden, einrichtung, felder))
        else:
            plan.unveraendert += 1

    plan.neu.sort(key=lambda e: (e.name.casefold(), e.plz, e.typ))
    konflikte.sort(key=lambda k: (k.lokal.name.casefold(), k.lokal.plz, k.lokal.typ))

    for nummer, konflikt in enumerate(konflikte, start=1):
        if modus is Modus.IMPORT:
            uebernehmen = True
        elif modus is Modus.LOKAL:
            uebernehmen = False
        else:
            if entscheiden is None:
                raise ValueError("Im Modus FRAGEN wird ein Entscheider gebraucht")
            uebernehmen = entscheiden(konflikt, nummer, len(konflikte))
        if uebernehmen:
            plan.ueberschreiben.append(konflikt)
        else:
            plan.lokal_behalten += 1
    return plan
