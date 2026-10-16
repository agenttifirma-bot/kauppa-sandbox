import math
import random
import unittest
from datetime import date, datetime, timezone

import db
import indikaattorit as ind
import taulukko
import universumi as uni

PV = 86400000
D = date(2026, 6, 1)
D_MS = taulukko.paiva_ms(D)


def luo_kanta(symbolit, paivia=120, loppu_ms=None, volyymit=None, seed=1):
    """Tekopriisi: paivat [loppu-paivia, loppu) paivakynttilat; loppu oletuksena D."""
    con = db.avaa(":memory:")
    loppu_ms = loppu_ms or D_MS
    rnd = random.Random(seed)
    for s in symbolit:
        h = 100.0
        rivit = []
        for i in range(paivia):
            ts = loppu_ms - (paivia - i) * PV
            h *= math.exp(rnd.gauss(0.001, 0.03))
            rivit.append((ts, h, h * 1.02, h * 0.98, h, 10.0, (volyymit or {}).get(s, 1000.0) * (1 + 0.01 * i), 5))
        db.lisaa_hinnat(con, s, rivit)
        db.lisaa_funding(con, s, [(loppu_ms - k * 8 * 3600000, 8.0, 0.0001) for k in range(1, 100)])
    return con


class IndikaattoriTesti(unittest.TestCase):
    def test_tuotto(self):
        self.assertAlmostEqual(ind.tuotto([100, 110, 121], 1), 0.1)
        self.assertAlmostEqual(ind.tuotto([100, 110, 121], 2), 0.21)
        self.assertIsNone(ind.tuotto([100, 110], 2))

    def test_volatiliteetti_vakiokasvu_nolla(self):
        s = [100 * 1.01 ** i for i in range(40)]
        self.assertAlmostEqual(ind.volatiliteetti(s, 30), 0.0, places=9)
        self.assertIsNone(ind.volatiliteetti(s[:10], 30))

    def test_pudotus(self):
        self.assertAlmostEqual(ind.pudotus_huipusta([100, 200, 150], 3), -0.25)

    def test_korrelaatio(self):
        rnd = random.Random(3)
        a = [100.0]
        for _ in range(70):
            a.append(a[-1] * math.exp(rnd.gauss(0, 0.02)))
        self.assertAlmostEqual(ind.korrelaatio(a, a, 60), 1.0, places=9)
        inv = [10000.0 / x for x in a]
        self.assertAlmostEqual(ind.korrelaatio(a, inv, 60), -1.0, places=9)
        self.assertIsNone(ind.korrelaatio([1.0] * 70, a, 60))

    def test_funding_vuosituotto(self):
        rivit = [(D_MS - k * 8 * 3600000, 8.0, 0.0001) for k in range(1, 22)]  # 7 paivaa x 3
        self.assertAlmostEqual(ind.funding_vuosituotto(rivit, D_MS, 7), 0.0003 * 365, places=9)
        self.assertIsNone(ind.funding_vuosituotto([], D_MS, 7))


class UniversumiTesti(unittest.TestCase):
    def test_volyymijarjestys_ja_pituus(self):
        con = luo_kanta(["AUSDT", "BUSDT", "CUSDT"], volyymit={"AUSDT": 10, "BUSDT": 50, "CUSDT": 30})
        u = uni.universumi(con, D_MS, n=2, symbolit=["AUSDT", "BUSDT", "CUSDT"])
        self.assertEqual([s for s, _ in u], ["BUSDT", "CUSDT"])

    def test_liian_lyhyt_historia_pois(self):
        con = luo_kanta(["AUSDT"], paivia=120)
        con2 = luo_kanta(["BUSDT"], paivia=10)
        for r in con2.execute("SELECT * FROM hinnat").fetchall():
            con.execute("INSERT INTO hinnat VALUES (?,?,?,?,?,?,?,?,?)", r)
        u = uni.universumi(con, D_MS, symbolit=["AUSDT", "BUSDT"])
        self.assertEqual([s for s, _ in u], ["AUSDT"])

    def test_vanhentunut_kolikko_pois(self):
        con = luo_kanta(["AUSDT"], loppu_ms=D_MS - 3 * PV)  # data loppuu 3 pv liian aikaisin
        self.assertEqual(uni.universumi(con, D_MS, symbolit=["AUSDT"]), [])


class TaulukkoTesti(unittest.TestCase):
    S = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]

    def test_ei_tulevaisuutta(self):
        con = luo_kanta(self.S, paivia=140)
        teksti1, _ = taulukko.rakenna(con, D)
        # lisaa ja muuta dataa hetkesta D alkaen: tulos ei saa muuttua
        for s in self.S:
            db.lisaa_hinnat(con, s, [(D_MS + i * PV, 1.0, 2.0, 0.5, 1.5, 1, 99999999.0, 1) for i in range(0, 5)])
            con.execute("UPDATE hinnat SET close=999 WHERE symbol=? AND ts>=?", (s, D_MS))
            con.execute("DELETE FROM funding WHERE symbol=? AND ts>=?", (s, D_MS))
            db.lisaa_funding(con, s, [(D_MS + 1000, 8.0, 0.05)])
        con.commit()
        teksti2, _ = taulukko.rakenna(con, D)
        self.assertEqual(teksti1, teksti2)

    def test_sisalto_ja_ranki(self):
        con = luo_kanta(self.S, paivia=140)
        teksti, t = taulukko.rakenna(con, D)
        self.assertIn('<data paiva="2026-06-01"', teksti)
        self.assertIn("viimeisin_suljettu=\"2026-05-31\"", teksti)
        self.assertEqual(sorted(t.keys()), sorted(self.S))
        rankit = sorted(int(l.split(" | ")[-1]) for l in teksti.splitlines() if l.startswith(("BTC", "ETH", "SOL")))
        self.assertEqual(rankit, [1, 2, 3])
        self.assertAlmostEqual(t["BTCUSDT"]["corr"], 1.0, places=6)  # BTC itseensa

    def test_aukko_antaa_na(self):
        con = luo_kanta(self.S, paivia=140)
        con.execute("DELETE FROM hinnat WHERE symbol='SOLUSDT' AND ts=?", (D_MS - 50 * PV,))
        con.commit()
        teksti, t = taulukko.rakenna(con, D)
        self.assertIsNone(t["SOLUSDT"]["r90"])   # aukko 91 paivan ikkunassa
        self.assertIsNotNone(t["SOLUSDT"]["r30"])  # lyhyempi ikkuna ehja
        sol = [l for l in teksti.splitlines() if l.startswith("SOLUSDT")][0]
        self.assertTrue(sol.endswith("n/a"))

    def test_toistettavuus(self):
        con = luo_kanta(self.S, paivia=140)
        self.assertEqual(taulukko.rakenna(con, D)[0], taulukko.rakenna(con, D)[0])


if __name__ == "__main__":
    unittest.main()
