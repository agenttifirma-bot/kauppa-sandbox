import json
import os
import tempfile
import unittest
from datetime import date, datetime, timezone
from unittest import mock

import backtest as bt
import config
import db
import historia_lataus as hl
import k7
import laaja
import lahde
import rajat
import salkku
from test_k1 import kuukausi_zip, zipita, kline
from test_k7 import spec_dict

PV = 86400000
T0 = int(datetime(2021, 10, 1, tzinfo=timezone.utc).timestamp() * 1000)


def sarja(paivia, alku_idx=0, hinta=100.0, vol=1000.0, kasvu=0.0):
    """{ts: (open, close, qv)} paivaindeksit alku_idx..alku_idx+paivia-1"""
    return {T0 + i * PV: (hinta * (1 + kasvu) ** (i - alku_idx), hinta * (1 + kasvu) ** (i - alku_idx + 1), vol)
            for i in range(alku_idx, alku_idx + paivia)}


def syotteet(kartta):
    close = {s: {ts: v[1] for ts, v in d.items()} for s, d in kartta.items()}
    open_ = {s: {ts: v[0] for ts, v in d.items()} for s, d in kartta.items()}
    qv = {s: {ts: v[2] for ts, v in d.items()} for s, d in kartta.items()}
    return close, open_, qv


def pohja():
    # A,C,D elossa koko ajan; B kuolee paivana 600 (viimeinen paiva 599); datan loppu paiva 999
    return {
        "AUSDT": sarja(1000, vol=900.0),
        "BUSDT": sarja(600, vol=5000.0),       # suurin volyymi -> universumissa kunnes kuolee
        "CUSDT": sarja(1000, vol=800.0),
        "DUSDT": sarja(1000, vol=700.0),
        "BTCUSDT": sarja(1000, vol=2000.0),
    }


class Nimimuutos(unittest.TestCase):
    def test_yhdistaa_kun_hinta_jatkuu(self):
        k = {"OLDUSDT": sarja(100, 0, hinta=10.0), "NEWUSDT": sarja(100, 100, hinta=10.5)}
        c, o, q = syotteet(k)
        r = laaja.yhdista_nimimuutokset(c, o, q, {"OLDUSDT": "NEWUSDT"})
        self.assertNotIn("OLDUSDT", c)
        self.assertEqual(len(c["NEWUSDT"]), 200)
        self.assertTrue(r[0].startswith("yhdistetty"))

    def test_ei_yhdista_jos_hinta_hyppaa(self):
        k = {"OLDUSDT": sarja(100, 0, hinta=10.0), "NEWUSDT": sarja(100, 100, hinta=100.0)}
        c, o, q = syotteet(k)
        r = laaja.yhdista_nimimuutokset(c, o, q, {"OLDUSDT": "NEWUSDT"})
        self.assertIn("OLDUSDT", c)
        self.assertEqual(len(c["NEWUSDT"]), 100)
        self.assertIn("EI yhdistetty", r[0])

    def test_ei_yhdista_jos_ajat_eivat_jatku(self):
        k = {"OLDUSDT": sarja(50, 0), "NEWUSDT": sarja(50, 300)}
        c, o, q = syotteet(k)
        r = laaja.yhdista_nimimuutokset(c, o, q, {"OLDUSDT": "NEWUSDT"})
        self.assertIn("EI yhdistetty", r[0])


class Universumit(unittest.TestCase):
    def data(self, tila, haircut=0.1, n=3):
        return laaja.LaajaData(tila=tila, n=n, haircut=haircut, lista=["AUSDT", "CUSDT"], rename={}, _syotteet=syotteet(pohja()))

    def test_kuollut_tunnistetaan(self):
        self.assertEqual(self.data("kaikki").kuollut, {"BUSDT"})

    def test_kaikki_sisaltaa_kuolleen_kunnes_data_loppuu(self):
        d = self.data("kaikki")
        self.assertIn("BUSDT", d.universum(T0 + 599 * PV))
        self.assertNotIn("BUSDT", d.universum(T0 + 600 * PV))   # viimeisen paivan jalkeen pois -> omistus myydaan
        self.assertNotIn("BUSDT", d.universum(T0 + 700 * PV))

    def test_elossa_ei_sisalla_kuollutta(self):
        d = self.data("elossa")
        self.assertNotIn("BUSDT", d.symbolit)
        self.assertNotIn("BUSDT", d.universum(T0 + 300 * PV))

    def test_vanha_vain_listan_kolikot(self):
        self.assertEqual(self.data("vanha").symbolit, ["AUSDT", "CUSDT"])

    def test_universumi_point_in_time(self):
        d = self.data("kaikki")
        self.assertEqual(d.universum(T0 + 10 * PV), [])           # ikkuna ei taysi vielakaan
        self.assertEqual(d.universum(T0 + 31 * PV)[0], "BUSDT")    # suurin volyymi ensin

    def test_synteettinen_delistaushinta(self):
        d = self.data("kaikki", haircut=0.3)
        viim_sulku = d.close["BUSDT"][T0 + 599 * PV]
        r = d.con.execute("SELECT open, close FROM hinnat WHERE symbol='BUSDT' AND ts=?", (T0 + 600 * PV,)).fetchone()
        self.assertAlmostEqual(r[0], viim_sulku * 0.7, places=6)
        self.assertNotIn(T0 + 600 * PV, d.close["BUSDT"])          # strategia ei nae synteettista hintaa

    def test_tuntematon_tila(self):
        with self.assertRaises(ValueError):
            laaja.LaajaData(tila="muu", _syotteet=syotteet(pohja()))


def aina_b(osuus=0.15):
    def tehdas():
        def strat(data, paiva, sallitut):
            return {"BUSDT": osuus} if "BUSDT" in sallitut else {}
        return strat
    return tehdas


class Delistaus(unittest.TestCase):
    def aja(self, haircut):
        d = laaja.LaajaData(tila="kaikki", n=3, haircut=haircut, rename={}, _syotteet=syotteet(pohja()))
        a = date(2021, 12, 1)
        l = date(2021, 10, 1) + (date(2023, 6, 1) - date(2021, 10, 1))
        arvot, kauppoja = bt._aja(aina_b(), d, a, l)
        return arvot

    def test_omistus_myydaan_delistauksessa_ilman_virhetta(self):
        a0, a3 = self.aja(0.0), self.aja(0.3)
        self.assertEqual(len(a0), len(a3))
        self.assertGreater(a0[-1] - a3[-1], 300)     # 15 % positio * 30 % haircut ~ 450 USDT
        self.assertGreater(a3[-1], 8000)              # ei romahda (virheetonta kirjanpitoa)

    def test_haircut_nolla_ei_tuhoa_arvoa(self):
        a0 = self.aja(0.0)
        self.assertGreater(a0[-1], 9000)


class Aukot(unittest.TestCase):
    def kartta(self):
        # A: elossa koko ajan. L: ensimmainen kolikko 0..299, 20 paivan aukko, uusi kolikko samalla tunnuksella 320..799
        # S: 3 paivan aukko 400..402 (esim. keskeytys)
        k = {"AUSDT": sarja(800, vol=900.0), "BTCUSDT": sarja(800, vol=2000.0), "CUSDT": sarja(800, vol=700.0)}
        k["LUSDT"] = {**sarja(300, 0, vol=6000.0), **sarja(480, 320, vol=100.0)}
        s = sarja(800, vol=5000.0)
        for i in (400, 401, 402):
            del s[T0 + i * PV]
        k["SUSDT"] = s
        return k

    def test_pitka_aukko_jakaa_vanhan_patkan_kuolleeksi(self):
        d = laaja.LaajaData(tila="kaikki", n=4, rename={}, _syotteet=syotteet(self.kartta()))
        self.assertIn("LUSDT#1", d.kuollut)
        self.assertNotIn("LUSDT", d.kuollut)
        self.assertEqual(min(d.close["LUSDT"]), T0 + 320 * PV)
        self.assertEqual(max(d.close["LUSDT#1"]), T0 + 299 * PV)
        self.assertTrue(any("jaettu LUSDT" in x for x in d.aukkoraportti))

    def test_elossa_ei_sisalla_vanhaa_patkaa(self):
        d = laaja.LaajaData(tila="elossa", n=4, rename={}, _syotteet=syotteet(self.kartta()))
        self.assertNotIn("LUSDT#1", d.symbolit)

    def test_omistus_pitkan_aukon_yli_ei_kaada_ajoa(self):
        def aina_l():
            def tehdas():
                def strat(data, paiva, sallitut):
                    ehd = {s: 0.15 for s in ("LUSDT#1", "LUSDT") if s in sallitut}
                    return ehd
                return strat
            return tehdas
        d = laaja.LaajaData(tila="kaikki", n=4, haircut=0.3, rename={}, _syotteet=syotteet(self.kartta()))
        arvot, _ = bt._aja(aina_l(), d, date(2021, 12, 1), date(2022, 9, 1))   # aukko kohdassa 2022-07-28..2022-08-17
        self.assertGreater(len(arvot), 250)
        self.assertTrue(all(a > 0 for a in arvot))

    def test_lyhyt_aukko_ei_kaada_omistusta(self):
        def aina_s():
            def tehdas():
                def strat(data, paiva, sallitut):
                    return {"SUSDT": 0.15} if "SUSDT" in sallitut else {}
                return strat
            return tehdas
        d = laaja.LaajaData(tila="kaikki", n=4, rename={}, _syotteet=syotteet(self.kartta()))
        self.assertIn("SUSDT", d.symbolit)
        self.assertNotIn(T0 + 401 * PV, d.close["SUSDT"])        # strategia ei nae taytettya hintaa
        arvot, _ = bt._aja(aina_s(), d, date(2022, 9, 1), date(2023, 2, 15))   # paivat 335..502 sisaltavat aukon
        self.assertGreater(len(arvot), 100)


class Lataus(unittest.TestCase):
    def setUp(self):
        self.con = db.avaa(":memory:")

    def test_tyot_vain_olemassaolevat_kuukaudet_ja_paivat_elossa_oleville(self):
        rivit = [("AAAUSDT", (2021, 6), (2021, 12), True), ("BBBUSDT", (2026, 8), (2026, 9), False), ("OLDUSDT", (2019, 1), (2020, 5), True)]
        t = hl.tyot(rivit, date(2026, 10, 4))
        a = [x for x in t if x[0] == "AAAUSDT"]
        self.assertEqual([x[2] for x in a], ["2021-10", "2021-11", "2021-12"])   # alkaa ALKU_KK:sta, ei 404-pyyntoja
        self.assertEqual([x for x in t if x[0] == "OLDUSDT"], [])               # kuoli ennen datan alkua
        b = [x for x in t if x[0] == "BBBUSDT"]
        self.assertEqual([x[1] for x in b], ["spot_kk", "spot_kk", "spot_pv", "spot_pv", "spot_pv"])
        self.assertEqual([x[2] for x in b if x[1] == "spot_pv"], ["2026-10-01", "2026-10-02", "2026-10-03"])

    def test_aja_kirjoittaa_puuttuvan_ja_on_idempotentti(self):
        lista = [("XUSDT", "spot_kk", "2022-01", "u1"), ("XUSDT", "spot_kk", "2022-02", "u2")]
        kutsut = []

        def hae(u):
            kutsut.append(u)
            return kuukausi_zip(2022, 1, 31) if u == "u1" else None
        t = hl.aja(self.con, lista, hae, tyontekijoita=2, paussi=0, edistyminen=0)
        self.assertEqual(t["hinnat"], 31)
        self.assertEqual(t["puuttuu"], 1)
        self.assertEqual(len(kutsut), 2)
        t2 = hl.aja(self.con, lista, hae, tyontekijoita=2, paussi=0, edistyminen=0)
        self.assertEqual(len(kutsut), 2)       # ei uusia pyyntoja
        self.assertEqual(t2["ohitettu"], 2)

    def test_huono_tiedosto_kirjataan_virheeksi_eika_kirjoita_mitaan(self):
        huono = zipita(kline(2022, 1, 1) + "\n12345,1,2,3,4,5")
        t = hl.aja(self.con, [("XUSDT", "spot_kk", "2022-01", "u")], lambda u: huono, tyontekijoita=1, paussi=0, edistyminen=0)
        self.assertEqual(len(t["virheet"]), 1)
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM hinnat").fetchone()[0], 0)

    def test_verkkovirhe_ei_kirjaa_valmiiksi(self):
        def hae(u):
            raise lahde.Verkkovirhe("x")
        lista = [("XUSDT", "spot_kk", "2022-01", "u")]
        t = hl.aja(self.con, lista, hae, tyontekijoita=1, paussi=0, edistyminen=0)
        self.assertEqual(len(t["virheet"]), 1)
        self.assertIsNone(db.tila(self.con, "spot_kk", "XUSDT", "2022-01"))   # yritetaan uudelleen ensi ajolla

    def test_estetty_keskeyttaa(self):
        def hae(u):
            raise lahde.Estetty(u)
        with self.assertRaises(lahde.Estetty):
            hl.aja(self.con, [("XUSDT", "spot_kk", "2022-01", "u")], hae, tyontekijoita=1, paussi=0, edistyminen=0)

    def test_ei_saa_kirjoittaa_markkina_kantaan(self):
        self.assertEqual(hl.main(["--db", config.DB_POLKU]), 3)


class Suojat(unittest.TestCase):
    def test_laaja_ei_saa_kayttaa_tuotantorekisteria(self):
        self.assertEqual(laaja.main(["--rekisteri", rajat.KOKEILU_DB, "--db", "/tmp/ei_ole.db"]), 3)

    def test_laaja_vaatii_historian(self):
        self.assertEqual(laaja.main(["--rekisteri", "/tmp/k11test_rek.db", "--db", "/tmp/ei_ole_varmasti.db"]), 2)


class Kokonaisuus(unittest.TestCase):
    def test_skenaario_loppuun_pienella_aineistolla(self):
        kartta = {s: sarja(800, vol=1000.0 + 10 * i, kasvu=0.0005 * (i % 3)) for i, s in enumerate(
            ["BTCUSDT", "AUSDT", "CUSDT", "DUSDT", "EUSDT", "FUSDT"])}
        kartta["BUSDT"] = sarja(700, vol=3000.0)
        with tempfile.TemporaryDirectory() as tmp:
            rek = bt.avaa_rekisteri(os.path.join(tmp, "rek.db"))
            rivit, t = laaja.skenaario(None, "kaikki", 0.1, 4, rek, [{"ikkuna": 30, "k": 3, "reb": 7}],
                                       alku=date(2022, 1, 1), loppu=date(2023, 4, 20), _syotteet=syotteet(kartta))
        self.assertTrue(rivit[0].startswith("== universumi=kaikki"))
        self.assertIsNotNone(t["momentum"])
        self.assertIn("BUSDT", " ".join(rivit))     # kuollut kolikko nakyy raportissa

    def test_vertailu_ryhmittelee_jarrun_mukaan(self):
        ts = [{"tila": "vanha", "haircut": 0.1, "jarru": 0.25, "momentum": 1.5, "kori": 0.8},
              {"tila": "elossa", "haircut": 0.1, "jarru": 0.25, "momentum": -0.7, "kori": -0.7},
              {"tila": "kaikki", "haircut": 0.1, "jarru": 0.25, "momentum": -0.72, "kori": -0.77},
              {"tila": "vanha", "haircut": 0.1, "jarru": 1.0, "momentum": 2.0, "kori": 0.9}]
        r = laaja.vertailu(ts)
        self.assertIn("-- hatajarru 25 % --", r)
        self.assertIn("-- ei jarrua --", r)
        self.assertTrue(any("vanha lista 150.0 % -> elossa -70.0 % -> kaikki -72.0 %" in x for x in r))

    def test_jasenna(self):
        self.assertEqual(laaja.jasenna("vanha:0.1"), ("vanha", 0.1, None))
        self.assertEqual(laaja.jasenna(" kaikki:0.3:0.25 "), ("kaikki", 0.3, 0.25))
        with self.assertRaises(ValueError):
            laaja.jasenna("vanha")

    def test_jarru_palautuu_ajon_jalkeen(self):
        kartta = {s: sarja(800, vol=1000.0 + 10 * i) for i, s in enumerate(["BTCUSDT", "AUSDT", "CUSDT", "DUSDT"])}
        ennen = rajat.MAX_DRAWDOWN
        with tempfile.TemporaryDirectory() as tmp:
            rek = bt.avaa_rekisteri(os.path.join(tmp, "rek.db"))
            rivit, t = laaja.skenaario(None, "vanha", 0.1, 3, rek, [{"ikkuna": 30, "k": 3, "reb": 7}],
                                       alku=date(2022, 1, 1), loppu=date(2023, 4, 20), _syotteet=syotteet(kartta), jarru=0.2)
        self.assertEqual(rajat.MAX_DRAWDOWN, ennen)
        self.assertEqual(t["jarru"], 0.2)
        self.assertIn("hatajarru 20 %", rivit[0])


class Rehellinen(unittest.TestCase):
    """K12: K7 ja K6 kayttavat oletuksena point-in-time-universumia."""

    def test_puuttuva_historia_fail_closed(self):
        with self.assertRaises(laaja.HistoriaPuuttuu):
            laaja.rehellinen_data("/tmp/ei_ole_varmasti_historia.db")

    def test_rehellinen_data_on_kaikki_tila_ja_haircut_10(self):
        kartta = {s: sarja(300) for s in ["BTCUSDT", "AUSDT"]}
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, "h.db")
            open(p, "w").close()
            with mock.patch.object(laaja, "_lue", return_value=syotteet(kartta)):
                d = laaja.rehellinen_data(p)
        self.assertEqual((d.tila, d.haircut, d.n), ("kaikki", 0.10, 20))

    def test_k7_testaa_toimii_rehellisella_datalla_ja_kertoo_universumin(self):
        kartta = {s: sarja(800, vol=1000.0 + 10 * i, kasvu=0.0005 * (i % 3)) for i, s in enumerate(
            ["BTCUSDT", "AUSDT", "CUSDT", "DUSDT", "EUSDT", "FUSDT"])}
        kartta["BUSDT"] = sarja(700, vol=3000.0)
        d = laaja.LaajaData(tila="kaikki", n=5, rename={}, _syotteet=syotteet(kartta))
        with tempfile.TemporaryDirectory() as tmp:
            rek = k7.avaa(os.path.join(tmp, "r.db"))
            s = k7.tarkista_spec(spec_dict())
            a, t = k7.testaa(s, d, rek, "x", 1, satunnaisia=3, wf_kw=dict(alku=date(2022, 2, 1), loppu=date(2023, 4, 20), train_pv=150, testi_pv=60))
            self.assertEqual(rek.execute("SELECT COUNT(*) FROM holdout_kaytto").fetchone()[0], 0)
        self.assertIn("point-in-time", t)
        self.assertNotIn("jalkikateen valittu (2026)", t)

    def test_k7_vanha_data_nayttaa_vanhan_varoituksen(self):
        a = {"oos_tuotto": 0.1, "oos_max_dd": 0.1, "oos_sharpe": 0.5, "btc_tuotto": 1.0, "btc_sharpe": 1.0, "satunnaisia": 10,
             "p_satunnainen": 0.5, "p_korjattu": 1.0, "riittavasti_satunnaisia": True, "voittaa_satunnaiset": False,
             "voittaa_btc_tuotto": False, "voittaa_btc_sharpe": False}
        self.assertIn("jalkikateen valittu", bt.teksti("x", a, 1))
        self.assertIn("point-in-time", bt.teksti("x", a, 1, rehellinen=True))

    def test_k7_main_puuttuva_historia_kasinspec_ei_rekisteroi(self):
        with tempfile.TemporaryDirectory() as tmp:
            sp = os.path.join(tmp, "s.json")
            with open(sp, "w") as f:
                json.dump(spec_dict(), f)
            rekp = os.path.join(tmp, "r.db")
            with mock.patch.object(laaja, "HISTORIA_DB", os.path.join(tmp, "ei.db")):
                self.assertEqual(k7.main(["--ei-tg", "--rekisteri", rekp, "--spec-tiedosto", sp]), 2)
            self.assertEqual(k7.avaa(rekp).execute("SELECT COUNT(*) FROM k7_hypoteesit").fetchone()[0], 0)

    def test_k7_main_puuttuva_historia_ei_kutsu_llm(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(laaja, "HISTORIA_DB", os.path.join(tmp, "ei.db")), mock.patch("llm.kysy") as kys:
                self.assertEqual(k7.main(["--ei-tg", "--rekisteri", os.path.join(tmp, "r.db"), "--llm-env", os.path.join(tmp, "ei")]), 2)
                kys.assert_not_called()


if __name__ == "__main__":
    unittest.main()
