"""Point-in-time -universumi: paivan D universumi lasketaan VAIN dataa ennen D (ts < D).
Valitaan config.SYMBOLIT-listan kolikoista n suurinta viimeisen ikkuna-paivan quote-volyymin mukaan;
kolikolla pitaa olla taysi kattavuus ikkunassa (ei aukkoja, ei vanhentumista)."""
import config

PV = 86400000


def universumi(con, paiva_ms, n=20, ikkuna=30, symbolit=None):
    alku = paiva_ms - ikkuna * PV
    tulos = []
    for s in (symbolit or config.SYMBOLIT):
        vol, lkm = con.execute(
            "SELECT COALESCE(SUM(quote_volume),0), COUNT(*) FROM hinnat WHERE symbol=? AND ts>=? AND ts<?",
            (s, alku, paiva_ms),
        ).fetchone()
        if lkm == ikkuna:
            tulos.append((s, vol))
    tulos.sort(key=lambda x: (-x[1], x[0]))
    return tulos[:n]
