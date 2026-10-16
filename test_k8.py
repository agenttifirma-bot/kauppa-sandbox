"""Auditointikorjausten (K8) regressiotestit: jokainen testi vastaa auditoinnin loydosta."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone

import agentit
import backtest as bt
import k7
import paiva
import rajat
import salkku
from test_k2 import luo_kanta
from test_k6 import SYMBOLIT, kanta

HERE = os.path.dirname(os.path.abspath(__file__))
S20 = ["C%02dUSDT" % i for i in range(19)] + ["BTCUSDT"]

DET_SKRIPTI = """
import sys
sys.path.insert(0, %r)
from datetime import date
import backtest as bt, k7, config
from test_k2 import luo_kanta
d = bt.Data(luo_kanta(config.SYMBOLIT, paivia=500, seed=4), 20)
a, b = date(2025, 6, 1), date(2026, 3, 1)
par = {"signaali": "momentum", "suunta": "matala", "ikkuna": 7, "k": 10, "reb": 3, "osuus": 0.8, "suodin": "ei", "suodin_toiminto": "kateinen"}
print(repr((bt._aja(bt.tasapaino(), d, a, b)[0][-1], bt._aja(k7.rakenna(par), d, a, b)[0][-1], bt._aja(bt.satunnainen(1, k=8, reb=7), d, a, b)[0][-1])))
""" % HERE


class DeterminismiTesti(unittest.TestCase):
    def test_tulos_ei_riipu_hash_siemenesta(self):          # A1
        ulos = []
        for seed in ("0", "1", "2"):
            env = dict(os.environ, PYTHONHASHSEED=seed)
            r = subprocess.run([sys.executable, "-c", DET_SKRIPTI], capture_output=True, text=True, env=env, cwd=HERE)
            self.assertEqual(r.returncode, 0, r.stderr[-500:])
            ulos.append(r.stdout.strip())
        self.assertEqual(len(set(ulos)), 1, ulos)


class HoldoutVartijaTesti(unittest.TestCase):
    def setUp(self):
        self.d = bt.Data(kanta(300), 8)
        self.rek = bt.avaa_rekisteri(":memory:")
        self.H = bt.holdout_alku()

    def test__aja_kieltaytyy(self):                         # A4
        with self.assertRaises(bt.Holdoutvirhe):
            bt._aja(bt.tasapaino(), self.d, self.H, self.H + timedelta(days=5))
        with self.assertRaises(bt.Holdoutvirhe):
            bt._aja(k7.rakenna(PAR), self.d, self.H - timedelta(days=3), self.H)

    def test_satunnaisjakauma_ja_btc_vertailu_kieltaytyvat(self):
        ik = [(self.H, self.H + timedelta(days=10))]
        with self.assertRaises(bt.Holdoutvirhe):
            bt.satunnaisjakauma(self.d, ik, 1)
        with self.assertRaises(bt.Holdoutvirhe):
            k7.satunnaisjakauma(self.d, ik, 1, [PAR])
        with self.assertRaises(bt.Holdoutvirhe):
            bt.btc_vertailu(self.d, ik)

    def test_uudelleennimeaminen_ei_anna_toista_katsausta(self):
        bt.holdout_arvioi(bt.tasapaino(), self.d, self.rek, "mom_v1", {})
        for nimi in ("mom_v1 ", "MOM_V1", "  mom_v1"):
            with self.assertRaises(bt.Holdoutvirhe, msg=nimi):
                bt.holdout_arvioi(bt.tasapaino(), self.d, self.rek, nimi, {})

    def test_samat_parametrit_eri_nimella_estetty(self):
        p = {"ikkuna": 30, "k": 5}
        bt.holdout_arvioi(bt.tasapaino(), self.d, self.rek, "a", p)
        with self.assertRaises(bt.Holdoutvirhe):
            bt.holdout_arvioi(bt.tasapaino(), self.d, self.rek, "b", dict(p))
        # eri parametrit eri nimella sallittu
        bt.holdout_arvioi(bt.tasapaino(), self.d, self.rek, "c", {"ikkuna": 60, "k": 5})

    def test_kesken_jaanyt_ajo_kuluttaa_katsauksen(self):
        def rikki():
            def s(data, p, sall):
                raise RuntimeError("x")
            return s
        with self.assertRaises(RuntimeError):
            bt.holdout_arvioi(rikki, self.d, self.rek, "z", {})
        with self.assertRaises(bt.Holdoutvirhe):
            bt.holdout_arvioi(bt.tasapaino(), self.d, self.rek, "z", {})


PAR = {"signaali": "momentum", "suunta": "korkea", "ikkuna": 30, "k": 5, "reb": 7, "osuus": 0.8, "suodin": "ei", "suodin_toiminto": "kateinen"}


class NakymaTesti(unittest.TestCase):
    def test_strategia_ei_nae_tulevaisuutta(self):          # B7
        d = bt.Data(kanta(300), 8)
        nahty = {}

        def tehdas():
            def s(data, p, sall):
                for attr in ("close", "open", "con", "_uni"):
                    nahty[attr] = hasattr(data, attr)
                return {}
            return s
        bt.aja(tehdas, d, date(2026, 1, 10), date(2026, 1, 12))
        self.assertEqual(set(nahty.values()), {False})


class RiskiTesti(unittest.TestCase):
    def test_jarru_huomioi_alkupaoman(self):                # A7
        S = SYMBOLIT
        con = luo_kanta(S, paivia=5, seed=2)
        # simuloitu portfolio: ensimmainen paiva -11 %, sitten lisaa laskua; huippu = alkupaoma 10000
        sal = salkku.avaa(":memory:", alkupaoma=10000.0)
        sal.execute("INSERT INTO arvot VALUES ('2025-12-30', 8904, 8904, 0)")   # -11 % ekana paivana
        sal.commit()
        self.assertEqual(salkku._arvohistoria(sal)[0], 10000.0)
        from riskivahti import tila
        jarru, _, dd = tila(salkku._arvohistoria(sal) + [7400.0], False)
        self.assertTrue(jarru)                               # 26 % alkupaomasta (raja 25 %)

    def test_paivatappio_ensimmaisena_paivana_estaa_ostot(self):
        from riskivahti import tila
        sal = salkku.avaa(":memory:", alkupaoma=10000.0)
        sal.execute("INSERT INTO arvot VALUES ('2025-12-30', 9300, 9300, 0)")
        sal.commit()
        _, tappio, _ = tila(salkku._arvohistoria(sal), False)
        self.assertTrue(tappio)

    def test_hatajarrun_myynteja_ei_rajata_kauppamaaralla(self):       # A8a
        S = ["C%02dUSDT" % i for i in range(12)]
        con = luo_kanta(S, paivia=40, seed=3)
        sal = salkku.avaa(":memory:", alkupaoma=10000.0)
        loppu = date(2026, 1, 20)
        # avataan 12 pientä positiota (7 % kukin = 84 %), sitten hatajarru
        p0 = loppu
        with sal:
            pass
        d0 = p0 - timedelta(days=1)
        # etsitaan paiva jolle data on
        rivi = con.execute("SELECT MIN(ts), MAX(ts) FROM hinnat WHERE symbol=?", (S[0],)).fetchone()
        alku = datetime.fromtimestamp(rivi[0] / 1000, timezone.utc).date() + timedelta(days=2)
        eh = {s: 0.07 for s in S}
        r = salkku.suorita_paiva(sal, con, alku, eh, set(S))
        self.assertLessEqual(len(r["kaupat"]), rajat.MAX_KAUPPOJA_PAIVA)
        salkku.suorita_paiva(sal, con, alku + timedelta(days=1), eh, set(S))     # loput kaksi positiota
        omat_ennen = len(salkku.positiot(sal))
        self.assertEqual(omat_ennen, 12)
        salkku._aseta(sal, "jarru", "1")
        r2 = salkku.suorita_paiva(sal, con, alku + timedelta(days=2), {}, set(S))
        self.assertEqual(salkku.positiot(sal), {})
        self.assertTrue(all(k[2] == "SELL" for k in r2["kaupat"]))
        self.assertEqual(len(r2["kaupat"]), omat_ennen)


class AgenttiTesti(unittest.TestCase):
    def test_valtava_kokonaisluku_ei_kaada(self):           # A8d
        with self.assertRaises(agentit.Vastausvirhe):
            agentit.jasenna_analyytikko('{"paino": {"BTCUSDT": %s}, "perustelu": "x"}' % ("9" * 400))

    def test_syva_sisakkaisuus_ei_kaada(self):
        syva = "[" * 100000 + "]" * 100000
        with self.assertRaises(agentit.Vastausvirhe):
            agentit.pura_json('{"a": %s}' % syva)

    def test_kelvoton_vastaus_kirjataan_llm_kutsuksi(self):            # A8d (kutsulaskuri)
        S = SYMBOLIT
        mk = luo_kanta(S, paivia=120, seed=1)
        sal = salkku.avaa(":memory:", alkupaoma=10000.0)
        env = {"LLM_BASE_URL": "http://x/v1", "LLM_API_KEY": "k"}
        d = datetime.fromtimestamp(max(r[0] for r in mk.execute("SELECT ts FROM hinnat WHERE symbol='BTCUSDT'")) / 1000, timezone.utc).date()

        def hae(url, avain, payload):
            return {"choices": [{"message": {"content": "roskaa, ei jsonia"}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 100, "completion_tokens": 7}}
        t = paiva.aja_paiva(d, "m", mk, sal, env, hae)
        self.assertIn("Vastausvirhe", t["virhe"])
        n = sal.execute("SELECT COUNT(*) FROM llm_kutsut WHERE paiva=?", (d.isoformat(),)).fetchone()[0]
        self.assertEqual(n, 1)


class Spec2Testi(unittest.TestCase):
    def sd(self, **yli):
        s = {"nimi": "t", "hypoteesi": "Hypoteesi jolla on riittava pituus ja mekanismi",
             "kiinteat": {"signaali": "momentum", "suunta": "matala", "osuus": 0.7, "suodin": "ei", "suodin_toiminto": "kateinen"},
             "ruudukko": {"ikkuna": [7, 14], "k": [5, 8], "reb": [7, 14]}}
        s.update(yli)
        return s

    def test_float_kokonaisluvun_tilalla_hylataan(self):    # A6
        with self.assertRaises(k7.Speksivirhe):
            k7.tarkista_spec(self.sd(ruudukko={"ikkuna": [7.0, 14], "k": [5, 8], "reb": [7]}))
        with self.assertRaises(k7.Speksivirhe):
            k7.tarkista_spec(self.sd(ruudukko={"ikkuna": [7, 14], "k": [5.0, 8], "reb": [7]}))

    def test_yhden_arvon_ruudukko_sama_kuin_kiintea(self):
        a = k7.tarkista_spec(self.sd(ruudukko={"ikkuna": [7, 14], "k": [5, 8], "reb": [7]}))
        k = dict(self.sd()["kiinteat"], reb=7)
        b = k7.tarkista_spec(self.sd(kiinteat=k, ruudukko={"ikkuna": [7, 14], "k": [5, 8]}))
        self.assertEqual(k7.spec_hash(a), k7.spec_hash(b))

    def test_suodin_toiminto_merkityksetön_kun_ei_suodinta(self):
        a = k7.tarkista_spec(self.sd())
        k = dict(self.sd()["kiinteat"], suodin_toiminto="btc")
        b = k7.tarkista_spec(self.sd(kiinteat=k))
        self.assertEqual(k7.spec_hash(a), k7.spec_hash(b))

    def test_ruudukon_katto_8(self):
        with self.assertRaises(k7.Speksivirhe):
            k7.tarkista_spec(self.sd(ruudukko={"ikkuna": [7, 14, 30], "k": [5, 8, 10], "reb": [7]}))   # 9 > 8


class PerheBudjettiTesti(unittest.TestCase):
    def test_kerroin_kiintea_eika_riipu_jarjestyksesta(self):          # A5
        self.assertEqual(k7.K7_PERHE_BUDJETTI, 30)
        self.assertLessEqual(k7.MAX_RUUDUKKO * k7.K7_PERHE_BUDJETTI * 25, k7.MAX_SATUNNAISIA)   # satunnaisia riittaa aina

    def test_budjetin_tayttyessa_ei_testata(self):
        rek = k7.avaa(":memory:")
        for i in range(k7.K7_PERHE_BUDJETTI - 1):
            rek.execute("INSERT INTO k7_hypoteesit (aika,viikko,lahde,nimi,hash,spec,tila) VALUES ('a','w','llm',?,?, '{}', 'valmis')", ("n%d" % i, "h%d" % i))
        rek.commit()
        self.assertEqual(k7.perhe_koko(rek), k7.K7_PERHE_BUDJETTI)
        self.assertEqual(k7.budjettia_jaljella(rek), 0)

    def test_main_pysahtyy_kun_budjetti_taynna(self):
        with tempfile.TemporaryDirectory() as d:
            polku = os.path.join(d, "r.db")
            rek = k7.avaa(polku)
            for i in range(k7.K7_PERHE_BUDJETTI - 1):
                rek.execute("INSERT INTO k7_hypoteesit (aika,viikko,lahde,nimi,hash,spec,tila) VALUES ('a','w','kasin',?,?, '{}', 'valmis')", ("n%d" % i, "h%d" % i))
            rek.commit(); rek.close()
            self.assertEqual(k7.main(["--ei-tg", "--rekisteri", polku, "--llm-env", os.path.join(d, "ei")]), 0)


class SatunnaisFoldTesti(unittest.TestCase):
    def test_satunnaisvertailu_kayttaa_foldin_parametreja(self):       # A3
        d = bt.Data(kanta(600), 8)
        rek = bt.avaa_rekisteri(":memory:")
        ruudukko = [{"ikkuna": 30, "k": 3, "reb": 7}, {"ikkuna": 60, "k": 5, "reb": 30}]
        wf = bt.walk_forward("m", lambda **p: bt.momentum(**p), ruudukko, d, rek,
                             alku=date(2025, 1, 1), loppu=date(2026, 4, 10), train_pv=200, testi_pv=60)
        f = wf["foldit"]
        sat = bt.satunnaisjakauma(d, wf["ikkunat"], 3, k=[x["valittu"]["k"] for x in f],
                                  reb=[x["valittu"]["reb"] for x in f], ikkuna=[x["valittu"]["ikkuna"] for x in f])
        self.assertEqual(len(sat), 3)
        with self.assertRaises(IndexError):   # lista liian lyhyt -> ei hiljaa vaarilla parametreilla
            bt.satunnaisjakauma(d, wf["ikkunat"], 1, k=[3])

    def test_riittavasti_ei_laske_none_sharpeja(self):                 # A8e
        wf = {"mittarit": {"tuotto": 0.5, "sharpe_pa": 2.0, "max_dd": 0.1}}
        btc = {"mittarit": {"tuotto": 0.1, "sharpe_pa": 0.5}}
        sat = [{"sharpe_pa": 0.1}] * 3 + [None] * 500
        a = bt.arvio(wf, sat, btc, 1)
        self.assertFalse(a["riittavasti_satunnaisia"])         # vain 3 kelvollista


if __name__ == "__main__":
    unittest.main()
