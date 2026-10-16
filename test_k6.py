import math
import random
import time
import unittest
from datetime import date, timedelta

import backtest as bt
import db
import rajat
import test_k2
from test_k2 import luo_kanta

SYMBOLIT = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "ADAUSDT", "XRPUSDT", "LINKUSDT", "DOGEUSDT", "AVAXUSDT"]
LOPPU = date(2026, 6, 1)


def kanta(paivia=700, seed=3):
    # luo_kanta: paivat [loppu-paivia, loppu), loppu = test_k2.D_MS
    return luo_kanta(SYMBOLIT, paivia=paivia, seed=seed)


class DataTesti(unittest.TestCase):
    def test_sulut_ei_palauta_tulevaisuutta(self):
        con = kanta(200)
        d = bt.Data(con, n_universumi=8)
        d_ms = bt._ms(date(2026, 4, 1))
        c = d.sulut("BTCUSDT", d_ms, 30)
        self.assertEqual(len(c), 30)
        self.assertEqual(c[-1], d.close["BTCUSDT"][d_ms - 86400000])  # viimeinen = edellisen paivan sulku

    def test_sulut_aukko_palauttaa_none(self):
        con = kanta(200)
        d = bt.Data(con, n_universumi=8)
        d_ms = bt._ms(date(2026, 4, 1))
        del d.close["BTCUSDT"][d_ms - 5 * 86400000]
        self.assertIsNone(d.sulut("BTCUSDT", d_ms, 30))


class AjoTesti(unittest.TestCase):
    def test_deterministinen(self):
        con = kanta(300)
        d = bt.Data(con, 8)
        a, b = date(2026, 1, 1), date(2026, 3, 1)
        r1 = bt.aja(bt.momentum(30, 3, 0.8, 7), d, a, b)
        r2 = bt.aja(bt.momentum(30, 3, 0.8, 7), d, a, b)
        self.assertEqual(r1["arvot"], r2["arvot"])
        self.assertEqual(len(r1["arvot"]), (b - a).days + 2)

    def test_ei_katso_tulevaisuuteen(self):
        """Muutetaan hintoja T:n jalkeen: tulos T:hen asti ei saa muuttua."""
        T = date(2026, 3, 1)
        con1 = kanta(300, seed=5)
        con2 = kanta(300, seed=5)
        T_ms = bt._ms(T)
        rnd = random.Random(9)
        for s in SYMBOLIT:
            for (ts, c) in con2.execute("SELECT ts, close FROM hinnat WHERE symbol=? AND ts>?", (s, T_ms)).fetchall():
                f = rnd.uniform(0.2, 5.0)
                con2.execute("UPDATE hinnat SET close=?, open=?, high=?, low=? WHERE symbol=? AND ts=?",
                             (c * f, c * f, c * f * 1.01, c * f * 0.99, s, ts))
        a = date(2026, 1, 10)
        r1 = bt.aja(bt.momentum(30, 3, 0.8, 7), bt.Data(con1, 8), a, T)
        r2 = bt.aja(bt.momentum(30, 3, 0.8, 7), bt.Data(con2, 8), a, T)
        self.assertEqual(r1["arvot"], r2["arvot"])

    def test_riskirajat_voimassa(self):
        con = kanta(300)
        d = bt.Data(con, 8)
        # yritetaan 100 % yhteen kolikkoon: riskivahti leikkaa
        def tehdas():
            return lambda data, p, sall: {"BTCUSDT": 1.0}
        sal = bt.salkku.avaa(":memory:")
        bt.salkku.suorita_paiva(sal, con, date(2026, 2, 1), {"BTCUSDT": 1.0}, set(SYMBOLIT))
        arvo, kassa = sal.execute("SELECT arvo, kateinen FROM arvot").fetchone()
        self.assertLess((arvo - kassa) / arvo, rajat.MAX_POSITIO + 0.01)

    def test_aika_hyvaksyttava(self):
        con = kanta(700)
        d = bt.Data(con, 8)
        t = time.time()
        bt.aja(bt.momentum(60, 5, 0.8, 7), d, date(2025, 6, 1), date(2026, 4, 10))
        self.assertLess(time.time() - t, 20)


class RekisteriTesti(unittest.TestCase):
    def test_kirjaa_ja_laskee(self):
        con = kanta(300)
        d = bt.Data(con, 8)
        rek = bt.avaa_rekisteri(":memory:")
        bt.aja(bt.momentum(30, 3, 0.8, 7), d, date(2026, 1, 1), date(2026, 2, 1), rek, "mom", {"ikkuna": 30}, "kehitys")
        bt.aja(bt.tasapaino(), d, date(2026, 1, 1), date(2026, 2, 1), rek, "ew", {}, "kehitys")
        self.assertEqual(bt.kokeiluja(rek), 2)
        self.assertEqual(bt.kokeiluja(rek, "mom"), 1)


class HoldoutTesti(unittest.TestCase):
    def test_aja_kieltaytyy_holdoutista(self):
        con = kanta(300)
        d = bt.Data(con, 8)
        with self.assertRaises(bt.Holdoutvirhe):
            bt.aja(bt.tasapaino(), d, date(2026, 3, 1), date(2026, 5, 1))

    def test_holdout_vain_kerran(self):
        con = kanta(300)
        d = bt.Data(con, 8)
        rek = bt.avaa_rekisteri(":memory:")
        r = bt.holdout_arvioi(bt.tasapaino(), d, rek, "x", {})
        self.assertIsNotNone(r["mittarit"])
        with self.assertRaises(bt.Holdoutvirhe):
            bt.holdout_arvioi(bt.tasapaino(), d, rek, "x", {})
        # eri nimi sallittu, mutta kirjautuu
        bt.holdout_arvioi(bt.tasapaino(), d, rek, "y", {})
        self.assertEqual(rek.execute("SELECT COUNT(*) FROM holdout_kaytto").fetchone()[0], 2)


class WalkForwardTesti(unittest.TestCase):
    def test_ikkunat_eivat_vuoda(self):
        ik = bt.ikkunat(date(2024, 1, 1), date(2025, 12, 31), 365, 90)
        self.assertGreater(len(ik), 3)
        for (a, b, c, d) in ik:
            self.assertLess(b, c)
            self.assertEqual(c, b + timedelta(days=1))
        for i in range(1, len(ik)):
            self.assertEqual(ik[i][2], ik[i - 1][3] + timedelta(days=1))  # testit perakkain, ei paallekkain

    def test_walk_forward_ja_arvio(self):
        con = kanta(600)
        d = bt.Data(con, 8)
        rek = bt.avaa_rekisteri(":memory:")
        ruudukko = [{"ikkuna": 30, "k": 3, "reb": 7}, {"ikkuna": 60, "k": 5, "reb": 14}]
        wf = bt.walk_forward("mom", lambda **p: bt.momentum(**p), ruudukko, d, rek,
                             alku=date(2025, 1, 1), loppu=date(2026, 4, 10), train_pv=200, testi_pv=60)
        self.assertGreaterEqual(len(wf["foldit"]), 2)
        self.assertIsNotNone(wf["mittarit"])
        # kokeilut kirjattu: jokaisessa foldissa len(ruudukko) train-ajoa + 1 oos
        self.assertEqual(bt.kokeiluja(rek), len(wf["foldit"]) * (len(ruudukko) + 1))
        sat = bt.satunnaisjakauma(d, wf["ikkunat"], 5)
        btc = bt.btc_vertailu(d, wf["ikkunat"])
        a = bt.arvio(wf, sat, btc, len(ruudukko))
        self.assertTrue(0 < a["p_satunnainen"] <= 1)
        self.assertGreaterEqual(a["p_korjattu"], a["p_satunnainen"])
        self.assertIn("TULOS:", bt.teksti("mom", a, bt.kokeiluja(rek)))

    def test_walk_forward_kieltaytyy_holdoutista(self):
        con = kanta(300)
        d = bt.Data(con, 8)
        with self.assertRaises(bt.Holdoutvirhe):
            bt.walk_forward("x", lambda **p: bt.tasapaino(), [{}], d, bt.avaa_rekisteri(":memory:"),
                            alku=date(2025, 6, 1), loppu=date(2026, 5, 1))


class PArvoTesti(unittest.TestCase):
    def test_p_arvo(self):
        sat = [{"sharpe_pa": x} for x in (0.1, 0.2, 0.3, 0.4)]
        self.assertAlmostEqual(bt.p_arvo(5.0, sat), 1 / 5)
        self.assertAlmostEqual(bt.p_arvo(0.0, sat), 1.0)
        self.assertEqual(bt.p_arvo(None, sat), 1.0)

    def test_ei_kelpaa_jos_yksikin_ehto_pettaa(self):
        a = {"oos_tuotto": 0.5, "oos_sharpe": 2.0, "oos_max_dd": 0.1, "btc_tuotto": 0.6, "btc_sharpe": 1.0,
             "p_satunnainen": 0.001, "p_korjattu": 0.01, "voittaa_satunnaiset": True,
             "voittaa_btc_tuotto": False, "voittaa_btc_sharpe": True, "satunnaisia": 500, "riittavasti_satunnaisia": True}
        self.assertIn("EI KELPAA", bt.teksti("x", a, 10))

    def test_liian_vahan_satunnaisia_ei_kelpaa(self):
        a = {"oos_tuotto": 0.5, "oos_sharpe": 2.0, "oos_max_dd": 0.1, "btc_tuotto": 0.1, "btc_sharpe": 1.0,
             "p_satunnainen": 0.02, "p_korjattu": 0.02, "voittaa_satunnaiset": True,
             "voittaa_btc_tuotto": True, "voittaa_btc_sharpe": True, "satunnaisia": 10, "riittavasti_satunnaisia": False}
        self.assertIn("EI KELPAA", bt.teksti("x", a, 10))
        sat = [{"sharpe_pa": 0.1}] * 10
        wf = {"mittarit": {"sharpe_pa": 5.0, "tuotto": 1.0, "max_dd": 0.1}}
        btc = {"mittarit": {"sharpe_pa": 0.1, "tuotto": 0.1}}
        self.assertFalse(bt.arvio(wf, sat, btc, 12)["riittavasti_satunnaisia"])


if __name__ == "__main__":
    unittest.main()
