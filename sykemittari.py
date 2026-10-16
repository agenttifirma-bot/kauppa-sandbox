"""Sykemittari: tarkistaa etta kauppatiimi on elossa ja terve. Hälytys Telegramiin vain jos jokin on pielessa;
sunnuntaisin lahettaa myos "OK"-viestin, jolloin viestin puuttuminen kertoo ettei sykemittari itse ole ajanut.
Vain luku: ei koskaan muuta salkkuja."""
import argparse
import os
import sqlite3
import sys
from datetime import date, datetime, timedelta, timezone

import config
import llm
import notify
import rajat

PV = 86400000


def _ro(polku):
    return sqlite3.connect("file:%s?mode=ro" % polku, uri=True, timeout=10)


def data_viimeisin(polku):
    con = _ro(polku)
    try:
        ts = con.execute("SELECT MAX(ts) FROM hinnat WHERE symbol='BTCUSDT'").fetchone()[0]
    finally:
        con.close()
    return datetime.fromtimestamp(ts / 1000, timezone.utc).date() if ts else None


def salkku_tila(polku):
    """Palauttaa dictin tai None jos tiedostoa ei ole."""
    if not os.path.exists(polku):
        return None
    con = _ro(polku)
    try:
        tila = dict(con.execute("SELECT avain, arvo FROM tila").fetchall())
        viim = con.execute("SELECT paiva, hylatty FROM paatokset ORDER BY paiva DESC LIMIT 3").fetchall()
        arvo = con.execute("SELECT arvo FROM arvot ORDER BY paiva DESC LIMIT 1").fetchone()
    finally:
        con.close()
    return {"viimeisin_paiva": tila.get("viimeisin_paiva"), "jarru": tila.get("jarru") == "1",
            "hylatyt_viimeiset": [h for _, h in viim], "arvo": arvo[0] if arvo else None}


def tarkista(data_polku, salkut, tanaan, pysaytys_polku=None):
    """Palauttaa ongelmalista (tyhja = kaikki hyvin) ja infolista."""
    ongelmat, info = [], []
    try:
        viim = data_viimeisin(data_polku)
    except sqlite3.Error as e:
        return ["markkinadataa ei voi lukea (%s)" % type(e).__name__], info
    if viim is None:
        return ["markkinadata tyhja"], info
    ika = (tanaan - viim).days
    if ika > config.VANHENTUNUT_PV:
        ongelmat.append("markkinadata vanhentunut: viimeisin %s (%d pv)" % (viim, ika))
    for nimi, polku in sorted(salkut.items()):
        try:
            t = salkku_tila(polku)
        except sqlite3.Error as e:
            ongelmat.append("salkku %s: kantaa ei voi lukea (%s)" % (nimi, type(e).__name__))
            continue
        if t is None:
            ongelmat.append("salkku %s: tiedostoa ei ole (ajo ei ole kayty)" % nimi)
            continue
        if not t["viimeisin_paiva"]:
            ongelmat.append("salkku %s: ei yhtaan ajettua paivaa" % nimi)
            continue
        jaljessa = (viim - date.fromisoformat(t["viimeisin_paiva"])).days
        if jaljessa > 1:
            ongelmat.append("salkku %s jaljessa %d pv (viimeisin %s, data %s)" % (nimi, jaljessa, t["viimeisin_paiva"], viim))
        if t["jarru"]:
            ongelmat.append("salkku %s: HATAJARRU lukossa (Tony nollaa)" % nimi)
        h = t["hylatyt_viimeiset"]
        if len(h) == 3 and all(x for x in h):
            ongelmat.append("salkku %s: kolme viimeista paivaa ilman hyvaksyttya ehdotusta (LLM/putki rikki?)" % nimi)
        info.append("%s: arvo %s, viimeisin %s" % (nimi, "n/a" if t["arvo"] is None else "%.0f" % t["arvo"], t["viimeisin_paiva"]))
    if pysaytys_polku and os.path.exists(pysaytys_polku):
        ongelmat.append("KILL SWITCH paalla (%s): ajot pysaytetty" % pysaytys_polku)
    return ongelmat, info


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tg-env", default="/srv/kauppa/.env")
    ap.add_argument("--ei-tg", action="store_true")
    a = ap.parse_args()
    tanaan = datetime.now(timezone.utc).date()
    ongelmat, info = tarkista(config.DB_POLKU, rajat.SALKUT, tanaan, rajat.PYSAYTYS)
    try:
        env = llm.lue_env(a.tg_env)
    except llm.LLMVirhe:
        env = {}
    if ongelmat:
        msg = "Kauppatiimi HALYTYS:\n- " + "\n- ".join(ongelmat)
        print(msg)
        if not a.ei_tg:
            notify.laheta(msg, env)
        return 1
    msg = "Kauppatiimi OK. " + "; ".join(info)
    print(msg)
    if tanaan.weekday() == 6 and not a.ei_tg:
        notify.laheta(msg, env)
    return 0


if __name__ == "__main__":
    sys.exit(main())
