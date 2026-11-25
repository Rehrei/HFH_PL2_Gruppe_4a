"""Zugangsdaten der Datenbank.

Gelesen wird aus Umgebungsvariablen und aus einer .env-Datei (Schlüssel wie im
Mailversand der Datenbank: DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASS).
Umgebungsvariablen haben Vorrang. Die Datei liegt neben run.py, ein anderer Ort
lässt sich mit PFLEGE_ENV angeben. Zugangsdaten stehen nie im Code.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from pflegekatalog.pfade import ENV_DATEI


class KonfigurationsFehler(Exception):
    pass


@dataclass(frozen=True)
class DbConfig:
    host: str
    port: int
    name: str
    user: str
    passwort: str = ""

    def __repr__(self) -> str:  # Passwort nie in Logs oder Tracebacks
        return f"DbConfig(host={self.host!r}, port={self.port}, name={self.name!r}, user={self.user!r})"


def _env_datei_lesen(pfad: Path) -> dict[str, str]:
    werte: dict[str, str] = {}
    if not pfad.is_file():
        return werte
    for zeile in pfad.read_text(encoding="utf-8-sig").splitlines():
        zeile = zeile.strip()
        if not zeile or zeile.startswith("#") or "=" not in zeile:
            continue
        schluessel, wert = zeile.split("=", 1)
        wert = wert.strip()
        if len(wert) >= 2 and wert[0] == wert[-1] and wert[0] in "\"'":
            wert = wert[1:-1]
        werte[schluessel.strip()] = wert
    return werte


def _rechte_pruefen(pfad: Path) -> None:
    """Warnt unter Linux, wenn andere Benutzer die Datei mit dem Datenbankpasswort lesen können."""
    if os.name != "posix" or not pfad.is_file():
        return
    if pfad.stat().st_mode & 0o077:
        print(
            f"Warnung: {pfad} ist für andere Benutzer zugänglich. Bitte 'chmod 600 {pfad}' ausführen.",
            file=sys.stderr,
        )


def laden(umgebung: dict[str, str] | None = None) -> DbConfig:
    umgebung = os.environ if umgebung is None else umgebung
    datei = Path(umgebung["PFLEGE_ENV"]) if umgebung.get("PFLEGE_ENV") else ENV_DATEI
    if umgebung.get("PFLEGE_ENV") and not datei.is_file():
        raise KonfigurationsFehler(f"PFLEGE_ENV zeigt auf eine fehlende Datei: {datei}")
    _rechte_pruefen(datei)
    werte = {**_env_datei_lesen(datei), **{k: v for k, v in umgebung.items() if k.startswith("DB_")}}

    benutzer = werte.get("DB_USER", "")
    if not benutzer:
        raise KonfigurationsFehler(
            f"DB_USER fehlt. Zugangsdaten in {datei} (siehe .env.example) oder als "
            "Umgebungsvariablen DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASS setzen."
        )
    try:
        port = int(werte.get("DB_PORT") or 3306)
    except ValueError:
        raise KonfigurationsFehler("DB_PORT muss eine Zahl sein.") from None
    return DbConfig(
        host=werte.get("DB_HOST") or "localhost",
        port=port,
        name=werte.get("DB_NAME") or "pflege_db",
        user=benutzer,
        passwort=werte.get("DB_PASS", ""),
    )
