import json
import unittest
from datetime import date, timedelta

import agentit
import config
import llm
import paiva
import rajat
import salkku
import taulukko
from test_k2 import luo_kanta, D, D_MS, PV

ENV = {"LLM_BASE_URL": "http://x/v1", "LLM_API_KEY": "avain"}
SYM = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]


def valemalli(vastaukset):
    """Palauttaa hae-funktion joka antaa vastaukset jarjestyksessa (analyytikko, kriitikko)."""
    jono = list(vastaukset)
    kutsut = []

    def hae(url, avain, payload):
        kutsut.append(payload)
        v = jono.pop(0)
        if isinstance(v, Exception):
            raise v
        return {"choices": [{"message": {"content": v}}], "usage": {"prompt_tokens": 10, "completion_tokens": 5}}
    hae.kutsut = kutsut
    return hae


A = json.dumps({"paino": {"BTCUSDT": 0.10, "ETHUSDT": 0.10}, "perustelu": "momentum", "luottamus": "keskitaso"})
K_OK = json.dumps({"paatos": "hyvaksy", "ongelmat": []})


class JasennysTesti(unittest.TestCase):
    def test_json_koodiaidasta(self):
        o = agentit.pura_json("```json\n{\"a\": 1}\n```")
        self.assertEqual(o, {"a": 1})

    def test_huonot(self):
        for h in ("ei jsonia", "{rikki", "[1,2]", ""):
            with self.assertRaises(agentit.Vastausvirhe):
                agentit.pura_json(h)

    def test_analyytikko_skeemat(self):
        self.assertTrue(agentit.jasenna_analyytikko('{"en_tieda": true, "syy": "data"}')["en_tieda"])
        a = agentit.jasenna_analyytikko(A)
        self.assertEqual(a["paino"]["BTCUSDT"], 0.10)
        for huono in ('{"paino": []}', '{"paino": {"BTCUSDT": "0.1"}}', '{"paino": {"BTCUSDT": true}}', '{}'):
            with self.assertRaises(agentit.Vastausvirhe):
                agentit.jasenna_analyytikko(huono)

    def test_kriitikko(self):
        k = agentit.jasenna_kriitikko('{"paatos": "pienenna", "kerroin": 0.5, "ongelmat": ["a"]}')
        self.assertEqual(agentit.sovella_kriitikko({"BTCUSDT": 0.1}, k), {"BTCUSDT": 0.05})
        self.assertIsNone(agentit.sovella_kriitikko({"BTCUSDT": 0.1}, agentit.jasenna_kriitikko('{"paatos": "hylkaa"}')))
        for huono in ('{"paatos": "kasvata"}', '{"paatos": "pienenna", "kerroin": 1.5}',
                      '{"paatos": "pienenna"}', '{"paatos": "pienenna", "kerroin": true}'):
            with self.assertRaises(agentit.Vastausvirhe):
                agentit.jasenna_kriitikko(huono)

    def test_kriitikko_ei_voi_kasvattaa(self):
        k = {"paatos": "hyvaksy", "kerroin": 5.0, "ongelmat": []}  # kerroin ohitetaan hyvaksy-tilassa
        self.assertEqual(agentit.sovella_kriitikko({"BTCUSDT": 0.1}, k), {"BTCUSDT": 0.1})


class LLMTesti(unittest.TestCase):
    def test_virheet(self):
        with self.assertRaises(llm.LLMVirhe):
            llm.kysy([], "m", {}, valemalli(["x"]))
        with self.assertRaises(llm.LLMVirhe):
            llm.kysy([], "m", ENV, valemalli([""]))
        with self.assertRaises(llm.LLMVirhe):
            llm.kysy([], "m", ENV, lambda *a: {"huono": 1})

    def test_avain_ei_payloadissa(self):
        hae = valemalli(["{}"])
        llm.kysy([{"role": "user", "content": "x"}], "m", ENV, hae)
        self.assertNotIn("avain", json.dumps(hae.kutsut))


class PutkiTesti(unittest.TestCase):
    def setUp(self):
        self.mk = luo_kanta(SYM, paivia=140, loppu_ms=D_MS + PV)  # paivan D kynttila mukana
        self.sal = salkku.avaa(":memory:")
        self._s = config.SYMBOLIT
        config.SYMBOLIT = SYM

    def tearDown(self):
        config.SYMBOLIT = self._s

    def test_normaali_ajo(self):
        hae = valemalli([A, K_OK])
        t = paiva.aja_paiva(D, "deepseek-flash", self.mk, self.sal, ENV, hae)
        self.assertIsNone(t["virhe"])
        self.assertEqual(len(t["sim"]["kaupat"]), 2)
        self.assertEqual(len(hae.kutsut), 2)
        # taulukko on mallin viestissa, ei avainta
        self.assertIn("<data", hae.kutsut[0]["messages"][1]["content"])
        txt = paiva.raportti(t, self.sal, self.mk)
        self.assertIn("Salkku", txt)

    def test_en_tieda_ei_kauppoja_eika_kriitikkoa(self):
        hae = valemalli(['{"en_tieda": true, "syy": "epaselva"}'])
        t = paiva.aja_paiva(D, "m", self.mk, self.sal, ENV, hae)
        self.assertEqual(t["sim"]["kaupat"], [])
        self.assertEqual(len(hae.kutsut), 1)

    def test_kriitikko_hylkaa(self):
        t = paiva.aja_paiva(D, "m", self.mk, self.sal, ENV, valemalli([A, '{"paatos": "hylkaa"}']))
        self.assertEqual(t["sim"]["kaupat"], [])

    def test_llm_virhe_fail_closed(self):
        t = paiva.aja_paiva(D, "m", self.mk, self.sal, ENV, valemalli([llm.LLMVirhe("HTTP 500")]))
        self.assertEqual(t["sim"]["kaupat"], [])
        self.assertIn("LLMVirhe", t["virhe"])

    def test_huono_json_fail_closed(self):
        t = paiva.aja_paiva(D, "m", self.mk, self.sal, ENV, valemalli(["en osaa"]))
        self.assertEqual(t["sim"]["kaupat"], [])
        self.assertIn("Vastausvirhe", t["virhe"])

    def test_kielletty_kolikko_hylataan(self):
        a = json.dumps({"paino": {"DOGEUSDT": 0.1}, "perustelu": "x", "luottamus": "korkea"})
        t = paiva.aja_paiva(D, "m", self.mk, self.sal, ENV, valemalli([a, K_OK]))
        self.assertEqual(t["sim"]["kaupat"], [])
        self.assertTrue(any("HYLATTY" in h for h in t["sim"]["huomautukset"]))

    def test_paivakatto(self):
        raja, rajat.MAX_LLM_KUTSUJA_PAIVA = rajat.MAX_LLM_KUTSUJA_PAIVA, 1
        try:
            t = paiva.aja_paiva(D, "m", self.mk, self.sal, ENV, valemalli([A, K_OK]))
        finally:
            rajat.MAX_LLM_KUTSUJA_PAIVA = raja
        self.assertIn("kutsukatto", t["virhe"])
        self.assertEqual(t["sim"]["kaupat"], [])

    def test_datan_puute_keskeyttaa(self):
        with self.assertRaises(salkku.Datavirhe):
            paiva.aja_paiva(D + timedelta(days=30), "m", self.mk, self.sal, ENV, valemalli([A, K_OK]))

    def test_viimeisin_paiva(self):
        self.assertEqual(paiva.viimeisin_paiva(self.mk), D)


if __name__ == "__main__":
    unittest.main()
