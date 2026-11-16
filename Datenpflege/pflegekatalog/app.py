from __future__ import annotations

import sqlite3
import threading

from flask import Flask, flash, g, jsonify, redirect, render_template, request, url_for

from pflegekatalog.db import AUSGABE, Hierarchie, datenbank_anlegen, verbinden
from pflegekatalog.importer import importieren
from pflegekatalog.konstanten import BUNDESLAENDER, TYPEN, TYP_NAMEN
from pflegekatalog.plz import PlzIndex, Zuordnung, sauber, schluessel

PRO_SEITE = 25
_import_sperre = threading.Lock()
_plz_index: PlzIndex | None = None


def create_app() -> Flask:
    app = Flask(__name__)
    app.secret_key = "pflegekatalog-lokal"

    @app.template_filter("de")
    def de_filter(wert: int) -> str:
        return f"{wert:,}".replace(",", ".")

    @app.context_processor
    def umgebung():
        return {"typen": TYPEN, "typ_name": TYP_NAMEN, "bundeslaender": BUNDESLAENDER}

    @app.before_request
    def vor_dem_request():
        if request.endpoint != "static":
            g.db = verbinden()

    @app.teardown_appcontext
    def verbindung_schliessen(_fehler):
        db = g.pop("db", None)
        if db is not None:
            db.close()

    @app.get("/")
    def liste():
        datenbank_anlegen(g.db)
        suche = sauber(request.args.get("q", ""))
        typ = request.args.get("typ", "")
        bundesland = request.args.get("bundesland", "")
        plz = sauber(request.args.get("plz", ""))
        try:
            seite = max(1, int(request.args.get("seite", "1")))
        except ValueError:
            seite = 1

        where: list[str] = []
        parameter: list[object] = []
        if suche:
            muster = "%" + suche.replace("%", "").replace("_", "") + "%"
            where.append(
                """(
                    e.name LIKE ? OR e.strasse LIKE ? OR e.telefon LIKE ?
                    OR e.email LIKE ? OR e.ansprechpartner LIKE ?
                    OR s.name LIKE ? OR g.name LIKE ? OR k.name LIKE ?
                )"""
            )
            parameter.extend([muster] * 8)
        if typ in TYP_NAMEN:
            where.append("e.typ = ?")
            parameter.append(typ)
        if bundesland in BUNDESLAENDER:
            where.append("b.name = ?")
            parameter.append(bundesland)
        if plz:
            ziffern = "".join(zeichen for zeichen in plz if zeichen.isdigit())
            if ziffern:
                where.append("e.plz LIKE ?")
                parameter.append(ziffern + "%")

        bedingung = ("WHERE " + " AND ".join(where)) if where else ""
        gesamt = g.db.execute(
            f"SELECT COUNT(*) AS n FROM einrichtung e "
            f"LEFT JOIN bundesland b ON b.id = e.bundesland_id "
            f"LEFT JOIN landkreis k ON k.id = e.landkreis_id "
            f"LEFT JOIN stadt s ON s.id = e.stadt_id "
            f"LEFT JOIN gemeinde g ON g.id = e.gemeinde_id {bedingung}",
            parameter,
        ).fetchone()["n"]
        seiten = max(1, (gesamt + PRO_SEITE - 1) // PRO_SEITE)
        seite = min(seite, seiten)
        zeilen = g.db.execute(
            AUSGABE + f" {bedingung} ORDER BY e.name, e.plz LIMIT ? OFFSET ?",
            [*parameter, PRO_SEITE, (seite - 1) * PRO_SEITE],
        ).fetchall()
        zaehlung = {
            zeile["typ"]: zeile["n"]
            for zeile in g.db.execute("SELECT typ, COUNT(*) AS n FROM einrichtung GROUP BY typ")
        }
        return render_template(
            "liste.html",
            zeilen=zeilen,
            suche=suche,
            typ=typ,
            bundesland=bundesland,
            plz=plz,
            seite=seite,
            seiten=seiten,
            gesamt=gesamt,
            zaehlung=zaehlung,
            bestand=sum(zaehlung.values()),
        )

    @app.route("/einrichtungen/neu", methods=["GET", "POST"])
    def neu():
        datenbank_anlegen(g.db)
        werte = leeres_formular()
        if request.method == "POST":
            werte = formular_lesen()
            fehler = pruefen(werte)
            if not fehler:
                try:
                    neue_id = speichern(None, werte)
                except sqlite3.IntegrityError:
                    g.db.rollback()
                    fehler = ["Diese Art, dieser Name, diese Straße und diese PLZ sind schon vergeben."]
                except ValueError as fehler_text:
                    g.db.rollback()
                    fehler = [str(fehler_text)]
                else:
                    flash("Datensatz angelegt.")
                    return redirect(url_for("bearbeiten", einrichtung_id=neue_id))
            for meldung in fehler:
                flash(meldung, "fehler")
        return render_template("formular.html", werte=werte, datensatz_id=None)

    @app.route("/einrichtungen/<int:einrichtung_id>", methods=["GET", "POST"])
    def bearbeiten(einrichtung_id: int):
        datenbank_anlegen(g.db)
        datensatz = laden(einrichtung_id)
        if datensatz is None:
            return "Diesen Datensatz gibt es nicht.", 404
        werte = werte_aus_datensatz(datensatz)
        if request.method == "POST":
            werte = formular_lesen()
            fehler = pruefen(werte)
            if not fehler:
                try:
                    speichern(einrichtung_id, werte, datensatz)
                except sqlite3.IntegrityError:
                    g.db.rollback()
                    fehler = ["Diese Art, dieser Name, diese Straße und diese PLZ sind schon vergeben."]
                except ValueError as fehler_text:
                    g.db.rollback()
                    fehler = [str(fehler_text)]
                else:
                    flash("Gespeichert.")
                    return redirect(url_for("bearbeiten", einrichtung_id=einrichtung_id))
            for meldung in fehler:
                flash(meldung, "fehler")
        return render_template("formular.html", werte=werte, datensatz_id=einrichtung_id)

    @app.post("/einrichtungen/<int:einrichtung_id>/loeschen")
    def loeschen(einrichtung_id: int):
        g.db.execute("DELETE FROM einrichtung WHERE id = ?", (einrichtung_id,))
        g.db.commit()
        flash("Datensatz gelöscht.")
        return redirect(url_for("liste"))

    @app.post("/importieren")
    def import_starten():
        if not _import_sperre.acquire(blocking=False):
            flash("Der Import läuft schon.", "fehler")
            return redirect(url_for("liste"))
        try:
            bericht = importieren()
        except Exception as fehler:
            flash(f"Import fehlgeschlagen: {fehler}", "fehler")
            return redirect(url_for("liste"))
        finally:
            _import_sperre.release()
        flash(
            f"Import fertig: {bericht.neu} neu, {bericht.aktualisiert} aktualisiert, "
            f"{bericht.ohne_name} ohne Namen, {bericht.dateien} Dateien, "
            f"{bericht.sekunden:.0f} Sekunden."
        )
        if bericht.bundesland_abweichung:
            flash(
                f"Bei {bericht.bundesland_abweichung} Datensätzen passte die PLZ nicht "
                "zum Bundesland der Datei. Kreis, Gemeinde und Koordinaten blieben dort leer.",
                "fehler",
            )
        return redirect(url_for("liste"))

    @app.get("/api/plz/<plz>")
    def api_plz(plz: str):
        zuordnung = plz_index().resolve(plz, request.args.get("ort", ""))
        return jsonify(zuordnung.als_dict())

    return app


def plz_index() -> PlzIndex:
    global _plz_index
    if _plz_index is None:
        _plz_index = PlzIndex.laden()
    return _plz_index


def laden(einrichtung_id: int):
    return g.db.execute(AUSGABE + " WHERE e.id = ?", (einrichtung_id,)).fetchone()


def leeres_formular() -> dict:
    return {
        "typ": "pflegestuetzpunkt",
        "name": "",
        "strasse": "",
        "plz": "",
        "stadt": "",
        "bundesland": "",
        "landkreis": "",
        "gemeinde": "",
        "ansprechpartner": "",
        "telefon": "",
        "email": "",
        "web": "",
        "oeffnungszeiten": "",
        "beratungsleistungen": "",
        "zustaendigkeitsbereich": "",
        "breitengrad": "",
        "laengengrad": "",
        "koordinaten_herkunft": "",
        "quelle": "",
        "angelegt_am": "",
        "geaendert_am": "",
    }


def werte_aus_datensatz(zeile) -> dict:
    werte = leeres_formular()
    werte.update(
        {
            "typ": zeile["typ"],
            "name": zeile["name"],
            "strasse": zeile["strasse"],
            "plz": zeile["plz"],
            "stadt": zeile["stadt"] or "",
            "bundesland": zeile["bundesland"] or "",
            "landkreis": zeile["landkreis"] or "",
            "gemeinde": zeile["gemeinde"] or "",
            "ansprechpartner": zeile["ansprechpartner"],
            "telefon": zeile["telefon"],
            "email": zeile["email"],
            "web": zeile["web"],
            "oeffnungszeiten": zeile["oeffnungszeiten"],
            "beratungsleistungen": zeile["beratungsleistungen"],
            "zustaendigkeitsbereich": zeile["zustaendigkeitsbereich"],
            "breitengrad": koordinaten_text(zeile["breitengrad"]),
            "laengengrad": koordinaten_text(zeile["laengengrad"]),
            "koordinaten_herkunft": zeile["koordinaten_herkunft"] or "",
            "quelle": zeile["quelle"],
            "angelegt_am": zeile["angelegt_am"],
            "geaendert_am": zeile["geaendert_am"],
        }
    )
    return werte


def formular_lesen() -> dict:
    werte = leeres_formular()
    for feld in werte:
        if feld in ("koordinaten_herkunft", "quelle", "angelegt_am", "geaendert_am"):
            continue
        werte[feld] = sauber(request.form.get(feld, ""))
    for feld in ("koordinaten_herkunft", "quelle", "angelegt_am", "geaendert_am"):
        werte[feld] = request.form.get(feld, "")
    return werte


def pruefen(werte: dict) -> list[str]:
    fehler = []
    if werte["typ"] not in TYP_NAMEN:
        fehler.append("Die Art der Einrichtung fehlt.")
    if not werte["name"]:
        fehler.append("Der Name fehlt.")
    if werte["plz"] and (len(werte["plz"]) != 5 or not werte["plz"].isdigit()):
        fehler.append("Die Postleitzahl braucht fünf Ziffern.")
    if werte["bundesland"] and werte["bundesland"] not in BUNDESLAENDER:
        fehler.append("Dieses Bundesland gibt es nicht.")
    breite = koordinaten_zahl(werte["breitengrad"])
    laenge = koordinaten_zahl(werte["laengengrad"])
    if (werte["breitengrad"] and breite is None) or (werte["laengengrad"] and laenge is None):
        fehler.append("Die Koordinaten sind keine Zahlen.")
    elif (breite is None) != (laenge is None):
        fehler.append("Breiten- und Längengrad gehören zusammen.")
    elif breite is not None and not (-90 <= breite <= 90 and -180 <= laenge <= 180):
        fehler.append("Die Koordinaten liegen außerhalb des Wertebereichs.")
    return fehler


def koordinaten_zahl(text: str) -> float | None:
    roh = text.strip().replace(",", ".")
    if not roh:
        return None
    try:
        return float(roh)
    except ValueError:
        return None


def koordinaten_text(wert) -> str:
    if wert is None:
        return ""
    return f"{wert:.6f}".rstrip("0").rstrip(".")


def koordinaten_festlegen(werte: dict, bisher) -> tuple[float | None, float | None, str | None]:
    breite = koordinaten_zahl(werte["breitengrad"])
    laenge = koordinaten_zahl(werte["laengengrad"])
    if breite is None and laenge is None:
        if bisher is not None and (
            bisher["breitengrad"] is not None or bisher["koordinaten_herkunft"] == "manuell"
        ):
            return None, None, "manuell"
        return None, None, None
    vorschlag = plz_index().resolve(werte["plz"], werte["stadt"]) if werte["plz"] else Zuordnung(None, None, None, None, None)
    if (
        vorschlag.breitengrad is not None
        and vorschlag.laengengrad is not None
        and abs(breite - vorschlag.breitengrad) < 1e-5
        and abs(laenge - vorschlag.laengengrad) < 1e-5
    ):
        return breite, laenge, "plz"
    return breite, laenge, "manuell"


def speichern(einrichtung_id: int | None, werte: dict, bisher=None) -> int:
    vorschlag = plz_index().resolve(werte["plz"], werte["stadt"]) if werte["plz"] else Zuordnung(None, None, None, None, None)
    bundesland = werte["bundesland"] or vorschlag.bundesland
    landkreis = werte["landkreis"] or vorschlag.landkreis
    gemeinde = werte["gemeinde"] or vorschlag.gemeinde
    stadt = werte["stadt"] or gemeinde
    if not bundesland and (stadt or landkreis or gemeinde):
        raise ValueError("Das Bundesland fehlt und ließ sich aus der PLZ nicht ermitteln.")
    orte = Hierarchie(g.db).sicherstellen(bundesland, landkreis, stadt, gemeinde)
    breite, laenge, herkunft = koordinaten_festlegen(werte, bisher)
    felder = (
        werte["typ"],
        werte["name"],
        schluessel(werte["name"]),
        werte["strasse"],
        schluessel(werte["strasse"]),
        werte["plz"],
        orte.bundesland_id,
        orte.landkreis_id,
        orte.stadt_id,
        orte.gemeinde_id,
        werte["ansprechpartner"],
        werte["telefon"],
        werte["email"],
        werte["web"],
        werte["oeffnungszeiten"],
        werte["beratungsleistungen"],
        werte["zustaendigkeitsbereich"],
        breite,
        laenge,
        herkunft,
    )
    if einrichtung_id is None:
        cursor = g.db.execute(
            """
            INSERT INTO einrichtung (
                typ, name, name_norm, strasse, strasse_norm, plz,
                bundesland_id, landkreis_id, stadt_id, gemeinde_id,
                ansprechpartner, telefon, email, web,
                oeffnungszeiten, beratungsleistungen, zustaendigkeitsbereich,
                breitengrad, laengengrad, koordinaten_herkunft, quelle
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'manuell')
            """,
            felder,
        )
        g.db.commit()
        return cursor.lastrowid
    g.db.execute(
        """
        UPDATE einrichtung SET
            typ = ?, name = ?, name_norm = ?, strasse = ?, strasse_norm = ?, plz = ?,
            bundesland_id = ?, landkreis_id = ?, stadt_id = ?, gemeinde_id = ?,
            ansprechpartner = ?, telefon = ?, email = ?, web = ?,
            oeffnungszeiten = ?, beratungsleistungen = ?, zustaendigkeitsbereich = ?,
            breitengrad = ?, laengengrad = ?, koordinaten_herkunft = ?,
            geaendert_am = datetime('now')
        WHERE id = ?
        """,
        (*felder, einrichtung_id),
    )
    g.db.commit()
    return einrichtung_id
