"""Puhtaat indikaattorifunktiot (ei kantaa, ei verkkoa). Palauttavat None jos dataa ei riita.
Koodi laskee, malli ei laske itse."""
import math
import statistics

PV = 86400000


def tuotto(sulut, n):
    if n < 1 or len(sulut) < n + 1:
        return None
    return sulut[-1] / sulut[-1 - n] - 1.0


def lokituotot(sulut):
    return [math.log(sulut[i] / sulut[i - 1]) for i in range(1, len(sulut))]


def volatiliteetti(sulut, n, vuosi=365):
    """Vuosikorjattu lokituottojen keskihajonta viimeisilta n paivalta."""
    if len(sulut) < n + 1:
        return None
    lt = lokituotot(sulut[-(n + 1):])
    return statistics.stdev(lt) * math.sqrt(vuosi)


def pudotus_huipusta(sulut, n):
    if len(sulut) < n:
        return None
    return sulut[-1] / max(sulut[-n:]) - 1.0


def korrelaatio(a, b, n):
    """a, b: samoille paiville kohdistetut sulkuhinnat (pituus >= n+1)."""
    if len(a) < n + 1 or len(b) < n + 1 or len(a) != len(b):
        return None
    ra, rb = lokituotot(a[-(n + 1):]), lokituotot(b[-(n + 1):])
    if statistics.pstdev(ra) == 0 or statistics.pstdev(rb) == 0:
        return None
    ka, kb = statistics.fmean(ra), statistics.fmean(rb)
    cov = sum((x - ka) * (y - kb) for x, y in zip(ra, rb))
    return cov / math.sqrt(sum((x - ka) ** 2 for x in ra) * sum((y - kb) ** 2 for y in rb))


def funding_vuosituotto(rivit, raja_ms, n_pv):
    """rivit: (ts, interval_h, rate). Ikkuna [raja - n_pv paivaa, raja). Vuosiperusteinen: summa/n_pv*365."""
    alku = raja_ms - n_pv * PV
    valit = [r for ts, _, r in rivit if alku <= ts < raja_ms]
    if not valit:
        return None
    return sum(valit) / n_pv * 365


def mediaani(arvot):
    a = [x for x in arvot if x is not None]
    return statistics.median(a) if a else None
