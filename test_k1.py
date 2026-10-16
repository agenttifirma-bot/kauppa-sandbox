import io
import json
import unittest
import zipfile
from datetime import date, datetime, timezone

import config
import db
import lahde
import lataa
import tarkista

PV = 86400000


def ms(y, m, d):
    return int(datetime(y, m, d, tzinfo=timezone.utc).timestamp() * 1000)


def kline(y, m, d, mikro=False, c=100.0):
    t = ms(y, m, d) * (1000 if mikro else 1)
    return "%d,99,101,98,%s,10,%d,1000,50,5,500,0" % (t, c, t + 86399999)


def zipita(teksti, nimi="x.csv"):
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr(nimi, teksti)
    return b.getvalue()


def kuukausi_zip(y, m, paivia, otsikko=False, mikro=False):
    rivit = ["open_time,open,high,low,close,volume,close_time,qv,n,a,b,i"] if otsikko else []
    rivit += [kline(y, m, d, mikro) for d in range(1, paivia + 1)]
    return zipita("\n".join(rivit))


class Pohja(unittest.TestCase):
    def setUp(self):
        self.con = db.avaa(":memory:")
        self.kutsut = []

    def hae_alkaen(self, kartta):
        def hae(url):
            self.kutsut.append(url)
            return kartta.get(url)
        return hae


class ParseTesti(unittest.TestCase):
    def test_otsikko_ja_ms(self):
        r = lahde.parse_klines("open_time,o\n" + kline(2024, 1, 1) + "\n" + kline(2024, 1, 2))
        self.assertEqual(len(r), 2)
        self.assertEqual(r[0][0], ms(2024, 1, 1))

    def test_mikrosekunnit(self):
        r = lahde.parse_klines(kline(2025, 3, 1, mikro=True))
        self.assertEqual(r[0][0], ms(2025, 3, 1))

    def test_hylkaa_ohlc_ristiriita(self):
        rivi = "%d,99,90,98,100,10,0,1000,50" % ms(2024, 1, 1)  # high < close
        with self.assertRaises(lahde.Parsevirhe):
            lahde.parse_klines(rivi)

    def test_hylkaa_vaara_aikaleima(self):
        with self.assertRaises(lahde.Parsevirhe):
            lahde.parse_klines("%d,99,101,98,100,10,0,1000,50" % (ms(2024, 1, 1) + 5))

    def test_yksi_huono_rivi_hylkaa_kaiken(self):
        with self.assertRaises(lahde.Parsevirhe):
            lahde.parse_klines(kline(2024, 1, 1) + "\n1,2,3")

    def test_funding_otsikolla(self):
        r = lahde.parse_funding("calc_time,funding_interval_hours,last_funding_rate\n1700000000000,8,0.0001\n1700028800000,8,-0.0002")
        self.assertEqual(r[1], (1700028800000, 8.0, -0.0002))

    def test_funding_epauskottava(self):
        with self.assertRaises(lahde.Parsevirhe):
            lahde.parse_funding("1700000000000,8,0.5")

    def test_rikkinainen_zip(self):
        with self.assertRaises(lahde.Parsevirhe):
            lahde.pura_zip(b"ei zip")

    def test_zip_kaksi_tiedostoa(self):
        b = io.BytesIO()
        with zipfile.ZipFile(b, "w") as z:
            z.writestr("a", "1"); z.writestr("b", "2")
        with self.assertRaises(lahde.Parsevirhe):
            lahde.pura_zip(b.getvalue())


class LatausTesti(Pohja):
    def setUp(self):
        super().setUp()
        self._alku = config.ALKU
        config.ALKU = (2026, 7)

    def tearDown(self):
        config.ALKU = self._alku

    def kartta(self):
        return {
            lahde.url_spot_kk("BTCUSDT", 2026, 7): kuukausi_zip(2026, 7, 31),
            lahde.url_spot_kk("BTCUSDT", 2026, 8): kuukausi_zip(2026, 8, 31, otsikko=True),
            # syyskuun kk-tiedostoa ei viela -> paivittaiset
            **{lahde.url_spot_pv("BTCUSDT", 2026, 9, d): zipita(kline(2026, 9, d)) for d in range(1, 31)},
            **{lahde.url_spot_pv("BTCUSDT", 2026, 10, d): zipita(kline(2026, 10, d)) for d in range(1, 15)},
            lahde.url_funding_kk("BTCUSDT", 2026, 7): zipita("calc_time,funding_interval_hours,last_funding_rate\n%d,8,0.0001" % ms(2026, 7, 1)),
        }

    def test_taysi_ajo_ja_idempotenssi(self):
        hae = self.hae_alkaen(self.kartta())
        t = lataa.aja(self.con, ["BTCUSDT"], date(2026, 10, 15), hae)
        self.assertEqual(t["virheet"], [])
        n = self.con.execute("SELECT COUNT(*) FROM hinnat").fetchone()[0]
        self.assertEqual(n, 31 + 31 + 30 + 14)
        kutsuja = len(self.kutsut)
        t2 = lataa.aja(self.con, ["BTCUSDT"], date(2026, 10, 15), hae)
        self.assertEqual(t2["hinnat"], 0)
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM hinnat").fetchone()[0], n)
        # toisella ajolla ei haeta enaa vanhoja kuukausia/paivia uudelleen (vain syyskuun kk-yritys + funding-REST + lokittamattomat)
        self.assertLess(len(self.kutsut) - kutsuja, kutsuja)

    def test_puuttuva_kuukausi_kirjataan_ja_ei_haeta_uudelleen(self):
        hae = self.hae_alkaen({})
        lataa.paivita_spot(self.con, "XYZUSDT", date(2026, 10, 15), hae, 0, {"hinnat": 0, "virheet": []})
        self.assertEqual(db.tila(self.con, "spot_kk", "XYZUSDT", "2026-07"), "puuttuu")
        self.assertIsNone(db.tila(self.con, "spot_kk", "XYZUSDT", "2026-09"))  # edellista kk:ta ei lukita
        kutsuja = len(self.kutsut)
        lataa.paivita_spot(self.con, "XYZUSDT", date(2026, 10, 15), hae, 0, {"hinnat": 0, "virheet": []})
        urls = self.kutsut[kutsuja:]
        self.assertFalse(any("2026-07.zip" in u for u in urls))

    def test_huono_tiedosto_ei_kirjoita_mitaan(self):
        huono = zipita(kline(2026, 7, 1) + "\n%d,99,90,98,100,10,0,1000,50" % ms(2026, 7, 2))
        hae = self.hae_alkaen({lahde.url_spot_kk("BTCUSDT", 2026, 7): huono})
        t = {"hinnat": 0, "virheet": []}
        lataa.paivita_spot(self.con, "BTCUSDT", date(2026, 10, 15), hae, 0, t)
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM hinnat WHERE ts<?", (ms(2026, 8, 1),)).fetchone()[0], 0)
        self.assertEqual(db.tila(self.con, "spot_kk", "BTCUSDT", "2026-07"), "virhe")
        self.assertTrue(t["virheet"])

    def test_funding_rest_sivutus(self):
        sivu1 = json.dumps([{"fundingTime": 1000 + i, "fundingRate": "0.0001"} for i in range(1000)]).encode()
        sivu2 = json.dumps([{"fundingTime": 5000 + i, "fundingRate": "0.0002"} for i in range(3)]).encode()
        vastaukset = [sivu1, sivu2]

        def hae(url):
            if url.startswith(config.FUNDING_REST):
                return vastaukset.pop(0) if vastaukset else b"[]"
            return None
        t = {"funding": 0, "virheet": []}
        lataa.paivita_funding(self.con, "BTCUSDT", date(2026, 10, 15), hae, 0, t)
        self.assertEqual(t["funding"], 1003)

    def test_yhteystesti(self):
        hae = self.hae_alkaen({lahde.url_spot_kk("BTCUSDT", 2023, 1): kuukausi_zip(2023, 1, 31)})
        self.assertTrue(lataa.yhteystesti(hae))
        self.assertFalse(lataa.yhteystesti(self.hae_alkaen({})))


class TarkistaTesti(Pohja):
    def test_aukko_ja_vanhentuminen(self):
        rivit = [(ms(2026, 10, d), 99, 101, 98, 100, 1, 1, 1) for d in (1, 2, 4, 5)]
        db.lisaa_hinnat(self.con, "BTCUSDT", rivit)
        ong, _, _ = tarkista.raportti(self.con, date(2026, 10, 6))
        tekstit = " ".join(ong)
        self.assertIn("1 paivaa puuttuu", tekstit)
        ong2, _, _ = tarkista.raportti(self.con, date(2026, 10, 20))
        self.assertIn("vanhentunut", " ".join(ong2))

    def test_ehja_data_ok_symbolille(self):
        rivit = [(ms(2026, 10, d), 99, 101, 98, 100, 1, 1, 1) for d in range(1, 6)]
        db.lisaa_hinnat(self.con, "BTCUSDT", rivit)
        ong, _, _ = tarkista.raportti(self.con, date(2026, 10, 6))
        self.assertFalse([o for o in ong if o.startswith("BTCUSDT")])

    def test_ei_dataa_on_ongelma(self):
        ong, _, _ = tarkista.raportti(self.con, date(2026, 10, 6))
        self.assertTrue(any("ei hintadataa" in o for o in ong))


if __name__ == "__main__":
    unittest.main()


class TestFuturesNimi(unittest.TestCase):
    def test_pepe_funding_url_kayttaa_1000_nimea(self):
        self.assertIn("1000PEPEUSDT", lahde.url_funding_kk("PEPEUSDT", 2026, 7))
        self.assertIn("symbol=1000PEPEUSDT", lahde.url_funding_rest("PEPEUSDT", 1))
        self.assertIn("/BTCUSDT/", lahde.url_funding_kk("BTCUSDT", 2026, 7))
        # spot-urli ei muutu
        self.assertIn("/PEPEUSDT/", lahde.url_spot_kk("PEPEUSDT", 2026, 7))
