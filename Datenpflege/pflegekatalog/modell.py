"""Datensatz einer Pflegeeinrichtung, wie ihn Import und Datenbank gemeinsam nutzen."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from pflegekatalog.plz import schluessel

# Spaltenlängen der Tabellen 22_pflegeeinrichtung und 21_ansprechpartner.
MAX_LAENGE = {
    "name": 150,
    "strasse": 150,
    "hausnummer": 20,
    "plz": 10,
    "ort": 100,
    "gemeinde_stadt": 100,
    "landkreis": 100,
    "bundesland": 100,
    "webseite": 2048,
    "telefon": 45,
    "email": 254,
}

# Felder, die beim Abgleich mit der Datenbank verglichen und ggf. überschrieben werden.
# Name, PLZ, Typ gehören zum Schlüssel und sind deshalb nicht dabei.
ABGLEICHSFELDER = (
    "strasse",
    "hausnummer",
    "ort",
    "gemeinde_stadt",
    "landkreis",
    "bundesland",
    "webseite",
    "telefon",
    "email",
    "breitengrad",
    "laengengrad",
)

FELDNAMEN = {
    "strasse": "Straße",
    "hausnummer": "Hausnummer",
    "ort": "Ort",
    "gemeinde_stadt": "Gemeinde/Stadt",
    "landkreis": "Landkreis",
    "bundesland": "Bundesland",
    "webseite": "Internetseite",
    "telefon": "Telefon",
    "email": "E-Mail",
    "breitengrad": "Breitengrad",
    "laengengrad": "Längengrad",
}


@dataclass
class Einrichtung:
    typ: str
    name: str
    strasse: str = ""
    hausnummer: str = ""
    plz: str = ""
    ort: str = ""
    gemeinde_stadt: str = ""
    landkreis: str = ""
    bundesland: str = ""
    webseite: str = ""
    telefon: str = ""
    email: str = ""
    breitengrad: Decimal | None = None
    laengengrad: Decimal | None = None
    # Nur bei Datensätzen aus der Datenbank gesetzt:
    id: int | None = None
    kontakt_id: int | None = None

    def schluessel(self) -> tuple[str, str, str, str]:
        """Identität einer Einrichtung: Typ, PLZ, Name und Anschrift."""
        anschrift = f"{self.strasse} {self.hausnummer}"
        return (self.typ, self.plz, schluessel(self.name), schluessel(anschrift))

    def zu_lange_felder(self) -> list[str]:
        return [
            feld for feld, grenze in MAX_LAENGE.items() if len(getattr(self, feld)) > grenze
        ]
