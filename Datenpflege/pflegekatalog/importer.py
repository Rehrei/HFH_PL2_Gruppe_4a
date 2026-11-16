"""Liest die Pflege-Navigator-Exporte in die Datenbank.

Aufgenommen werden nur Stammdaten. Preise und Verträge bleiben draußen.
Ambulante Dateien werden ambulante Dienste. Stationär wird so aufgeteilt:
Vollstationär und Kurzzeitpflege ergeben ein Pflegeheim, Tagespflege einen
eigenen Datensatz. Kommen beide vor, entstehen zwei Zeilen. Nachtpflege und
Pflegestützpunkte stehen nicht im Export und werden nur von Hand angelegt.
"""

from __future__ import annotations

import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

from pflegekatalog.db import (
    Hierarchie,
    bekannte_schluessel,
    datenbank_anlegen,
    einrichtung_schreiben,
    verbinden,
)
from pflegekatalog.pfade import EXPORT_ROOT
from pflegekatalog.plz import PlzIndex, sauber, schluessel

ADRESSFELDER = ("name", "strasse_hnr", "plz", "ort", "telefon", "email", "web")


@dataclass
class ImportBericht:
    dateien: int = 0
    neu: int = 0
    aktualisiert: int = 0
    ohne_name: int = 0
    bundesland_abweichung: int = 0
    sekunden: float = 0
    je_datei: list[str] = field(default_factory=list)


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


def importieren(bericht: ImportBericht | None = None) -> ImportBericht:
    start = time.perf_counter()
    bericht = bericht or ImportBericht()
    index = PlzIndex.laden()
    conn = verbinden()
    try:
        datenbank_anlegen(conn)
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        hierarchie = Hierarchie(conn)
        bekannt = bekannte_schluessel(conn)
        for verzeichnis, art_fest in (("ambulant", "ambulant"), ("stationaer", None)):
            ordner = EXPORT_ROOT / verzeichnis
            for pfad in sorted(ordner.glob("*.xml")):
                bericht.dateien += 1
                neu = aktualisiert = 0
                with conn:
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
                            landkreis = gemeinde = None
                            breite = laenge = None
                            herkunft = None
                        else:
                            landkreis = zuordnung.landkreis
                            gemeinde = zuordnung.gemeinde
                            breite = zuordnung.breitengrad
                            laenge = zuordnung.laengengrad
                            herkunft = "plz" if breite is not None and laenge is not None else None
                        orte = hierarchie.sicherstellen(bundesland, landkreis, ort or gemeinde, gemeinde)
                        typen = [art_fest] if art_fest else typen_aus_pflegearten(roh["pflegearten"])
                        for typ in typen:
                            ident = (typ, plz, schluessel(name), schluessel(strasse))
                            if ident in bekannt:
                                aktualisiert += 1
                            else:
                                neu += 1
                                bekannt.add(ident)
                            einrichtung_schreiben(
                                conn,
                                typ=typ,
                                name=name,
                                strasse=strasse,
                                plz=plz,
                                orte=orte,
                                telefon=roh.get("telefon", ""),
                                email=roh.get("email", ""),
                                web=roh.get("web", ""),
                                breitengrad=breite,
                                laengengrad=laenge,
                                koordinaten_herkunft=herkunft,
                                quelle=f"{verzeichnis}/{pfad.name}",
                            )
                bericht.neu += neu
                bericht.aktualisiert += aktualisiert
                zeile = f"{verzeichnis}/{pfad.name}: {neu} neu, {aktualisiert} aktualisiert"
                bericht.je_datei.append(zeile)
                print(zeile)
        bericht.sekunden = time.perf_counter() - start
        return bericht
    finally:
        conn.close()


def main() -> None:
    bericht = importieren()
    print(
        f"Fertig: {bericht.neu} neu, {bericht.aktualisiert} aktualisiert, "
        f"{bericht.ohne_name} ohne Namen, {bericht.dateien} Dateien, "
        f"{bericht.sekunden:.1f} s, Bundesland wich ab: {bericht.bundesland_abweichung}"
    )


if __name__ == "__main__":
    main()
