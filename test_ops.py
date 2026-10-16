import os
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from unittest import mock

import db
import paiva
import rajat
import salkku
import sykemittari as sm

PV = 86400000
TANAAN = date(2026, 10, 16)


def ms(p):
    return int(datetime(p.year, p.month, p.day, tzinfo=timezone.utc).timestamp() * 1000)


class Ymp:
    def __init__(self):
        self.d = tempfile.TemporaryDirectory()
        self.data = os.path.join(self.d.name, "markkina.db")
        self.flash = os.path.join(self.d.name, "flash.db")
        self.pro = os.path.join(self.d.name, "pro.db")
        self.stop = os.path.join(self.d.name, "PYSAYTYS")

    def markkina(self, viim):
        con = db.avaa(self.data)
        db.lisaa_hinnat(con, "BTCUSDT", [(ms(viim), 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1)])
        con.close()

    def salkku(self, polku, viim, jarru=False, hylatyt=(None, None, None)):
        con = salkku.avaa(polku)
        salkku._aseta(con, "viimeisin_paiva", viim.isoformat())
        salkku._aseta(con, "jarru", "1" if jarru else "0")
        for i, h in enumerate(hylatyt):
            con.execute("INSERT OR REPLACE INTO paatokset VALUES (?,?,?,?)", ((viim - timedelta(days=i)).isoformat(), "{}", "[]", h))
            con.execute("INSERT OR REPLACE INTO arvot VALUES (?,?,?,?)", ((viim - timedelta(days=i)).isoformat(), 10000.0, 10000.0, 0.0))
        con.commit()
        con.close()

    def salkut(self):
        return {"flash": self.flash, "pro": self.pro}


class SykemittariTesti(unittest.TestCase):
    def setUp(self):
        self.y = Ymp()
        self.addCleanup(self.y.d.cleanup)

    def terve(self):
        viim = TANAAN - timedelta(days=1)
        self.y.markkina(viim)
        self.y.salkku(self.y.flash, viim)
        self.y.salkku(self.y.pro, viim)

    def test_kaikki_ok(self):
        self.terve()
        ong, info = sm.tarkista(self.y.data, self.y.salkut(), TANAAN, self.y.stop)
        self.assertEqual(ong, [])
        self.assertEqual(len(info), 2)

    def test_vanhentunut_data(self):
        viim = TANAAN - timedelta(days=6)
        self.y.markkina(viim)
        self.y.salkku(self.y.flash, viim)
        self.y.salkku(self.y.pro, viim)
        ong, _ = sm.tarkista(self.y.data, self.y.salkut(), TANAAN, self.y.stop)
        self.assertTrue(any("vanhentunut" in o for o in ong))

    def test_salkkua_ei_ole_eika_luoda(self):
        self.terve()
        os.remove(self.y.pro)
        ong, _ = sm.tarkista(self.y.data, self.y.salkut(), TANAAN, self.y.stop)
        self.assertTrue(any("pro" in o and "tiedostoa ei ole" in o for o in ong))
        self.assertFalse(os.path.exists(self.y.pro))  # vain luku, ei luo tiedostoa

    def test_jaljessa(self):
        self.terve()
        self.y.salkku(self.y.flash, TANAAN - timedelta(days=4))
        ong, _ = sm.tarkista(self.y.data, self.y.salkut(), TANAAN, self.y.stop)
        self.assertTrue(any("flash jaljessa" in o for o in ong))

    def test_hatajarru(self):
        self.terve()
        self.y.salkku(self.y.pro, TANAAN - timedelta(days=1), jarru=True)
        ong, _ = sm.tarkista(self.y.data, self.y.salkut(), TANAAN, self.y.stop)
        self.assertTrue(any("HATAJARRU" in o for o in ong))

    def test_kolme_hylattya(self):
        self.terve()
        self.y.salkku(self.y.flash, TANAAN - timedelta(days=1), hylatyt=("x", "y", "z"))
        ong, _ = sm.tarkista(self.y.data, self.y.salkut(), TANAAN, self.y.stop)
        self.assertTrue(any("ilman hyvaksyttya" in o for o in ong))

    def test_yksi_hylatty_ei_halyta(self):
        self.terve()
        self.y.salkku(self.y.flash, TANAAN - timedelta(days=1), hylatyt=("x", None, None))
        ong, _ = sm.tarkista(self.y.data, self.y.salkut(), TANAAN, self.y.stop)
        self.assertEqual(ong, [])

    def test_kill_switch_nakyy(self):
        self.terve()
        open(self.y.stop, "w").close()
        ong, _ = sm.tarkista(self.y.data, self.y.salkut(), TANAAN, self.y.stop)
        self.assertTrue(any("KILL SWITCH" in o for o in ong))

    def test_rikkinainen_data_ei_kaada(self):
        ong, _ = sm.tarkista(os.path.join(self.y.d.name, "ei_ole.db"), self.y.salkut(), TANAAN, self.y.stop)
        self.assertTrue(ong)


class KillSwitchTesti(unittest.TestCase):
    def test_paiva_main_pysahtyy_ilman_llm_kutsua(self):
        with tempfile.TemporaryDirectory() as d:
            stop = os.path.join(d, "PYSAYTYS")
            open(stop, "w").close()
            argv = ["paiva.py", "--malli", "flash", "--salkku-db", os.path.join(d, "s.db"), "--ei-tg"]
            with mock.patch.object(rajat, "PYSAYTYS", stop), mock.patch.object(sys, "argv", argv), \
                    mock.patch("llm._http_post", side_effect=AssertionError("LLM-kutsu kill switchin aikana")), \
                    mock.patch("db.avaa", side_effect=AssertionError("kantaa ei saa avata")):
                self.assertEqual(paiva.main(), 0)
            self.assertFalse(os.path.exists(os.path.join(d, "s.db")))  # salkkua ei luotu


if __name__ == "__main__":
    unittest.main()
