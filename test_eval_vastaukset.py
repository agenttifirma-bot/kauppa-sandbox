"""Eval-joukko analyytikon ja kriitikon vastausportille (agentit.jasenna_*): tyypilliset mallivastaukset kasin merkittyina.
Mittaa: kelvolliset menevat lapi (ei turhaa fail-closed-paivaa) ja kelvottomat hylataan (ei epailyttavia painoja salkkuun).
Lisaksi omaisuus: kriitikko ei koskaan kasvata painoja."""
import unittest

import agentit

ANALYYTIKKO_OK = {
    "puhdas": '{"paino": {"BTCUSDT": 0.5, "ETHUSDT": 0.3}, "perustelu": "BTC vahva", "luottamus": "korkea"}',
    "markdown_aita": '```json\n{"paino": {"BTCUSDT": 0.4}, "perustelu": "x", "luottamus": "matala"}\n```',
    "proosa_ymparilla": 'Tassa ehdotus:\n{"paino": {"SOLUSDT": 0.2}, "perustelu": "momentum"}\nKiitos.',
    "en_tieda": '{"en_tieda": true, "syy": "data puutteellinen"}',
    "tyhja_paino": '{"paino": {}, "perustelu": "kaikki kateiseen"}',
    "kokonaisluku_paino": '{"paino": {"BTCUSDT": 1}, "perustelu": "x"}',
    "lista_kaarittyna": '[{"paino": {"BTCUSDT": 0.2}, "perustelu": "x"}]',   # pura_json poimii olion; hyvaksytaan tarkoituksella
    "tuntematon_luottamus": '{"paino": {"BTCUSDT": 0.1}, "luottamus": "erittain"}',
}
ANALYYTIKKO_VIRHE = {
    "ei_jsonia": "En osaa sanoa mitaan tasta.",
    "rikkinainen": '{"paino": {"BTCUSDT": 0.5,',
    "paino_puuttuu": '{"perustelu": "x"}',
    "paino_lista": '{"paino": ["BTCUSDT", 0.5]}',
    "paino_merkkijono": '{"paino": {"BTCUSDT": "0.5"}}',
    "paino_bool": '{"paino": {"BTCUSDT": true}}',
    "paino_null": '{"paino": {"BTCUSDT": null}}',
    "en_tieda_merkkijono": '{"en_tieda": "true"}',
}
KRIITIKKO_OK = {
    "hyvaksy": '{"paatos": "hyvaksy", "ongelmat": []}',
    "pienenna": '{"paatos": "pienenna", "kerroin": 0.5, "ongelmat": ["keskittyminen"]}',
    "hylkaa": '{"paatos": "hylkaa", "ongelmat": ["data"]}',
    "aita": '```json\n{"paatos": "hyvaksy"}\n```',
    "kerroin_rajalla": '{"paatos": "pienenna", "kerroin": 1.0}',
}
KRIITIKKO_VIRHE = {
    "tuntematon_paatos": '{"paatos": "kasvata", "kerroin": 1.5}',
    "kerroin_yli": '{"paatos": "pienenna", "kerroin": 1.5}',
    "kerroin_negatiivinen": '{"paatos": "pienenna", "kerroin": -0.2}',
    "kerroin_puuttuu": '{"paatos": "pienenna"}',
    "kerroin_merkkijono": '{"paatos": "pienenna", "kerroin": "0.5"}',
    "kerroin_bool": '{"paatos": "pienenna", "kerroin": true}',
    "ei_jsonia": "Hyvaksyn.",
}


def _ok(f, teksti):
    try:
        f(teksti)
        return True
    except agentit.Vastausvirhe:
        return False


class VastausPorttiEval(unittest.TestCase):
    def test_kelvolliset_menevat_lapi(self):
        hylatyt = [n for n, t in ANALYYTIKKO_OK.items() if not _ok(agentit.jasenna_analyytikko, t)]
        hylatyt += [n for n, t in KRIITIKKO_OK.items() if not _ok(agentit.jasenna_kriitikko, t)]
        self.assertEqual(hylatyt, [])

    def test_kelvottomat_hylataan(self):
        lapi = [n for n, t in ANALYYTIKKO_VIRHE.items() if _ok(agentit.jasenna_analyytikko, t)]
        lapi += [n for n, t in KRIITIKKO_VIRHE.items() if _ok(agentit.jasenna_kriitikko, t)]
        self.assertEqual(lapi, [])

    def test_nan_ja_inf_eivat_paase_salkkuun(self):
        """Pythonin json hyvaksyy NaN/Infinity. Parseri paastaa ne lapi, mutta riskivahti (toinen kerros) hylkaa ne -> ei kauppoja.
        Testi lukitsee syvyyspuolustuksen: jos jompikumpi kerros hylkaa, paino ei paase salkkuun."""
        import riskivahti
        for arvo in ("NaN", "Infinity", "-Infinity", "1e999"):
            teksti = '{"paino": {"BTCUSDT": %s}, "perustelu": "x"}' % arvo
            try:
                painot = agentit.jasenna_analyytikko(teksti)["paino"]
            except agentit.Vastausvirhe:
                continue
            with self.assertRaises(riskivahti.Ehdotusvirhe, msg=arvo):
                riskivahti.siisti_ehdotus(painot, {"BTCUSDT"})

    def test_kriitikko_ei_koskaan_kasvata(self):
        painot = {"BTCUSDT": 0.5, "ETHUSDT": 0.3}
        for t in KRIITIKKO_OK.values():
            tulos = agentit.sovella_kriitikko(painot, agentit.jasenna_kriitikko(t))
            if tulos is None:
                continue
            for s, w in tulos.items():
                self.assertLessEqual(w, painot[s] + 1e-12, t)


if __name__ == "__main__":
    unittest.main()
