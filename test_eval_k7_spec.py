"""Eval-joukko K7:n spec-portille (tarkista_spec): tyypilliset mallin ehdotukset kasin merkittyina kelvollisiksi tai kelvottomiksi.
Mittaa: (1) portti hylkaa kaikki kelvottomat (turvallisuus), (2) hyvaksyy kaikki kelvolliset (ei turhaa hukkaa),
(3) samaan strategiaan johtavat eri kirjoitusasut saavat saman hashin (ei tuplia rekisteriin)."""
import unittest

import k7
from test_k7 import spec_dict

HYP_OK = "Ylimyydyt kolikot palautuvat lyhyella aikavalilla likviditeettishokin jalkeen"

KELVOLLISET = {
    "perus": spec_dict(),
    "yksi_ruudukkoparametri": spec_dict(kiinteat={"signaali": "momentum", "suunta": "korkea", "osuus": 0.8, "suodin": "ei",
                                                  "suodin_toiminto": "kateinen", "k": 5, "reb": 7}, ruudukko={"ikkuna": [7, 14]}),
    "suodin_btc": spec_dict(kiinteat={"signaali": "volatiliteetti", "suunta": "matala", "osuus": 0.5, "suodin": "sma100",
                                      "suodin_toiminto": "btc", "ikkuna": 30, "k": 6, "reb": 14}, ruudukko={}),
    "isot_kirjaimet_nimessa": spec_dict(nimi="Matala VOL!! 2"),
}

KELVOTTOMAT = {
    "ei_dict": ["momentum"],
    "nimi_puuttuu": spec_dict(nimi=""),
    "lyhyt_hypoteesi": spec_dict(hypoteesi="toimii"),
    "tuntematon_parametri_stop_loss": spec_dict(kiinteat={"signaali": "momentum", "suunta": "matala", "osuus": 0.7, "suodin": "ei",
                                                          "suodin_toiminto": "kateinen", "stop_loss": 0.1}),
    "tuntematon_signaali": spec_dict(kiinteat={"signaali": "rsi", "suunta": "matala", "osuus": 0.7, "suodin": "ei", "suodin_toiminto": "kateinen"}),
    "float_kokonaisluvun_tilalla": spec_dict(ruudukko={"ikkuna": [7.0, 14], "k": [5, 8], "reb": [7]}),
    "merkkijono_luvun_tilalla": spec_dict(ruudukko={"ikkuna": ["7", "14"], "k": [5, 8], "reb": [7]}),
    "bool_luvun_tilalla": spec_dict(ruudukko={"ikkuna": [True, 14], "k": [5, 8], "reb": [7]}),
    "arvo_ei_listalla": spec_dict(ruudukko={"ikkuna": [7, 21], "k": [5, 8], "reb": [7]}),
    "ruudukko_liian_suuri": spec_dict(ruudukko={"ikkuna": [7, 14, 30], "k": [5, 6, 8], "reb": [3, 7, 14]}),
    "koodi_arvona": spec_dict(kiinteat={"signaali": "__import__('os').system('x')", "suunta": "matala", "osuus": 0.7, "suodin": "ei", "suodin_toiminto": "kateinen"}),
    "pakollinen_puuttuu": spec_dict(kiinteat={"signaali": "momentum", "suunta": "matala", "osuus": 0.7}, ruudukko={"ikkuna": [7, 14]}),
    "sama_kiintea_ja_ruudukko": spec_dict(ruudukko={"osuus": [0.5, 0.7], "ikkuna": [7, 14], "k": [5], "reb": [7]}),
    "ruudukkoon_ei_sallittu_param": spec_dict(kiinteat={"signaali": "momentum", "osuus": 0.7, "suodin": "ei", "suodin_toiminto": "kateinen"},
                                              ruudukko={"suunta": ["korkea", "matala"], "ikkuna": [7], "k": [5], "reb": [7]}),
    "tyhja_ruudukko": spec_dict(ruudukko={"ikkuna": [], "k": [5], "reb": [7]}),
}


def _hyvaksytty(o):
    try:
        k7.tarkista_spec(o)
        return True
    except k7.Speksivirhe:
        return False


class SpecPorttiEval(unittest.TestCase):
    def test_kelvottomat_hylataan(self):
        paasi = [n for n, o in KELVOTTOMAT.items() if _hyvaksytty(o)]
        self.assertEqual(paasi, [], "portti paasti lapi kelvottomia")

    def test_kelvolliset_hyvaksytaan(self):
        hylatyt = [n for n, o in KELVOLLISET.items() if not _hyvaksytty(o)]
        self.assertEqual(hylatyt, [], "portti hylkasi kelvollisia")

    def test_eri_kirjoitusasu_sama_hash(self):
        a = k7.tarkista_spec(spec_dict(ruudukko={"ikkuna": [14, 7], "k": [5, 8], "reb": [7]}))
        b = k7.tarkista_spec(spec_dict(nimi="Toinen Nimi", ruudukko={"reb": [7, 7], "k": [8, 5, 5], "ikkuna": [7, 14]}))
        self.assertEqual(k7.spec_hash(a), k7.spec_hash(b))
        # suodin 'ei' + btc-toiminto = sama kuin kateinen
        c = k7.tarkista_spec(spec_dict(kiinteat={"signaali": "momentum", "suunta": "matala", "osuus": 0.7, "suodin": "ei", "suodin_toiminto": "btc"}))
        d = k7.tarkista_spec(spec_dict(kiinteat={"signaali": "momentum", "suunta": "matala", "osuus": 0.7, "suodin": "ei", "suodin_toiminto": "kateinen"}))
        self.assertEqual(k7.spec_hash(c), k7.spec_hash(d))


if __name__ == "__main__":
    unittest.main()
