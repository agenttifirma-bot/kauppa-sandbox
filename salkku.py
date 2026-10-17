"""Simuloitu paperisalkku. Paatos tehdaan datalla ennen paivaa D; toteutus paivan D avaushintaan + slippage + kulu;
arvostus paivan D sulkuun. Kaikki kaupat kirjataan (verokirjanpito)."""
import json
import sqlite3
from datetime import datetime, timezone

import rajat
import riskivahti
from riskivahti import Ehdotusvirhe

PV = 86400000


class Datavirhe(Exception):
    pass


SKEEMA = """
CREATE TABLE IF NOT EXISTS tila (avain TEXT PRIMARY KEY, arvo TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS positiot (symbol TEXT PRIMARY KEY, maara REAL NOT NULL);
CREATE TABLE IF NOT EXISTS kaupat (
  id INTEGER PRIMARY KEY AUTOINCREMENT, paiva TEXT NOT NULL, symbol TEXT NOT NULL, puoli TEXT NOT NULL,
  maara REAL NOT NULL, hinta REAL NOT NULL, kulu REAL NOT NULL, slippage_kulu REAL NOT NULL);
CREATE TABLE IF NOT EXISTS arvot (paiva TEXT PRIMARY KEY, arvo REAL NOT NULL, kateinen REAL NOT NULL, positiot_arvo REAL NOT NULL);
CREATE TABLE IF NOT EXISTS paatokset (paiva TEXT PRIMARY KEY, ehdotus TEXT, rajaukset TEXT, hylatty TEXT);
"""


def avaa(polku=None, alkupaoma=None):
    con = sqlite3.connect(polku or rajat.SALKKU_DB, timeout=30)
    con.executescript(SKEEMA)
    if _hae(con, "kateinen") is None:
        a = float(alkupaoma if alkupaoma is not None else rajat.ALKUPAOMA)
        _aseta(con, "kateinen", a)
        _aseta(con, "alkupaoma", a)
        _aseta(con, "jarru", "0")
    return con


def _hae(con, avain):
    r = con.execute("SELECT arvo FROM tila WHERE avain=?", (avain,)).fetchone()
    return r[0] if r else None


def _aseta(con, avain, arvo):
    con.execute("INSERT OR REPLACE INTO tila VALUES (?,?)", (avain, str(arvo)))
    con.commit()


def kateinen(con):
    return float(_hae(con, "kateinen"))


def positiot(con):
    return dict(con.execute("SELECT symbol, maara FROM positiot WHERE maara > 0").fetchall())


def nollaa_jarru(con):
    """VAIN TONY: poistaa hatajarrun lukon manuaalisesti. HUOM (auditointi A8c): drawdown mitataan yha koko historian huipusta,
    joten jarru lukkiutuu uudelleen jos arvo on yha yli rajan huipusta. Tonyn paatettava, halutaanko nollaus huipun nollaukseksi."""
    _aseta(con, "jarru", "0")


def _hinnat(markkina, symbol, d_ms):
    r = markkina.execute("SELECT open, close FROM hinnat WHERE symbol=? AND ts=?", (symbol, d_ms)).fetchone()
    return r


def _arvohistoria(con):
    """Paivan paattymisarvot kronologisesti; alkupaoma aina ensimmaisena (huippu ja paivatappio mitataan siita)."""
    alku = float(_hae(con, "alkupaoma"))
    return [alku] + [float(r[0]) for r in con.execute("SELECT arvo FROM arvot ORDER BY paiva")]


def suorita_paiva(con, markkina, paiva, ehdotus, sallitut):
    """paiva: date. ehdotus: {symbol: tavoitepaino}. Palauttaa yhteenvedon. Nostaa Datavirhe jos arvostus ei onnistu."""
    pstr = paiva.isoformat()
    edellinen = _hae(con, "viimeisin_paiva")
    if edellinen is not None and pstr <= edellinen:
        raise Datavirhe("paiva %s on jo ajettu (viimeisin %s)" % (pstr, edellinen))
    d_ms = int(datetime(paiva.year, paiva.month, paiva.day, tzinfo=timezone.utc).timestamp() * 1000)
    omat = positiot(con)
    avaus, sulku = {}, {}
    for s in omat:
        h = _hinnat(markkina, s, d_ms)
        if h is None:
            raise Datavirhe("ei hintaa omistetulle kolikolle %s paivalle %s" % (s, pstr))
        avaus[s], sulku[s] = h
    huom = []
    kassa = kateinen(con)
    v_open = kassa + sum(omat[s] * avaus[s] for s in omat)
    historia = _arvohistoria(con)
    jarru, ostot_estetty, dd = riskivahti.tila(historia, _hae(con, "jarru") == "1")
    if jarru:
        _aseta(con, "jarru", "1")
    # tavoitepainot
    hylatty = None
    painot = {}
    if jarru:
        huom.append("HATAJARRU: kaikki kateiseksi (lukko kunnes Tony nollaa), drawdown %.1f %%" % (dd * 100))
    else:
        try:
            painot, h = riskivahti.siisti_ehdotus(ehdotus, sallitut)
            huom += h
        except Ehdotusvirhe as e:
            hylatty = str(e)
            painot = {s: (omat[s] * avaus[s] / v_open if v_open > 0 else 0.0) for s in omat}  # ei muutoksia
            if ehdotus is None:
                huom.append("EI KAUPPOJA: ei ehdotusta (kriitikko hylkasi tai analyytikko ei ehdottanut painoja)")
            else:
                huom.append("EHDOTUS HYLATTY, ei kauppoja: %s" % e)
    for s in list(painot):
        if s not in avaus:
            h = _hinnat(markkina, s, d_ms)
            if h is None:
                painot.pop(s)
                huom.append("%s: ei hintaa paivalle, ohitettu" % s)
            else:
                avaus[s], sulku[s] = h
    # kauppaehdotukset
    ehd = []
    for s in sorted(set(omat) | set(painot)):   # jarjestys deterministinen (ei hash-satunnaisuutta)
        pidetty = omat.get(s, 0.0) * avaus.get(s, 0.0)
        tavoite = painot.get(s, 0.0) * v_open
        if s not in painot and not jarru and hylatty is None:
            tavoite = 0.0  # ehdotuksessa ei mainittu = myy pois
        ero = tavoite - pidetty
        if ero < 0 and (tavoite == 0.0 or -ero >= rajat.MIN_KAUPPA_OSUUS * v_open):
            ehd.append(("SELL", s, -ero if tavoite > 0 else pidetty))
        elif ero > 0 and ero >= rajat.MIN_KAUPPA_OSUUS * v_open:
            if ostot_estetty or jarru:
                huom.append("%s osto estetty (paivatappioraja)" % s)
            else:
                ehd.append(("BUY", s, ero))
    ehd.sort(key=lambda x: (x[0] != "SELL", -x[2], x[1]))
    if len(ehd) > rajat.MAX_KAUPPOJA_PAIVA and not jarru:   # hatajarrun myynteja ei rajata
        huom.append("kauppoja rajattu %d -> %d" % (len(ehd), rajat.MAX_KAUPPOJA_PAIVA))
        ehd = ehd[:rajat.MAX_KAUPPOJA_PAIVA]
    kaupat = []
    # myynnit
    for puoli, s, arvo in ehd:
        if puoli != "SELL":
            continue
        qty = min(omat.get(s, 0.0), arvo / avaus[s])
        if qty <= 0:
            continue
        hinta = avaus[s] * (1 - rajat.SLIPPAGE)
        tulo = qty * hinta
        kulu = tulo * rajat.KULU
        kassa += tulo - kulu
        omat[s] = omat.get(s, 0.0) - qty
        kaupat.append((pstr, s, "SELL", qty, hinta, kulu, qty * avaus[s] * rajat.SLIPPAGE))
    # ostot, kateispuskuri turvaan
    ostot = [(s, a) for p, s, a in ehd if p == "BUY"]
    kaytettavissa = kassa - rajat.KATEISPUSKURI_MIN * v_open
    tarve = sum(a for _, a in ostot)
    if ostot and tarve > 0:
        if kaytettavissa <= 0:
            huom.append("ostot ohitettu: kateispuskuri")
            ostot = []
        elif tarve > kaytettavissa:
            k = kaytettavissa / tarve
            ostot = [(s, a * k) for s, a in ostot]
            huom.append("ostot skaalattu %.2f (kateispuskuri)" % k)
    for s, kulutus in ostot:
        hinta = avaus[s] * (1 + rajat.SLIPPAGE)
        qty = kulutus / (hinta * (1 + rajat.KULU))
        kulu = qty * hinta * rajat.KULU
        kassa -= qty * hinta + kulu
        omat[s] = omat.get(s, 0.0) + qty
        kaupat.append((pstr, s, "BUY", qty, hinta, kulu, qty * avaus[s] * rajat.SLIPPAGE))
    if kassa < -1e-6:
        raise Datavirhe("kassa negatiivinen, keskeytetty")
    # tallennus yhdessa transaktiossa
    with con:
        con.execute("DELETE FROM positiot")
        con.executemany("INSERT INTO positiot VALUES (?,?)", [(s, q) for s, q in omat.items() if q > 1e-12])
        con.executemany("INSERT INTO kaupat (paiva,symbol,puoli,maara,hinta,kulu,slippage_kulu) VALUES (?,?,?,?,?,?,?)", kaupat)
        con.execute("INSERT OR REPLACE INTO tila VALUES ('kateinen', ?)", (str(kassa),))
        sul_arvo = kassa + sum(q * sulku[s] for s, q in omat.items() if q > 1e-12)
        con.execute("INSERT INTO arvot VALUES (?,?,?,?)", (pstr, sul_arvo, kassa, sul_arvo - kassa))
        con.execute("INSERT OR REPLACE INTO paatokset VALUES (?,?,?,?)", (pstr, json.dumps(ehdotus, default=str), json.dumps(huom), hylatty))
        con.execute("INSERT OR REPLACE INTO tila VALUES ('viimeisin_paiva', ?)", (pstr,))
    # paivan paatosarvon perusteella lukitaan hatajarru seuraavalle paivalle
    jarru2, _, dd2 = riskivahti.tila(historia + [sul_arvo], jarru)
    if jarru2 and not jarru:
        _aseta(con, "jarru", "1")
        huom.append("HATAJARRU lukittu: drawdown %.1f %%" % (dd2 * 100))
    return {"paiva": pstr, "v_open": v_open, "v_close": sul_arvo, "kaupat": kaupat, "huomautukset": huom, "jarru": jarru2}

