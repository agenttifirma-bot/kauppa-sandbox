"""K11b/c: selviytymisharhan mittaus. Ajaa saman rehellisen walk-forward-backtestin (backtest.py) kolmella universumilla:
  vanha  = kovakoodattu 20 kolikon lista (config.SYMBOLIT, valittu jalkikateen 2026) -- nykyinen tapa
  elossa = point-in-time top-n volyymin mukaan, mutta VAIN kolikoista jotka ovat yha elossa datan lopussa (jalkiviisas)
  kaikki = point-in-time top-n volyymin mukaan kaikista paareista, myos myohemmin kuolleista
Ero elossa -> kaikki on mitattu selviytymisharha. Delistaus: kuolleen kolikon omistaja saa myyda viimeiseen sulkuhintaan
miinus haircut (synteettinen hintarivi); herkkyys 0 / 10 / 30 %. Uudelleennimeamiset (MATIC->POL jne.) yhdistetaan jos hinta jatkuu.
VAIN backtest: ei kosketa paivittaiseen paperikauppaan, backtest.py:hyn eika salkku.py:hyn. Oma kokeilurekisteri."""
import argparse
import os
import sqlite3
import sys
from datetime import date, datetime, timedelta, timezone

import backtest as bt
import config
import db
import mittarit as mit
import rajat

PV = 86400000
HISTORIA_DB = os.environ.get("KAUPPA_HISTORIA_DB", "/srv/kauppa/data/historia.db")
REKISTERI_LAAJA = os.environ.get("KAUPPA_KOKEILU_LAAJA_DB", "/srv/kauppa/data/kokeilut_laaja.db")
TULOS_TIEDOSTO = os.environ.get("KAUPPA_LAAJA_TULOS", "/srv/kauppa/data/laaja_tulos.txt")

# vanha tunnus -> uusi tunnus (sama kolikko, 1:1-siirto). Yhdistetaan vain jos hinta jatkuu saumassa (suhde 0.7..1.4).
RENAME = {"MATICUSDT": "POLUSDT", "FTMUSDT": "SUSDT", "EOSUSDT": "AUSDT", "RNDRUSDT": "RENDERUSDT"}
KUOLLUT_PV = 90        # kolikko on "kuollut" jos sen data loppuu yli 90 paivaa ennen koko datan loppua
SYNT_PV = 30           # synteettisia myyntirivejä delistauksen jalkeen (ettei omistus jaa hinnatta)
UNI_IKKUNA = 30
AUKKO_PV = 10          # yli tama aukko datassa = kolikko "kuoli" (tunnus voi vaihtua toiseen kolikkoon, esim. LUNA 2022)
OLETUS_SKENAARIOT = ",".join("%s:0.1:%s" % (t, j) for j in ("0.2", "0.25", "1.0") for t in ("vanha", "elossa", "kaikki")) + ",kaikki:0.0:0.25,kaikki:0.3:0.25"


def _lue(polku):
    con = sqlite3.connect(polku)
    close, open_, qv = {}, {}, {}
    for s, ts, o, c, q in con.execute("SELECT symbol, ts, open, close, quote_volume FROM hinnat ORDER BY symbol, ts"):
        close.setdefault(s, {})[ts] = c
        open_.setdefault(s, {})[ts] = o
        qv.setdefault(s, {})[ts] = q
    con.close()
    return close, open_, qv


def yhdista_nimimuutokset(close, open_, qv, rename=None):
    """Siirtaa vanhan tunnuksen historian uuden tunnuksen alle jos hinta jatkuu. Palauttaa raporttirivit."""
    raportti = []
    for vanha, uusi in (RENAME if rename is None else rename).items():
        if vanha not in close or uusi not in close:
            continue
        v_viim = max(close[vanha])
        u_eka = min(close[uusi])
        if u_eka > v_viim + 14 * PV or min(close[vanha]) > u_eka:
            raportti.append("EI yhdistetty %s -> %s: ajat eivat jatku (vanha loppuu %s, uusi alkaa %s)" % (
                vanha, uusi, _pv(v_viim), _pv(u_eka)))
            continue
        # vertailuhinnat saumasta: sama paiva jos molemmat kauppasivat silloin, muuten vanhan viimeinen ja uuden ensimmainen sulku
        ref = u_eka if u_eka in close[vanha] else v_viim
        suhde = close[uusi][u_eka] / close[vanha][ref]
        if not 0.7 <= suhde <= 1.4:
            raportti.append("EI yhdistetty %s -> %s: hinta ei jatku (suhde %.2f)" % (vanha, uusi, suhde))
            continue
        for kartta in (close, open_, qv):
            tayta = {ts: v for ts, v in kartta[vanha].items() if ts not in kartta[uusi]}
            kartta[uusi].update(tayta)
            del kartta[vanha]
        raportti.append("yhdistetty %s -> %s (sauma %s, hintasuhde %.2f)" % (vanha, uusi, _pv(v_viim), suhde))
    return raportti


def katkaise_aukot(close, open_, qv, aukko_pv=AUKKO_PV):
    """Yli aukko_pv paivan aukko = vanha pätkä on kuollut kolikko (nimi SYMBOL#1, #2...), uusi pätkä pitää tunnuksen.
    Lyhyemmat aukot: palauttaa tayttolistan [(symbol, ts, edellinen_sulku)] (jaadytetty hinta, vain myyntia varten).
    Palauttaa (taytot, raportti)."""
    taytot, raportti = [], []
    for s in sorted(close):
        ts = sorted(close[s])
        rajat_ = [i for i in range(1, len(ts)) if ts[i] - ts[i - 1] > aukko_pv * PV]
        for i in range(1, len(ts)):
            ero = ts[i] - ts[i - 1]
            if PV < ero <= aukko_pv * PV:
                for k in range(1, ero // PV):
                    taytot.append((s, ts[i - 1] + k * PV, close[s][ts[i - 1]]))
        if not rajat_:
            continue
        alut = [0] + rajat_ + [len(ts)]
        for n in range(len(alut) - 2):               # kaikki paitsi viimeinen pätkä -> uusi nimi
            osa = ts[alut[n]:alut[n + 1]]
            nimi = "%s#%d" % (s, n + 1)
            for kartta in (close, open_, qv):
                kartta[nimi] = {t: kartta[s][t] for t in osa}
            raportti.append("jaettu %s: pätkä %s..%s -> %s (aukko %s..%s)" % (
                s, _pv(osa[0]), _pv(osa[-1]), nimi, _pv(osa[-1]), _pv(ts[alut[n + 1]])))
        for kartta in (close, open_, qv):
            for t in ts[:alut[-2]]:
                del kartta[s][t]
    return taytot, raportti


def _pv(ms):
    return datetime.fromtimestamp(ms / 1000, timezone.utc).date().isoformat()


class LaajaData:
    """Sama rajapinta kuin backtest.Data (con, n, close, open, sulut, universum). Hinnat muistissa + muistikanta delistausriveilla."""

    def __init__(self, polku=None, tila="kaikki", n=20, haircut=0.10, lista=None, rename=None, _syotteet=None):
        if tila not in ("vanha", "elossa", "kaikki"):
            raise ValueError("tuntematon universumi: %s" % tila)
        self.tila, self.n, self.haircut = tila, n, haircut
        close, open_, qv = _syotteet if _syotteet is not None else _lue(polku or HISTORIA_DB)
        self.raportti = yhdista_nimimuutokset(close, open_, qv, rename)
        taytot, self.aukkoraportti = katkaise_aukot(close, open_, qv)
        loppu = max(max(d) for d in close.values())
        self.loppu_ts = loppu
        self.eka = {s: min(d) for s, d in close.items()}
        self.vika = {s: max(d) for s, d in close.items()}
        self.kuollut = {s for s in close if self.vika[s] < loppu - KUOLLUT_PV * PV}
        vanha_lista = set(lista if lista is not None else config.SYMBOLIT)
        if tila == "vanha":
            valitut = [s for s in close if s in vanha_lista]
        elif tila == "elossa":
            valitut = [s for s in close if s not in self.kuollut]
        else:
            valitut = list(close)
        self.symbolit = sorted(valitut)
        self.close = {s: close[s] for s in self.symbolit}
        self.open = {s: open_[s] for s in self.symbolit}
        self.qv = {s: qv[s] for s in self.symbolit}
        self.con = db.avaa(":memory:")
        rivit = []
        valitut_set = set(self.symbolit)
        for s in self.symbolit:
            c, o, q = self.close[s], self.open[s], self.qv[s]
            for ts in c:
                oo, cc = o[ts], c[ts]
                rivit.append((s, ts, oo, max(oo, cc), min(oo, cc), cc, 0.0, q[ts], 0))
            if s in self.kuollut:   # delistaus: omistaja voi myyda viimeiseen sulkuun miinus haircut
                hinta = c[self.vika[s]] * (1 - haircut)
                for k in range(1, SYNT_PV + 1):
                    rivit.append((s, self.vika[s] + k * PV, hinta, hinta, hinta, hinta, 0.0, 0.0, 0))
        for s_, t_, c_ in taytot:   # lyhyet aukot: jaadytetty hinta, ettei omistettu kolikko jaa ilman hintaa
            if s_ in valitut_set:
                rivit.append((s_, t_, c_, c_, c_, c_, 0.0, 0.0, 0))
        with self.con:
            self.con.executemany("INSERT OR IGNORE INTO hinnat VALUES (?,?,?,?,?,?,?,?,?)", rivit)
        self._uni = {}

    def sulut(self, symbol, d_ms, n):
        d = self.close.get(symbol)
        if d is None:
            return None
        ulos = []
        for k in range(n, 0, -1):
            v = d.get(d_ms - k * PV)
            if v is None:
                return None
            ulos.append(v)
        return ulos

    def universum(self, d_ms):
        """Point-in-time: volyymi vain ikkunasta [d-30, d); kolikon pitaa kaupata paivana d (avaushinta olemassa) ja
        sen ikkunan taytyy olla aukoton. Kuollut kolikko poistuu universumista viimeisen paivansa jalkeen -> omistus myydaan."""
        if d_ms not in self._uni:
            alku = d_ms - UNI_IKKUNA * PV
            tulos = []
            for s in self.symbolit:
                if self.eka[s] > alku or self.vika[s] < d_ms:
                    continue
                qv = self.qv[s]
                vol, ok = 0.0, True
                for k in range(UNI_IKKUNA, 0, -1):
                    v = qv.get(d_ms - k * PV)
                    if v is None:
                        ok = False
                        break
                    vol += v
                if ok:
                    tulos.append((s, vol))
            tulos.sort(key=lambda x: (-x[1], x[0]))
            self._uni[d_ms] = [s for s, _ in tulos[:self.n]]
        return self._uni[d_ms]

    def kuolleet_universumissa(self, ikkunat_):
        """Kuinka monta myohemmin kuollutta kolikkoa oli testijaksoilla universumissa vahintaan yhtena paivana."""
        nahty = set()
        for a, b in ikkunat_:
            p = a
            while p <= b:
                nahty |= set(self.universum(bt._ms(p))) & self.kuollut
                p += timedelta(days=1)
        return sorted(nahty)


class HistoriaPuuttuu(Exception):
    pass


def rehellinen_data(polku=None, n=20, haircut=0.10):
    """K12: oletusdata K7:lle ja K6:lle. Point-in-time top-n volyymin mukaan kaikista USDT-pareista (myos kuolleet).
    Fail closed: jos historia.db puuttuu, ei palata hiljaa jalkikateen valittuun listaan."""
    p = polku or HISTORIA_DB
    if not os.path.exists(p):
        raise HistoriaPuuttuu("historia.db puuttuu (%s): aja ensin historia_lataus.py tai kayta --data markkina" % p)
    return LaajaData(p, tila="kaikki", n=n, haircut=haircut)


def _f(x):
    return "n/a" if x is None else "%.1f %%" % (x * 100)


def skenaario(polku, tila, haircut, satunnaisia, rek, ruudukko, alku=None, loppu=None, _syotteet=None, jarru=None):
    """Ajaa yhden skenaarion. jarru: hatajarrun raja (osuus) VAIN taman backtestin ajaksi; None = rajat.py:n arvo.
    Palauttaa (tekstirivit, tiivistelma-dict). rajat.MAX_DRAWDOWN palautetaan aina (ei jaa muistiin)."""
    vanha_raja = rajat.MAX_DRAWDOWN
    if jarru is not None:
        rajat.MAX_DRAWDOWN = jarru
    try:
        return _skenaario(polku, tila, haircut, satunnaisia, rek, ruudukko, alku, loppu, _syotteet)
    finally:
        rajat.MAX_DRAWDOWN = vanha_raja


def _jarru_teksti(j):
    return "ei jarrua" if j >= 1.0 else "hatajarru %d %%" % round(j * 100)


def _skenaario(polku, tila, haircut, satunnaisia, rek, ruudukko, alku, loppu, _syotteet):
    data = LaajaData(polku, tila=tila, haircut=haircut, _syotteet=_syotteet)
    wf = bt.walk_forward("laaja-momentum-%s" % tila, lambda **p: bt.momentum(**p), ruudukko, data, rek, alku=alku, loppu=loppu,
                         edistyminen=lambda i, f: print("  fold %d: valittu %s, OOS %s" % (i, f["valittu"], _f(f["oos_tuotto"])), flush=True))
    f = wf["foldit"]
    sat = bt.satunnaisjakauma(data, wf["ikkunat"], satunnaisia, k=[x["valittu"]["k"] for x in f],
                              reb=[x["valittu"]["reb"] for x in f], ikkuna=[x["valittu"]["ikkuna"] for x in f])
    btc = bt.btc_vertailu(data, wf["ikkunat"])
    a = bt.arvio(wf, sat, btc, len(ruudukko))
    # passiivinen vertailu: kaikki universumin kolikot tasapainoin -- puhtain selviytymisharhan mittari
    osat = [bt._aja(bt.tasapaino(), data, x, y)[0] for x, y in wf["ikkunat"]]
    tas = mit.mittarit(bt._ketju(osat))
    kuolleet = data.kuolleet_universumissa(wf["ikkunat"])
    rivit = [
        "== universumi=%s, haircut=%d %%, %s ==" % (tila, round(haircut * 100), _jarru_teksti(rajat.MAX_DRAWDOWN)),
        "momentum OOS: tuotto %s, max dd %s, Sharpe %s | BTC tuotto %s, Sharpe %s" % (
            _f(a["oos_tuotto"]), _f(a["oos_max_dd"]), "n/a" if a["oos_sharpe"] is None else "%.2f" % a["oos_sharpe"],
            _f(a["btc_tuotto"]), "n/a" if a["btc_sharpe"] is None else "%.2f" % a["btc_sharpe"]),
        "satunnaisvertailu (%d kpl): p=%.3f, korjattu p=%.3f%s" % (
            a["satunnaisia"], a["p_satunnainen"], a["p_korjattu"], "" if a["riittavasti_satunnaisia"] else " [liian vahan satunnaisia verdiktiin]"),
        "tasapainoinen kori (kaikki universumin kolikot): tuotto %s, max dd %s, Sharpe %s" % (
            _f((tas or {}).get("tuotto")), _f((tas or {}).get("max_dd")),
            "n/a" if not tas or tas["sharpe_pa"] is None else "%.2f" % tas["sharpe_pa"]),
        "myohemmin kuolleita kolikoita universumissa testijaksoilla: %d%s" % (len(kuolleet), (" (" + ", ".join(kuolleet[:12]) + (" ..." if len(kuolleet) > 12 else "") + ")") if kuolleet else ""),
    ]
    return rivit, {"tila": tila, "haircut": haircut, "jarru": rajat.MAX_DRAWDOWN, "momentum": a["oos_tuotto"], "sharpe": a["oos_sharpe"],
                   "kori": (tas or {}).get("tuotto"), "btc": a["btc_tuotto"], "kuolleita": len(kuolleet), "raportti": data.raportti, "aukot": data.aukkoraportti}


def vertailu(tulokset):
    """Yhteenveto per hatajarrun arvo. valintaharha = vanha lista -> point-in-time (elossa); kuolleiden harha = elossa -> kaikki (haircut 10 %)."""
    rivit = []
    jarrut = sorted({t.get("jarru", rajat.MAX_DRAWDOWN) for t in tulokset})
    for j in jarrut:
        haku = {(t["tila"], round(t["haircut"] * 100)): t for t in tulokset if t.get("jarru", rajat.MAX_DRAWDOWN) == j}
        v, e, k = haku.get(("vanha", 10)), haku.get(("elossa", 10)), haku.get(("kaikki", 10))
        rivit.append("-- %s --" % _jarru_teksti(j))
        for nimi, avain in (("momentum", "momentum"), ("tasapainoinen kori", "kori")):
            osat = [(n, t) for n, t in (("vanha lista", v), ("elossa", e), ("kaikki", k)) if t and t[avain] is not None]
            if len(osat) >= 2:
                rivit.append("%s OOS: %s" % (nimi, " -> ".join("%s %s" % (n, _f(t[avain])) for n, t in osat)))
    return rivit


def jasenna(osa):
    """'tila:haircut[:jarru]' -> (tila, haircut, jarru tai None)."""
    p = [x.strip() for x in osa.split(":")]
    if len(p) not in (2, 3):
        raise ValueError("skenaario pitaa olla tila:haircut[:jarru], saatiin %r" % osa)
    return p[0], float(p[1]), (float(p[2]) if len(p) == 3 else None)


def main(argv=None):
    ap = argparse.ArgumentParser(description="K11b/c: selviytymisharhan mittaus (vain backtest)")
    ap.add_argument("--db", default=HISTORIA_DB)
    ap.add_argument("--rekisteri", default=REKISTERI_LAAJA)
    ap.add_argument("--satunnaisia", type=int, default=300)
    ap.add_argument("--skenaariot", default=OLETUS_SKENAARIOT, help="tila:haircut[:jarru], pilkulla eroteltuina")
    ap.add_argument("--ulos", default=TULOS_TIEDOSTO)
    a = ap.parse_args(argv)
    if os.path.abspath(a.rekisteri) == os.path.abspath(rajat.KOKEILU_DB):
        print("EI SALLITTU: kokeilurekisteri ei saa olla tuotantorekisteri (monivertailubudjetti)", flush=True)
        return 3
    if not os.path.exists(a.db):
        print("historia.db puuttuu: aja ensin historia_lataus.py", flush=True)
        return 2
    rek = bt.avaa_rekisteri(a.rekisteri)
    ruudukko = [{"ikkuna": i, "k": k, "reb": r} for i in (30, 60, 90) for k in (3, 5, 8) for r in (7, 14, 30)]
    tulokset, epaonnistui = [], []
    ulos = open(a.ulos, "w")

    def kirjoita(rivit):
        print("\n".join(rivit), flush=True)
        ulos.write("\n".join(rivit) + "\n")
        ulos.flush()
    for osa in a.skenaariot.split(","):
        tila, h, j = jasenna(osa)
        print("--- skenaario %s ---" % osa, flush=True)
        try:
            rivit, t = skenaario(a.db, tila, h, a.satunnaisia, rek, ruudukko, jarru=j)
        except Exception as e:   # yksi virhe ei saa havittaa muita tuloksia; virhe nakyy tuloksessa
            epaonnistui.append(osa)
            kirjoita(["== EPAONNISTUI %s: %s: %s ==" % (osa, type(e).__name__, str(e)[:200])])
            continue
        tulokset.append(t)
        kirjoita(rivit)
    loppu = ["", "== YHTEENVETO =="] + vertailu(tulokset)
    if tulokset:
        loppu += ["nimimuutokset: " + "; ".join(tulokset[0]["raportti"]) if tulokset[0]["raportti"] else "nimimuutoksia ei yhdistetty"]
    if tulokset and tulokset[0].get("aukot"):
        loppu.append("datan aukot (%d), esim: %s" % (len(tulokset[0]["aukot"]), "; ".join(tulokset[0]["aukot"][:6])))
    if epaonnistui:
        loppu.append("EPAONNISTUNEET skenaariot: " + ", ".join(epaonnistui))
    loppu.append("HUOM: tulokset eivat ole verdikti; ne kertovat paljonko jalkiviisas kolikkolista paisutti tuloksia. Holdoutiin ei koskettu.")
    kirjoita(loppu)
    ulos.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
