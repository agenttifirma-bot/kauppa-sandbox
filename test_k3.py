import json
import unittest
from datetime import date, datetime, timedelta, timezone

import db
import kirjanpito
import mittarit
import rajat
import riskivahti
import salkku

PV = 86400000
ALKU = date(2026, 1, 1)


def ms(p):
    return int(datetime(p.year, p.month, p.day, tzinfo=timezone.utc).timestamp() * 1000)


def markkina(hinnat):
    """hinnat: {symbol: [(open, close), ...]} alkaen ALKU:sta."""
    con = db.avaa(":memory:")
    for s, lista in hinnat.items():
        db.lisaa_hinnat(con, s, [(ms(ALKU + timedelta(days=i)), o, max(o, c) * 1.01, min(o, c) * 0.99, c, 1, 1, 1)
                                 for i, (o, c) in enumerate(lista)])
    return con


S = {"BTCUSDT", "ETHUSDT", "SOLUSDT"}


class RiskivahtiTesti(unittest.TestCase):
    def test_rajaa_positio_ja_skaalaa_summa(self):
        p, h = riskivahti.siisti_ehdotus({"BTCUSDT": 0.5, "ETHUSDT": 0.15, "SOLUSDT": 0.15}, S)
        self.assertTrue(all(w <= rajat.MAX_POSITIO + 1e-12 for w in p.values()))
        self.assertLessEqual(sum(p.values()), 1 - rajat.KATEISPUSKURI_MIN + 1e-12)
        self.assertTrue(h)

    def test_hylkaa_virheelliset(self):
        for huono in ({"XRPUSDT": 0.1}, {"BTCUSDT": -0.1}, {"BTCUSDT": float("nan")},
                      {"BTCUSDT": True}, {"BTCUSDT": "0.1"}, [("BTCUSDT", 0.1)], None):
            with self.assertRaises(riskivahti.Ehdotusvirhe):
                riskivahti.siisti_ehdotus(huono, S)

    def test_jarru_ja_paivatappio(self):
        j, t, dd = riskivahti.tila([100, 120, 88], False)       # raja 25 %
        self.assertTrue(j)
        self.assertAlmostEqual(dd, 1 - 88 / 120)
        self.assertFalse(riskivahti.tila([100, 120, 95], False)[0])  # 20,8 % ei vielä jarruta
        j, t, _ = riskivahti.tila([100, 94], False)
        self.assertFalse(j)
        self.assertTrue(t)
        self.assertTrue(riskivahti.tila([100, 100], True)[0])  # lukko pysyy


class SalkkuTesti(unittest.TestCase):
    def aja(self, mk, ehdotukset, alku=1000000.0):
        con = salkku.avaa(":memory:", alkupaoma=10000.0)
        tulokset = []
        for i, e in enumerate(ehdotukset):
            tulokset.append(salkku.suorita_paiva(con, mk, ALKU + timedelta(days=i), e, S))
        return con, tulokset

    def test_osto_kulut_ja_kirjanpitoidentiteetti(self):
        mk = markkina({"BTCUSDT": [(100, 100)] * 3})
        con, t = self.aja(mk, [{"BTCUSDT": 0.10}])
        k = t[0]["kaupat"]
        self.assertEqual(len(k), 1)
        _, s, puoli, q, hinta, kulu, slip = k[0]
        self.assertEqual(puoli, "BUY")
        self.assertAlmostEqual(hinta, 100 * (1 + rajat.SLIPPAGE))
        self.assertAlmostEqual(q * hinta + kulu, 1000.0, places=6)  # kulutus = 10 % salkusta
        # arvo avaushinnoilla = alkuarvo - kulu - slippage-kulu
        arvo = salkku.kateinen(con) + q * 100
        self.assertAlmostEqual(arvo, 10000 - kulu - slip, places=6)

    def test_ei_negatiivista_kassaa_ja_puskuri(self):
        mk = markkina({s: [(100, 100)] * 3 for s in S})
        con, t = self.aja(mk, [{"BTCUSDT": 0.15, "ETHUSDT": 0.15, "SOLUSDT": 0.15}])
        self.assertGreaterEqual(salkku.kateinen(con), rajat.KATEISPUSKURI_MIN * 10000 - 1e-6)

    def test_myynti_ennen_ostoa_ja_ei_enaa_mainittu_myydaan(self):
        mk = markkina({"BTCUSDT": [(100, 100)] * 4, "ETHUSDT": [(100, 100)] * 4})
        con, t = self.aja(mk, [{"BTCUSDT": 0.15}, {"ETHUSDT": 0.15}])
        puolet = [k[2] for k in t[1]["kaupat"]]
        self.assertEqual(puolet, ["SELL", "BUY"])
        self.assertNotIn("BTCUSDT", salkku.positiot(con))

    def test_virheellinen_ehdotus_ei_kauppoja(self):
        mk = markkina({"BTCUSDT": [(100, 100)] * 3})
        con, t = self.aja(mk, [{"BTCUSDT": 0.1}, {"DOGEUSDT": 0.5}])
        self.assertEqual(t[1]["kaupat"], [])
        self.assertIn("BTCUSDT", salkku.positiot(con))  # vanha positio sailyy

    def test_hatajarru_myy_kaiken_ja_lukitsee(self):
        # BTC kaatuu -40 % omistuksen ollessa 15 % => salkku -6 %, ei vielä jarrua; tehdaan useampi kolikko
        mk = markkina({s: [(100, 100), (100, 50), (50, 50), (50, 50), (50, 50)] for s in S})
        eh = {"BTCUSDT": 0.15, "ETHUSDT": 0.15, "SOLUSDT": 0.15}
        con, t = self.aja(mk, [eh] * 1)
        # pakotetaan syvempi pudotus: pienenna arvoa suoraan historiassa
        con.execute("INSERT INTO arvot VALUES ('2025-12-31', 20000, 20000, 0)")
        con.commit()
        # uusi paiva: drawdown (suhteessa huippuun 20000) >= 20 % => hatajarru
        r = salkku.suorita_paiva(con, mk, ALKU + timedelta(days=1), eh, S)
        self.assertTrue(r["jarru"])
        self.assertTrue(all(k[2] == "SELL" for k in r["kaupat"]))
        self.assertEqual(salkku.positiot(con), {})
        r2 = salkku.suorita_paiva(con, mk, ALKU + timedelta(days=2), eh, S)
        self.assertEqual(r2["kaupat"], [])  # lukko: ei osteta vaikka ehdotus
        salkku.nollaa_jarru(con)
        # nollauksen jalkeen drawdown yha yli rajan => jarru laukeaa uudelleen (huippu sailyy)
        r3 = salkku.suorita_paiva(con, mk, ALKU + timedelta(days=3), eh, S)
        self.assertTrue(r3["jarru"])

    def test_paivatappion_jalkeen_ei_osteta(self):
        mk = markkina({s: [(100, 100), (100, 100), (100, 100)] for s in S})
        con = salkku.avaa(":memory:", alkupaoma=10000.0)
        con.execute("INSERT INTO arvot VALUES ('2025-12-30', 10000, 10000, 0)")
        con.execute("INSERT INTO arvot VALUES ('2025-12-31', 9400, 9400, 0)")  # -6 %
        con.commit()
        r = salkku.suorita_paiva(con, mk, ALKU, {"BTCUSDT": 0.1}, S)
        self.assertEqual(r["kaupat"], [])

    def test_kaksi_ajoa_samalle_paivalle_estetty(self):
        mk = markkina({"BTCUSDT": [(100, 100)] * 3})
        con, _ = self.aja(mk, [{"BTCUSDT": 0.1}])
        with self.assertRaises(salkku.Datavirhe):
            salkku.suorita_paiva(con, mk, ALKU, {"BTCUSDT": 0.1}, S)

    def test_puuttuva_hinta_omistetulle_keskeyttaa(self):
        mk = markkina({"BTCUSDT": [(100, 100)] * 1})  # vain paiva 1
        con = salkku.avaa(":memory:")
        salkku.suorita_paiva(con, mk, ALKU, {"BTCUSDT": 0.1}, S)
        with self.assertRaises(salkku.Datavirhe):
            salkku.suorita_paiva(con, mk, ALKU + timedelta(days=1), {"BTCUSDT": 0.1}, S)

    def test_kauppamaaran_katto(self):
        mk = markkina({s: [(100, 100)] * 3 for s in ("BTCUSDT", "ETHUSDT", "SOLUSDT")})
        raja, rajat.MAX_KAUPPOJA_PAIVA = rajat.MAX_KAUPPOJA_PAIVA, 2
        try:
            con, t = self.aja(mk, [{"BTCUSDT": 0.1, "ETHUSDT": 0.1, "SOLUSDT": 0.1}])
        finally:
            rajat.MAX_KAUPPOJA_PAIVA = raja
        self.assertEqual(len(t[0]["kaupat"]), 2)


class KirjanpitoTesti(unittest.TestCase):
    def test_fifo(self):
        kaupat = [("2026-01-01", "BTCUSDT", "BUY", 1.0, 100.0, 1.0),
                  ("2026-01-02", "BTCUSDT", "BUY", 1.0, 200.0, 2.0),
                  ("2026-01-03", "BTCUSDT", "SELL", 1.5, 300.0, 4.5)]
        r = kirjanpito.fifo(kaupat)
        self.assertEqual(len(r), 1)
        _, _, q, tulo, meno, voitto = r[0]
        self.assertAlmostEqual(meno, 101.0 + 0.5 * 202.0)  # koko 1. era + puolet 2. erasta
        self.assertAlmostEqual(tulo, 450.0 - 4.5)
        self.assertAlmostEqual(voitto, tulo - meno)
        self.assertEqual(kirjanpito.vuosiyhteenveto(r), {"2026": voitto})

    def test_myynti_yli_omistuksen(self):
        with self.assertRaises(ValueError):
            kirjanpito.fifo([("2026-01-01", "BTCUSDT", "SELL", 1.0, 100.0, 0.0)])

    def test_salkun_kaupat_fifo_toimii(self):
        mk = markkina({"BTCUSDT": [(100, 100), (110, 110), (120, 120)]})
        con = salkku.avaa(":memory:")
        salkku.suorita_paiva(con, mk, ALKU, {"BTCUSDT": 0.15}, S)
        salkku.suorita_paiva(con, mk, ALKU + timedelta(days=1), {}, S)
        rivit = con.execute("SELECT paiva,symbol,puoli,maara,hinta,kulu FROM kaupat ORDER BY id").fetchall()
        r = kirjanpito.fifo(rivit)
        self.assertEqual(len(r), 1)
        self.assertGreater(r[0][5], -50)  # voitto/tappio jarkeva


class MittaritTesti(unittest.TestCase):
    def test_mittarit(self):
        m = mittarit.mittarit([100, 110, 99, 120])
        self.assertAlmostEqual(m["tuotto"], 0.2)
        self.assertAlmostEqual(m["max_dd"], 0.1)
        self.assertIsNone(mittarit.mittarit([100, 101]))

    def test_vertailusalkku_ostaa_ja_pitaa(self):
        mk = markkina({"BTCUSDT": [(100, 100), (100, 110), (110, 120)]})
        v = mittarit.vertailusalkku(mk, {"BTCUSDT": 0.5}, ALKU, ALKU + timedelta(days=2))
        self.assertEqual(len(v), 3)
        self.assertLess(v[0][1], 10000)  # kulut vahentavat heti
        self.assertGreater(v[2][1], v[0][1])


if __name__ == "__main__":
    unittest.main()
