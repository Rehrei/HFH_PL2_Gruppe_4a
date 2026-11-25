"""Liest die AOK-Pflege-Navigator-Exporte und wandelt sie in Einrichtungen um.

Aufgenommen werden nur Stammdaten. Preise und Verträge bleiben draußen.
Ambulante Dateien werden ambulante Dienste. Stationär wird so aufgeteilt:
Vollstationär und Kurzzeitpflege ergeben ein Pflegeheim, Tagespflege einen
eigenen Datensatz. Kommen beide vor, entstehen zwei Einträge. Nachtpflege und
Pflegestützpunkte stehen nicht in der Beispielquelle.
"""

from __future__ import annotations

import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from pflegekatalog.modell import Einrichtung
from pflegekatalog.pfade import DATEN_ROOT
from pflegekatalog.plz import PlzIndex, sauber

ADRESSFELDER = ("name", "strasse_hnr", "plz", "ort", "telefon", "email", "web")


@dataclass
class Bericht:
    dateien: int = 0
    dubletten: int = 0
    ohne_name: int = 0
    zu_lang: list[str] = field(default_factory=list)
    bundesland_abweichung: int = 0
    sekunden: float = 0


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


def _koordinate(wert: float | None) -> Decimal | None:
    if wert is None:
        return None
    return Decimal(f"{wert:.6f}")


def lese_dateneingang() -> tuple[dict[tuple[str, str, str, str], Einrichtung], Bericht]:
    """Liest alle XML-Dateien. Doppelte Einträge (gleicher Schlüssel) ersetzen einander."""
    start = time.perf_counter()
    if not DATEN_ROOT.is_dir():
        raise FileNotFoundError(f"Dateneingang fehlt: {DATEN_ROOT}")
    bericht = Bericht()
    index = PlzIndex.laden()
    einrichtungen: dict[tuple[str, str, str, str], Einrichtung] = {}

    for verzeichnis, art_fest in (("ambulant", "ambulant"), ("stationaer", None)):
        ordner = DATEN_ROOT / verzeichnis
        if not ordner.is_dir():
            continue
        for pfad in sorted(ordner.glob("*.xml")):
            bericht.dateien += 1
            neu_in_datei = dubletten_in_datei = 0
            for roh in einrichtungen_lesen(pfad):
                name = roh.get("name", "")
                if not name:
                    bericht.ohne_name += 1
                    continue
                plz = "".join(zeichen for zeichen in roh.get("plz", "") if zeichen.isdigit())[:5]
                ort = roh.get("ort", "")
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
                strasse, hausnummer = teile_anschrift(roh.get("strasse_hnr", ""))
                typen = [art_fest] if art_fest else typen_aus_pflegearten(roh["pflegearten"])
                for typ in typen:
                    einrichtung = Einrichtung(
                        typ=typ,
                        name=name,
                        strasse=strasse,
                        hausnummer=hausnummer,
                        plz=plz,
                        ort=ort or gemeinde,
                        gemeinde_stadt=gemeinde,
                        landkreis=landkreis,
                        bundesland=bundesland,
                        webseite=roh.get("web", ""),
                        telefon=roh.get("telefon", ""),
                        email=roh.get("email", ""),
                        breitengrad=_koordinate(breite),
                        laengengrad=_koordinate(laenge),
                    )
                    zu_lang = einrichtung.zu_lange_felder()
                    if zu_lang:
                        bericht.zu_lang.append(
                            f"{name[:70]} ({plz}): {', '.join(zu_lang)} zu lang für die Datenbank"
                        )
                        continue
                    schluessel = einrichtung.schluessel()
                    if schluessel in einrichtungen:
                        dubletten_in_datei += 1
                    else:
                        neu_in_datei += 1
                    einrichtungen[schluessel] = einrichtung
            bericht.dubletten += dubletten_in_datei
            print(
                f"{verzeichnis}/{pfad.name}: {neu_in_datei} neu, "
                f"{dubletten_in_datei} Dubletten ersetzt"
            )

    bericht.sekunden = time.perf_counter() - start
    return einrichtungen, bericht
