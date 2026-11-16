from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "pflege.db"
PLZ_PATH = ROOT / "referenz" / "geonames" / "DE.txt"
EXPORT_ROOT = ROOT / "Dateneingang" / "Pflegenavigator" / "data"
