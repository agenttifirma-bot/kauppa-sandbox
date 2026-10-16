"""Suorituskykymittarit ja vertailusalkku (osta ja pida)."""
import math
import statistics
from datetime import date, datetime, timedelta, timezone

import rajat
from salkku import Datavirhe

PV = 86400000


def mittarit(arvot):
    """arvot: paivan paattymisarvot. Palauttaa dict (tuotto, max_dd, vol_pa, sharpe_pa)."""
    if len(arvot) < 3:
        return None
    tuotot = [arvot[i] / arvot[i - 1] - 1 for i in range(1, len(arvot))]
    huippu, mdd = arvot[0], 0.0
    for a in arvot:
        huippu = max(huippu, a)
        mdd = max(mdd, 1 - a / huippu)
    sd = statistics.stdev(tuotot)
    return {
        "tuotto": arvot[-1] / arvot[0] - 1,
        "max_dd": mdd,
        "vol_pa": sd * math.sqrt(365),
        "sharpe_pa": (statistics.fmean(tuotot) / sd * math.sqrt(365)) if sd > 0 else None,
    }


def vertailusalkku(markkina, painot, alku, loppu, alkupaoma=None):
    """Osta ja pida: painot {symbol: osuus} ostetaan alku-paivan avaushintaan (kulu + slippage), loput kateiseksi.
    Palauttaa [(paiva_iso, arvo)] paivan sulkuhinnoilla alku..loppu (molemmat mukana)."""
    pao = float(alkupaoma if alkupaoma is not None else rajat.ALKUPAOMA)
    ms = lambda p: int(datetime(p.year, p.month, p.day, tzinfo=timezone.utc).timestamp() * 1000)
    kassa = pao
    maarat = {}
    for s, w in painot.items():
        r = markkina.execute("SELECT open FROM hinnat WHERE symbol=? AND ts=?", (s, ms(alku))).fetchone()
        if r is None:
            raise Datavirhe("vertailusalkku: ei avaushintaa %s %s" % (s, alku))
        hinta = r[0] * (1 + rajat.SLIPPAGE)
        kulutus = pao * w
        maarat[s] = kulutus / (hinta * (1 + rajat.KULU))
        kassa -= kulutus
    ulos, p = [], alku
    while p <= loppu:
        arvo = kassa
        for s, q in maarat.items():
            r = markkina.execute("SELECT close FROM hinnat WHERE symbol=? AND ts=?", (s, ms(p))).fetchone()
            if r is None:
                raise Datavirhe("vertailusalkku: ei sulkuhintaa %s %s" % (s, p))
            arvo += q * r[0]
        ulos.append((p.isoformat(), arvo))
        p += timedelta(days=1)
    return ulos
