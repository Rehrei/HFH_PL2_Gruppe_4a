from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLZ_PATH = ROOT / "referenz" / "geonames" / "DE.txt"
DATEN_ROOT = ROOT / "Dateneingang" / "Pflegenavigator" / "data"
AUSGABE_ORDNER = ROOT / "Export"
AUSGABE_DATEI = AUSGABE_ORDNER / "pflegeeinrichtungen.csv"
