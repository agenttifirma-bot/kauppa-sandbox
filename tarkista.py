"""Datan laatutarkistus. Palauttaa 1 jos spot-datassa on aukkoja/vanhentumista (fail closed)."""
import sys
from datetime import datetime, timedelta, timezone

import config
import db

PV = 86400000


def raportti(con, tanaan):
    ongelmat, huomiot, rivit = [], [], []
    for s in config.SYMBOLIT:
        r = con.execute("SELECT MIN(ts), MAX(ts), COUNT(*) FROM hinnat WHERE symbol=?", (s,)).fetchone()
        if not r[2]:
            ongelmat.append("%s: ei hintadataa" % s)
            continue
        ensin, viimeksi, n = r
        odotettu = (viimeksi - ensin) // PV + 1
        if n != odotettu:
            ts = {x[0] for x in con.execute("SELECT ts FROM hinnat WHERE symbol=?", (s,))}
            puuttuu = [ensin + i * PV for i in range(odotettu) if ensin + i * PV not in ts]
            esim = ", ".join(datetime.fromtimestamp(t / 1000, timezone.utc).date().isoformat() for t in puuttuu[:5])
            ongelmat.append("%s: %d paivaa puuttuu (esim. %s)" % (s, len(puuttuu), esim))
        vanhin_sallittu = datetime.combine(tanaan - timedelta(days=config.VANHENTUNUT_PV), datetime.min.time(), timezone.utc)
        if viimeksi < int(vanhin_sallittu.timestamp() * 1000):
            ongelmat.append("%s: data vanhentunut (viimeisin %s)" % (s, datetime.fromtimestamp(viimeksi / 1000, timezone.utc).date()))
        f = con.execute("SELECT MAX(ts), COUNT(*) FROM funding WHERE symbol=?", (s,)).fetchone()
        if not f[1]:
            huomiot.append("%s: ei funding-dataa" % s)
        elif f[0] < int(vanhin_sallittu.timestamp() * 1000):
            huomiot.append("%s: funding vanhentunut" % s)
        rivit.append("%-10s %s .. %s  paivia %4d  funding %5d" % (
            s,
            datetime.fromtimestamp(ensin / 1000, timezone.utc).date(),
            datetime.fromtimestamp(viimeksi / 1000, timezone.utc).date(),
            n, f[1]))
    return ongelmat, huomiot, rivit


def main():
    con = db.avaa(config.DB_POLKU)
    tanaan = datetime.now(timezone.utc).date()
    ongelmat, huomiot, rivit = raportti(con, tanaan)
    print("\n".join(rivit))
    for h in huomiot:
        print("HUOM", h)
    for o in ongelmat:
        print("ONGELMA", o)
    print("TULOS:", "ONGELMIA %d" % len(ongelmat) if ongelmat else "OK")
    return 1 if ongelmat else 0


if __name__ == "__main__":
    sys.exit(main())
