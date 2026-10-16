import os
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone

import db
import rajat
import retro
import salkku

PV = 86400000


def ms(p):
    return int(datetime(p.year, p.month, p.day, tzinfo=timezone.utc).timestamp() * 1000)


class RetroTesti(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.addCleanup(self.d.cleanup)
        self.data = os.path.join(self.d.name, "m.db")
        self.a = os.path.join(self.d.name, "a.db")
        self.b = os.path.join(self.d.name, "b.db")
        self.alku = date(2026, 10, 1)

    def markkina(self, paivia):
        con = db.avaa(self.data)
        for s in ("BTCUSDT", "BNBUSDT"):
            rivit = []
            for i in range(paivia):
                p = self.alku + timedelta(days=i)
                h = 100.0 * (1 + 0.01 * i)
                rivit.append((ms(p), h, h, h, h, 1.0, 1.0, 1))
            db.lisaa_hinnat(con, s, rivit)
        con.close()

    def salkku(self, polku, paivia, kerroin=0.001, kaupat=0, jarru=False):
        con = salkku.avaa(polku)
        salkku._aseta(con, "aloituspaiva", self.alku.isoformat())
        salkku._aseta(con, "viimeisin_paiva", (self.alku + timedelta(days=paivia - 1)).isoformat())
        salkku._aseta(con, "jarru", "1" if jarru else "0")
        for i in range(paivia):
            p = (self.alku + timedelta(days=i)).isoformat()
            con.execute("INSERT OR REPLACE INTO arvot VALUES (?,?,?,?)", (p, 10000.0 * (1 + kerroin * i), 1000.0, 9000.0))
            con.execute("INSERT OR REPLACE INTO paatokset VALUES (?,?,?,?)", (p, "{}", "[]", "virhe" if i % 4 == 0 else None))
        for i in range(kaupat):
            p = (self.alku + timedelta(days=paivia - 1 - i)).isoformat()
            con.execute("INSERT INTO kaupat (paiva,symbol,puoli,maara,hinta,kulu,slippage_kulu) VALUES (?,?,?,?,?,?,?)", (p, "BTCUSDT", "osto", 1.0, 100.0, 1.0, 0.5))
        con.commit()
        con.close()

    def aja(self, paivia, **kw):
        tanaan = self.alku + timedelta(days=paivia)
        return retro.raportti(self.data, {"flash": self.a, "pro": self.b}, tanaan, kw.get("stop"))

    def test_lyhyt_historia_ei_johtopaatoksia(self):
        self.markkina(10); self.salkku(self.a, 10); self.salkku(self.b, 10, 0.002)
        t = self.aja(10)
        self.assertIn("flash:", t); self.assertIn("pro:", t); self.assertIn("BTC:", t)
        self.assertIn("vertailu (Tonyn jako)", t)
        self.assertIn("ei johtopaatoksia", t)

    def test_pitka_historia_ero_mutta_varoitus(self):
        self.markkina(30); self.salkku(self.a, 30); self.salkku(self.b, 30, 0.002)
        t = self.aja(30)
        self.assertNotIn("ei johtopaatoksia", t)
        self.assertIn("ei todista", t)

    def test_viikon_kaupat_ja_kulut(self):
        self.markkina(10); self.salkku(self.a, 10, kaupat=3); self.salkku(self.b, 10)
        t = self.aja(10)
        self.assertIn("kaupat 3 (kulut 4.5 USDT)", t)

    def test_salkkua_ei_ole(self):
        self.markkina(10); self.salkku(self.a, 10)
        t = self.aja(10)
        self.assertIn("pro: ei viela dataa", t)

    def test_jarru_ja_kill_switch_nakyvat(self):
        self.markkina(10); self.salkku(self.a, 10, jarru=True); self.salkku(self.b, 10)
        stop = os.path.join(self.d.name, "STOP"); open(stop, "w").close()
        t = self.aja(10, stop=stop)
        self.assertIn("HATAJARRU", t); self.assertIn("KILL SWITCH", t)

    def test_vertailu_puuttuu_ei_kaada(self):
        self.markkina(3); self.salkku(self.a, 10); self.salkku(self.b, 10)
        t = self.aja(10)
        self.assertIn("vertailu ei saatavilla", t)

    def test_ei_kirjoita_salkkuihin(self):
        self.markkina(10); self.salkku(self.a, 10); self.salkku(self.b, 10)
        m = [os.path.getmtime(self.a), os.path.getmtime(self.b)]
        self.aja(10)
        self.assertEqual(m, [os.path.getmtime(self.a), os.path.getmtime(self.b)])


if __name__ == "__main__":
    unittest.main()
