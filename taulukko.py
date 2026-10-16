"""Rakentaa mallille menevan <data>-taulukon paivalle D. Vain dataa ennen D (suljetut paivakynttilat).
Jokainen luku on koodin laskema; puuttuva tai aukkoinen data nayttaa 'n/a' (fail closed)."""
import sys
from datetime import date, datetime, timezone

import config
import db
import indikaattorit as ind
import universumi as uni

PV = 86400000
HISTORIA = 91  # paivaa (r90 tarvitsee 91 sulkua)


def paiva_ms(p):
    return int(datetime(p.year, p.month, p.day, tzinfo=timezone.utc).timestamp() * 1000)


def _sulut(con, symbol, d_ms, paivia):
    """Palauttaa {ts: close} viimeiselta 'paivia' paivalta ennen D; vain jos taysin yhtenainen, muuten {}."""
    alku = d_ms - paivia * PV
    rivit = con.execute(
        "SELECT ts, close FROM hinnat WHERE symbol=? AND ts>=? AND ts<? ORDER BY ts", (symbol, alku, d_ms)
    ).fetchall()
    if len(rivit) != paivia:
        return {}
    return dict(rivit)


def _lista(d, d_ms, paivia):
    """Sulut aikajarjestyksessa jos ikkuna taysi, muuten None."""
    if len(d) < paivia:
        return None
    return [d[d_ms - k * PV] for k in range(paivia, 0, -1)]


def rivi_tiedot(con, s, d_ms, btc):
    d91 = _sulut(con, s, d_ms, 91)
    d61 = _sulut(con, s, d_ms, 61)
    d31 = _sulut(con, s, d_ms, 31)
    d8 = _sulut(con, s, d_ms, 8)
    d90 = _sulut(con, s, d_ms, 90)
    sul91, sul61, sul31, sul8, sul90 = (_lista(x, d_ms, n) for x, n in ((d91, 91), (d61, 61), (d31, 31), (d8, 8), (d90, 90)))
    close = None
    last = con.execute("SELECT close FROM hinnat WHERE symbol=? AND ts=?", (s, d_ms - PV)).fetchone()
    if last:
        close = last[0]
    corr = None
    if sul61 and btc.get("sul61"):
        corr = ind.korrelaatio(sul61, btc["sul61"], 60)
    f = con.execute("SELECT ts, interval_h, rate FROM funding WHERE symbol=? AND ts>=? AND ts<?",
                    (s, d_ms - 30 * PV, d_ms)).fetchall()
    return {
        "close": close,
        "r7": ind.tuotto(sul8, 7) if sul8 else None,
        "r30": ind.tuotto(sul31, 30) if sul31 else None,
        "r90": ind.tuotto(sul91, 90) if sul91 else None,
        "vol30": ind.volatiliteetti(sul31, 30) if sul31 else None,
        "dd90": ind.pudotus_huipusta(sul90, 90) if sul90 else None,
        "corr": corr,
        "f7": ind.funding_vuosituotto(f, d_ms, 7),
        "f30": ind.funding_vuosituotto(f, d_ms, 30),
        "sul61": sul61,
    }


def _p(x, kerroin=100.0, desim=1):
    return "n/a" if x is None else ("%.*f" % (desim, x * kerroin))


def rakenna(con, paiva, n=20):
    """Palauttaa (teksti, tiedot_dict). paiva = paatospaiva D (date); kaytetaan suljettuja kynttilöita < D."""
    d_ms = paiva_ms(paiva)
    uni_lista = uni.universumi(con, d_ms, n=n)
    btc = {"sul61": _lista(_sulut(con, "BTCUSDT", d_ms, 61), d_ms, 61)}
    tiedot = {s: rivi_tiedot(con, s, d_ms, btc) for s, _ in uni_lista}
    # momentum-ranki r90:n mukaan (1 = paras), vain kolikot joilla r90 on
    jarj = sorted([s for s in tiedot if tiedot[s]["r90"] is not None], key=lambda s: -tiedot[s]["r90"])
    ranki = {s: i + 1 for i, s in enumerate(jarj)}
    rivit = ["symbol | close | r7% | r30% | r90% | vol30%pa | dd90% | corrBTC60 | fund7%pa | fund30%pa | mom_ranki_r90"]
    for s, _ in uni_lista:
        t = tiedot[s]
        rivit.append(" | ".join([
            s, "n/a" if t["close"] is None else ("%.6g" % t["close"]),
            _p(t["r7"]), _p(t["r30"]), _p(t["r90"]), _p(t["vol30"]), _p(t["dd90"]),
            _p(t["corr"], 1.0, 2), _p(t["f7"]), _p(t["f30"]), str(ranki.get(s, "n/a")),
        ]))
    r30 = [tiedot[s]["r30"] for s in tiedot]
    pos = [x for x in r30 if x is not None]
    yhteenveto = "universumi %d kolikkoa; r30-mediaani %s%%; positiivisia r30: %s/%d" % (
        len(uni_lista), _p(ind.mediaani(r30)), sum(1 for x in pos if x > 0), len(pos))
    viim = datetime.fromtimestamp((d_ms - PV) / 1000, timezone.utc).date()
    teksti = ('<data paiva="%s" viimeisin_suljettu="%s" yksikko="UTC-paivakynttilat, kulut ei mukana">\n%s\n%s\n</data>'
              % (paiva.isoformat(), viim.isoformat(), "\n".join(rivit), yhteenveto))
    for t in tiedot.values():
        t.pop("sul61", None)
    return teksti, tiedot


def main():
    con = db.avaa(config.DB_POLKU)
    p = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else datetime.now(timezone.utc).date()
    teksti, _ = rakenna(con, p)
    print(teksti)
    return 0


if __name__ == "__main__":
    sys.exit(main())
