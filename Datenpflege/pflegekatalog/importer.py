"""Wandelt die AOK-Pflege-Navigator-Exporte in eine CSV-Datei um.

Aufgenommen werden nur Stammdaten. Preise und Verträge bleiben draußen.
Ambulante Dateien werden ambulante Dienste. Stationär wird so aufgeteilt:
Vollstationär und Kurzzeitpflege ergeben ein Pflegeheim, Tagespflege einen
eigenen Datensatz. Kommen beide vor, entstehen zwei Zeilen. Nachtpflege und
Pflegestützpunkte stehen nicht in der Beispielquelle.
"""

from __future__ import annotations

import csv
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from pflegekatalog.konstanten import TYP_NAMEN
from pflegekatalog.pfade import AUSGABE_DATEI, DATEN_ROOT
from pflegekatalog.plz import PlzIndex, sauber, schluessel

ADRESSFELDER = ("name", "strasse_hnr", "plz", "ort", "telefon", "email", "web")
SPALTEN = (
    "Art",
    "Name",
    "Straße",
    "Hausnummer",
    "PLZ",
    "Stadt",
    "Bundesland",
    "Landkreis",
    "Gemeinde",
    "Telefon",
    "E-Mail",
    "Internetseite",
    "Breitengrad",
    "Laengengrad",
    "Quelle",
)


@dataclass
class Bericht:
    dateien: int = 0
    neu: int = 0
    aktualisiert: int = 0
    ohne_name: int = 0
    bundesland_abweichung: int = 0
    sekunden: float = 0
    ausgabe: Path = AUSGABE_DATEI


def typen_aus_pflegearten(arten: set[str]) -> list[str]:
    klein = [art.casefold() for art in arten]
    heim = any("vollstation" in art or "kurzzeit" in art for art in klein)
    tag = any("tagespflege" in art for art in klein)
    nacht = any("nachtpflege" in art for art in klein)
    typen: list[str] = []
    if heim or (not tag and not nacht):
        typen.append("pflegeheim")
    if tag:
        typen.append("tagespflege")
    if nacht:
        typen.append("nachtpflege")
    return typen


def einrichtungen_lesen(pfad: Path):
    stack: list[str] = []
    aktuell: dict | None = None
    for event, elem in ET.iterparse(pfad, events=("start", "end")):
        tag = elem.tag.rsplit("}", 1)[-1]
        if event == "start":
            if tag == "einrichtung":
                aktuell = {"pflegearten": set()}
            stack.append(tag)
            continue
        eltern = stack[-2] if len(stack) >= 2 else ""
        if aktuell is not None:
            if eltern == "einrichtung" and tag in ADRESSFELDER:
                aktuell[tag] = sauber(elem.text)
            elif tag == "pflegeart" and elem.text:
                aktuell["pflegearten"].add(sauber(elem.text))
        if tag == "einrichtung" and aktuell is not None:
            yield aktuell
            aktuell = None
            elem.clear()
        elif tag in ("vertrag", "gpos", "preis"):
            elem.clear()
        stack.pop()


_STRASSENENDE = re.compile(
    r"(straße|strasse|str\.|weg|platz|gasse|allee|ring|damm|chaussee|ufer|pfad|stieg|graben|markt|zeile|anger|deich|wall|brücke|bruecke|twiete|gang|steig)$",
    re.IGNORECASE,
)


def teile_anschrift(roh: str) -> tuple[str, str]:
    """Trennt den Straßenamen von der Hausnummer. Ortsnamen bleiben nicht in der Straßenspalte."""
    text = sauber(roh)
    text = re.sub(r"\s+\.", ".", text)
    text = re.sub(r"\.(?=\d)", ". ", text)
    stelle = re.search(r"\d", text)
    if stelle is None:
        if _STRASSENENDE.search(text):
            return text, ""
        return "", ""
    strasse = text[: stelle.start()].strip(" ,")
    nummer = text[stelle.start() :].strip()
    if not strasse:
        return "", nummer
    return strasse, nummer


def _koordinate(wert: float | None) -> str:
    if wert is None:
        return ""
    return f"{wert:.6f}".rstrip("0").rstrip(".")


def umwandeln(ausgabe: Path | None = None) -> Bericht:
    start = time.perf_counter()
    if not DATEN_ROOT.is_dir():
        raise FileNotFoundError(f"Dateneingang fehlt: {DATEN_ROOT}")
    ziel = ausgabe or AUSGABE_DATEI
    bericht = Bericht(ausgabe=ziel)
    index = PlzIndex.laden()
    datensaetze: dict[tuple[str, str, str, str], dict[str, str]] = {}

    for verzeichnis, art_fest in (("ambulant", "ambulant"), ("stationaer", None)):
        ordner = DATEN_ROOT / verzeichnis
        if not ordner.is_dir():
            continue
        for pfad in sorted(ordner.glob("*.xml")):
            bericht.dateien += 1
            neu_in_datei = aktualisiert_in_datei = 0
            for roh in einrichtungen_lesen(pfad):
                name = roh.get("name", "")
                if not name:
                    bericht.ohne_name += 1
                    continue
                plz = "".join(zeichen for zeichen in roh.get("plz", "") if zeichen.isdigit())[:5]
                ort = roh.get("ort", "")
                strasse = roh.get("strasse_hnr", "")
                zuordnung = index.resolve(plz, ort)
                bundesland = pfad.stem
                if zuordnung.bundesland and zuordnung.bundesland != bundesland:
                    bericht.bundesland_abweichung += 1
                    landkreis = gemeinde = ""
                    breite = laenge = None
                else:
                    landkreis = zuordnung.landkreis or ""
                    gemeinde = zuordnung.gemeinde or ""
                    breite = zuordnung.breitengrad
                    laenge = zuordnung.laengengrad
                stadt = ort or gemeinde
                strassenname, hausnummer = teile_anschrift(strasse)
                typen = [art_fest] if art_fest else typen_aus_pflegearten(roh["pflegearten"])
                for typ in typen:
                    ident = (typ, plz, schluessel(name), schluessel(strasse))
                    if ident in datensaetze:
                        aktualisiert_in_datei += 1
                    else:
                        neu_in_datei += 1
                    datensaetze[ident] = {
                        "Art": TYP_NAMEN[typ],
                        "Name": name,
                        "Straße": strassenname,
                        "Hausnummer": hausnummer,
                        "PLZ": plz,
                        "Stadt": stadt,
                        "Bundesland": bundesland,
                        "Landkreis": landkreis,
                        "Gemeinde": gemeinde,
                        "Telefon": roh.get("telefon", ""),
                        "E-Mail": roh.get("email", ""),
                        "Internetseite": roh.get("web", ""),
                        "Breitengrad": _koordinate(breite),
                        "Laengengrad": _koordinate(laenge),
                        "Quelle": f"{verzeichnis}/{pfad.name}",
                    }
            bericht.aktualisiert += aktualisiert_in_datei
            print(
                f"{verzeichnis}/{pfad.name}: {neu_in_datei} neu, {aktualisiert_in_datei} aktualisiert"
            )

    ziel.parent.mkdir(parents=True, exist_ok=True)
    with ziel.open("w", encoding="utf-8-sig", newline="") as datei:
        writer = csv.DictWriter(datei, fieldnames=SPALTEN, delimiter=";", lineterminator="\n")
        writer.writeheader()
        for datensatz in sorted(
            datensaetze.values(),
            key=lambda zeile: (zeile["Name"].casefold(), zeile["PLZ"], zeile["Art"]),
        ):
            writer.writerow(datensatz)
    bericht.sekunden = time.perf_counter() - start
    bericht.ausgabe = ziel
    bericht.neu = len(datensaetze)
    return bericht
