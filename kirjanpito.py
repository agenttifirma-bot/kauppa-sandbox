"""FIFO-kirjanpito simuloiduista kaupoista (USDT-pohjainen; verotus myohemmin EUR:ssa)."""
from collections import defaultdict, deque


def fifo(kaupat):
    """kaupat: (paiva, symbol, puoli, maara, hinta, kulu) aikajarjestyksessa.
    Palauttaa [(paiva, symbol, maara, tulo_netto, hankintameno, voitto)]. Hankintameno sisaltaa osto-kulut,
    tulo on myyntikulujen jalkeen. Myynti yli omistuksen = virhe."""
    erat = defaultdict(deque)
    ulos = []
    for paiva, s, puoli, maara, hinta, kulu in kaupat:
        if puoli == "BUY":
            erat[s].append([maara, (maara * hinta + kulu) / maara])
        elif puoli == "SELL":
            jaljella = maara
            meno = 0.0
            while jaljella > 1e-12:
                if not erat[s]:
                    raise ValueError("myynti yli omistuksen: %s %s" % (s, paiva))
                era = erat[s][0]
                ota = min(era[0], jaljella)
                meno += ota * era[1]
                era[0] -= ota
                jaljella -= ota
                if era[0] <= 1e-12:
                    erat[s].popleft()
            tulo = maara * hinta - kulu
            ulos.append((paiva, s, maara, tulo, meno, tulo - meno))
        else:
            raise ValueError("tuntematon puoli")
    return ulos


def vuosiyhteenveto(realisoinnit):
    v = defaultdict(float)
    for paiva, *_, voitto in realisoinnit:
        v[paiva[:4]] += voitto
    return dict(v)
