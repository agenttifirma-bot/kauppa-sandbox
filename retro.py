"""Viikkoretro: sunnuntain yhteenveto Telegramiin. Vain luku: ei koskaan muuta salkkuja eika kutsu LLM:aa.
Vertaa kahta mallisalkkua (flash/pro) vertailusalkkuun (Tonyn jako) ja BTC:hen. Ei johtopaatoksia lyhyesta datasta."""
import argparse
import os
import sqlite3
import sys
from datetime import date, datetime, timedelta, timezone

import config
import llm
import mittarit
import notify
import rajat
import salkku

MIN_PV_JOHTOPAATOS = 28  # tata lyhyemmalla historialla ei sanota kumpi malli on parempi


def _ro(polku):
    return sqlite3.connect("file:%s?mode=ro" % polku, uri=True, timeout=10)


def lue_salkku(polku):
    """Palauttaa dictin tai None jos tiedostoa ei ole / ei viela ajettu."""
    if not os.path.exists(polku):
        return None
    con = _ro(polku)
    try:
        tila = dict(con.execute("SELECT avain, arvo FROM tila").fetchall())
        arvot = con.execute("SELECT paiva, arvo FROM arvot ORDER BY paiva").fetchall()
        kaupat = con.execute("SELECT paiva, symbol, puoli, maara, hinta, kulu, slippage_kulu FROM kaupat ORDER BY id").fetchall()
        paatokset = con.execute("SELECT paiva, hylatty FROM paatokset ORDER BY paiva").fetchall()
    finally:
        con.close()
    return {"tila": tila, "arvot": arvot, "kaupat": kaupat, "paatokset": paatokset}


def _pct(a, b):
    return 100.0 * (a / b - 1) if b else 0.0


def salkun_rivi(nimi, s, tanaan):
    """Palauttaa (rivit, tiedot) yhdelle salkulle."""
    if s is None or not s["arvot"]:
        return ["%s: ei viela dataa" % nimi], None
    arvot = s["arvot"]
    viim_p, viim_a = arvot[-1]
    alku_a = float(s["tila"].get("alkupaoma", rajat.ALKUPAOMA))
    viikko_alku = (date.fromisoformat(viim_p) - timedelta(days=7)).isoformat()
    ed = [a for p, a in arvot if p <= viikko_alku]
    viikko_a = ed[-1] if ed else alku_a
    mdd = mittarit.mittarit([a for _, a in arvot])
    vk_kaupat = [k for k in s["kaupat"] if k[0] > viikko_alku]
    kulut = sum(k[5] + k[6] for k in vk_kaupat)
    vk_p = [h for p, h in s["paatokset"] if p > viikko_alku]
    hylatyt = sum(1 for h in vk_p if h)
    rivit = ["%s: %.0f USDT | alusta %+.2f %% | viikko %+.2f %%" % (nimi, viim_a, _pct(viim_a, alku_a), _pct(viim_a, viikko_a)),
             "  kaupat %d (kulut %.1f USDT), paatospaivia %d, hylattyja %d%s" % (
                 len(vk_kaupat), kulut, len(vk_p), hylatyt, ", max-drawdown %.1f %%" % (100 * mdd["max_dd"]) if mdd else "")]
    if s["tila"].get("jarru") == "1":
        rivit.append("  HATAJARRU LUKOSSA")
    return rivit, {"paiva": viim_p, "alku": s["tila"].get("aloituspaiva"), "tuotto": _pct(viim_a, alku_a), "viikko": _pct(viim_a, viikko_a), "arvot": arvot}


def vertailut(markkina, aloitus, viimeisin):
    """Palauttaa {nimi: (tuotto_alusta, tuotto_viikko)} tai {} jos dataa ei ole."""
    ulos = {}
    for nimi, painot in (("vertailu (Tonyn jako)", rajat.VERTAILU_PAINOT), ("BTC", {"BTCUSDT": 1.0})):
        try:
            v = mittarit.vertailusalkku(markkina, painot, aloitus, viimeisin)
        except salkku.Datavirhe:
            continue
        if len(v) < 2:
            continue
        viikko = v[max(0, len(v) - 8)][1]
        ulos[nimi] = (_pct(v[-1][1], rajat.ALKUPAOMA), _pct(v[-1][1], viikko))
    return ulos


def raportti(data_polku, salkut, tanaan, pysaytys_polku=None):
    rivit = ["Kauppatiimi viikkoretro (%s)" % tanaan.isoformat()]
    tiedot = {}
    for nimi, polku in sorted(salkut.items()):
        try:
            s = lue_salkku(polku)
        except sqlite3.Error as e:
            rivit.append("%s: kantaa ei voi lukea (%s)" % (nimi, type(e).__name__))
            continue
        r, t = salkun_rivi(nimi, s, tanaan)
        rivit += r
        if t:
            tiedot[nimi] = t
    if tiedot:
        alut = [t["alku"] for t in tiedot.values() if t["alku"]]
        viim = max(date.fromisoformat(t["paiva"]) for t in tiedot.values())
        if alut:
            aloitus = date.fromisoformat(min(alut))
            try:
                markkina = _ro(data_polku)
                try:
                    v = vertailut(markkina, aloitus, viim)
                finally:
                    markkina.close()
            except sqlite3.Error:
                v = {}
            for n, (a, w) in v.items():
                rivit.append("%s: alusta %+.2f %% | viikko %+.2f %%" % (n, a, w))
            if not v:
                rivit.append("vertailu ei saatavilla")
            pv = (viim - aloitus).days + 1
        else:
            pv = 0
        if pv < MIN_PV_JOHTOPAATOS:
            rivit.append("Historiaa %d pv < %d: ei johtopaatoksia kummastakaan mallista (satunnaisvaihtelu dominoi)." % (pv, MIN_PV_JOHTOPAATOS))
        elif len(tiedot) == 2:
            (n1, t1), (n2, t2) = sorted(tiedot.items())
            ero = t1["tuotto"] - t2["tuotto"]
            rivit.append("%d pv: %s vs %s ero %+.2f %%-yks. Yksi jakso ei todista mallin paremmuutta; K6-testit ratkaisevat." % (pv, n1, n2, ero))
    if pysaytys_polku and os.path.exists(pysaytys_polku):
        rivit.append("KILL SWITCH PAALLA: ajot pysaytetty")
    return "\n".join(rivit)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tg-env", default="/srv/kauppa/.env")
    ap.add_argument("--ei-tg", action="store_true")
    a = ap.parse_args()
    tanaan = datetime.now(timezone.utc).date()
    msg = raportti(config.DB_POLKU, rajat.SALKUT, tanaan, rajat.PYSAYTYS)
    print(msg)
    if not a.ei_tg:
        try:
            env = llm.lue_env(a.tg_env)
        except llm.LLMVirhe:
            env = {}
        notify.laheta(msg, env)
    return 0


if __name__ == "__main__":
    sys.exit(main())
