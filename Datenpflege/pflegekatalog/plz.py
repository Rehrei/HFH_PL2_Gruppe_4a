"""Ordnet eine Postleitzahl Landkreis, Gemeinde und einem ungefähren Punkt zu.

Quelle ist das GeoNames-PLZ-Verzeichnis (CC BY 4.0). Eine PLZ kann mehrere
Orte haben. Die Gemeinde wird nur gesetzt, wenn der Ortsname dazu passt.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from pflegekatalog.konstanten import LAND_AUS_CODE
from pflegekatalog.pfade import PLZ_PATH

_KREIS_PREFIXE = (
    "Kreisfreie Stadt ",
    "Stadtkreis ",
    "Landkreis ",
    "Kreis ",
)
_KREIS_ALIAS = {
    "Nuremberg": "Nürnberg",
}


def norm(value: str | None) -> str:
    text = (value or "").casefold().strip()
    text = text.replace("ß", "ss")
    text = (
        text.replace("ä", "ae")
        .replace("ö", "oe")
        .replace("ü", "ue")
    )
    text = re.sub(r"[^a-z0-9]+", " ", text)
    text = " ".join(text.split())
    text = re.sub(r"\bst\b", "sankt", text)
    text = re.sub(r"\bhann\b", "hannoversch", text)
    return text


def schluessel(value: str | None) -> str:
    """Vergleichswert für den Import-Schlüssel (Name, Straße)."""
    text = (value or "").casefold().strip()
    text = text.replace("ß", "ss")
    return " ".join(text.split())


def sauber(value: str | None) -> str:
    text = (value or "").replace("\xa0", " ").strip()
    return re.sub(r"\s+", " ", text)


def name_oder_nichts(value: str | None) -> str | None:
    text = sauber(value)
    return text or None


def _kreis_name(raw: str) -> str:
    text = _KREIS_ALIAS.get(raw.strip(), raw.strip())
    for prefix in _KREIS_PREFIXE:
        if text.startswith(prefix):
            text = text[len(prefix) :]
            break
    for suffix in (", Freie und Hansestadt", ", Stadt"):
        if text.endswith(suffix):
            text = text[: -len(suffix)]
    return text.strip()


def _passt(gesucht: str, vorhanden: str) -> bool:
    if not gesucht or not vorhanden:
        return False
    if gesucht == vorhanden:
        return True
    if len(gesucht) >= 4 and vorhanden.startswith(gesucht + " "):
        return True
    if len(vorhanden) >= 4 and gesucht.startswith(vorhanden + " "):
        return True
    if _woerter_darin(gesucht, vorhanden) or _woerter_darin(vorhanden, gesucht):
        return True
    if len(gesucht) >= 5 and _ohne_doppelbuchstaben(gesucht) == _ohne_doppelbuchstaben(vorhanden):
        return True
    return False


def _woerter_darin(kurz: str, lang: str) -> bool:
    teile = kurz.split()
    if len(teile) < 2:
        return False
    rest = lang
    for teil in teile:
        stelle = rest.find(teil)
        if stelle < 0 or (stelle > 0 and rest[stelle - 1] != " "):
            return False
        ende = stelle + len(teil)
        if ende < len(rest) and rest[ende] != " ":
            return False
        rest = rest[ende:]
    return True


def _ohne_doppelbuchstaben(text: str) -> str:
    return re.sub(r"(.)\1", r"\1", text)


def _auf_kern_reduzieren(treffer: list[PlzOrt]) -> list[PlzOrt]:
    """Ortsteile wie 'Nienburg (Weser) Holtorf' auf die kürzere Gemeinde ziehen."""
    kern = min(treffer, key=lambda zeile: (len(zeile.ort_norm), zeile.ort_norm))
    if all(
        zeile.ort_norm == kern.ort_norm or zeile.ort_norm.startswith(kern.ort_norm + " ")
        for zeile in treffer
    ):
        return [zeile for zeile in treffer if zeile.ort_norm == kern.ort_norm]
    return treffer


@dataclass(frozen=True)
class PlzOrt:
    plz: str
    ort: str
    ort_norm: str
    bundesland: str | None
    landkreis: str
    breitengrad: float | None
    laengengrad: float | None


@dataclass(frozen=True)
class Zuordnung:
    bundesland: str | None
    landkreis: str | None
    gemeinde: str | None
    breitengrad: float | None
    laengengrad: float | None

    def als_dict(self) -> dict:
        return {
            "bundesland": self.bundesland,
            "landkreis": self.landkreis,
            "gemeinde": self.gemeinde,
            "breitengrad": self.breitengrad,
            "laengengrad": self.laengengrad,
        }


def _eine_koordinate(orte: list[PlzOrt]) -> tuple[float | None, float | None]:
    punkte = {
        (round(ort.breitengrad, 3), round(ort.laengengrad, 3))
        for ort in orte
        if ort.breitengrad is not None and ort.laengengrad is not None
    }
    if len(punkte) != 1:
        return None, None
    for ort in orte:
        if ort.breitengrad is not None and ort.laengengrad is not None:
            return ort.breitengrad, ort.laengengrad
    return None, None


class PlzIndex:
    def __init__(self, nach_plz: dict[str, list[PlzOrt]]):
        self.nach_plz = nach_plz

    @classmethod
    def laden(cls, pfad=PLZ_PATH) -> "PlzIndex":
        nach_plz: dict[str, list[PlzOrt]] = {}
        with open(pfad, encoding="utf-8") as datei:
            for zeile in datei:
                teile = zeile.rstrip("\n").split("\t")
                if len(teile) < 11 or not teile[1] or not teile[2]:
                    continue
                try:
                    breite = float(teile[9]) if teile[9] else None
                    laenge = float(teile[10]) if teile[10] else None
                except ValueError:
                    breite = laenge = None
                ort = PlzOrt(
                    plz=teile[1],
                    ort=teile[2].strip(),
                    ort_norm=norm(teile[2]),
                    bundesland=LAND_AUS_CODE.get(teile[4]),
                    landkreis=_kreis_name(teile[7]) if teile[7] else "",
                    breitengrad=breite,
                    laengengrad=laenge,
                )
                nach_plz.setdefault(ort.plz, []).append(ort)
        return cls(nach_plz)

    def resolve(self, plz: str, ort: str | None) -> Zuordnung:
        zeilen = self.nach_plz.get(sauber(plz), [])
        if not zeilen:
            return Zuordnung(None, None, None, None, None)

        laender = {zeile.bundesland for zeile in zeilen if zeile.bundesland}
        bundesland = next(iter(laender)) if len(laender) == 1 else None
        kreise = {zeile.landkreis for zeile in zeilen if zeile.landkreis}
        landkreis = next(iter(kreise)) if len(kreise) == 1 else None

        gesucht = norm(ort)
        genau = [zeile for zeile in zeilen if gesucht and zeile.ort_norm == gesucht]
        treffer = genau or [
            zeile for zeile in zeilen if gesucht and _passt(gesucht, zeile.ort_norm)
        ]
        if len({zeile.ort_norm for zeile in treffer}) > 1:
            treffer = _auf_kern_reduzieren(treffer)

        gemeinde = None
        breite = laenge = None
        if treffer:
            namen = {zeile.ort for zeile in treffer}
            if len(namen) == 1:
                gemeinde = treffer[0].ort
            kreise_treffer = {zeile.landkreis for zeile in treffer if zeile.landkreis}
            if len(kreise_treffer) == 1:
                landkreis = next(iter(kreise_treffer))
            breite, laenge = _eine_koordinate(treffer)
        elif len({zeile.ort for zeile in zeilen}) == 1:
            gemeinde = zeilen[0].ort
            breite, laenge = _eine_koordinate(zeilen)

        if breite is None and gemeinde is not None:
            for zeile in zeilen:
                if zeile.ort == gemeinde and zeile.breitengrad is not None:
                    breite, laenge = zeile.breitengrad, zeile.laengengrad
                    break
        if breite is None:
            breite, laenge = _eine_koordinate(zeilen)

        return Zuordnung(bundesland, landkreis, gemeinde, breite, laenge)


def _pruefen() -> None:
    index = PlzIndex.laden()
    faelle = (
        ("27568", "Bremerhaven", "Bremerhaven", "Bremerhaven", True),
        ("28325", "Bremen", "Bremen", "Bremen", True),
        ("80331", "München", "München", "München", True),
        ("50667", "Köln", "Köln", "Köln", True),
        ("01945", "Ruhland", "Ruhland", "Oberspreewald-Lausitz", True),
        ("01945", "Irgendwo", None, "Oberspreewald-Lausitz", False),
        ("00000", "Nirgendwo", None, None, False),
        ("77933", "Lahr", "Lahr/Schwarzwald", "Ortenaukreis", True),
        ("66386", "St. Ingbert", "Sankt Ingbert", "Saarpfalz-Kreis", True),
        ("34346", "Hann. Münden", "Hannoversch Münden", "Göttingen", True),
        ("31582", "Nienburg", "Nienburg (Weser)", "Nienburg/Weser", True),
        ("26789", "Leer", "Leer (Ostfriesland)", "Leer", True),
        ("89584", "Ehingen (Donau)", "Ehingen an der Donau", "Alb-Donau-Kreis", True),
        ("40789", "Monheim", "Monheim am Rhein", "Mettmann", True),
        ("08280", "Aue-Bad Schlema", "Aue", "Erzgebirgskreis", True),
        ("82152", "Krailing", "Krailling", "Starnberg", True),
        ("14476", "Potsdam", None, None, False),
    )
    for plz, ort, gemeinde, kreis, koordinaten in faelle:
        hit = index.resolve(plz, ort)
        assert hit.gemeinde == gemeinde, (plz, ort, hit)
        assert hit.landkreis == kreis, (plz, ort, hit)
        assert (hit.breitengrad is not None) is koordinaten, (plz, ort, hit)
        if hit.landkreis:
            assert "Nuremberg" not in hit.landkreis
    nuernberg = index.resolve("90402", "Nürnberg")
    assert nuernberg.gemeinde == "Nürnberg", nuernberg
    assert nuernberg.landkreis == "Nürnberg", nuernberg
    print("PLZ-Zuordnung in Ordnung")


if __name__ == "__main__":
    _pruefen()
