import unittest

import tarkistus as tk

TAULUKKO = """<data paiva="2026-10-25" viimeisin_suljettu="2026-10-24" yksikko="x">
symbol | close | r7% | r30% | r90% | vol30%pa | dd90% | corrBTC60 | fund7%pa | fund30%pa | mom_ranki_r90
BTCUSDT | 67000 | 1.2 | 5.4 | 12.8 | 41.0 | -8.3 | 1.00 | 3.1 | 4.2 | 3
SOLUSDT | 182.5 | 4.0 | 18.7 | 55.1 | 80.2 | -12.0 | 0.85 | 9.0 | 7.7 | 1
universumi 2 kolikkoa; r30-mediaani 12.0%; positiivisia r30: 2/2
</data>"""


class TarkistusTesti(unittest.TestCase):
    def test_taulukon_arvot_eivat_ole_keksittyja(self):
        self.assertEqual(tk.tarkista_perustelu("SOLUSDT r90 55.1 % ja ranki 1; BTCUSDT vol30 41 %", TAULUKKO), [])

    def test_pyoristys_sallitaan(self):
        self.assertEqual(tk.tarkista_perustelu("SOLUSDT r90 noin 55 %, r30 18.7", TAULUKKO), [])

    def test_keksitty_luku_liputetaan(self):
        self.assertEqual(tk.tarkista_perustelu("SOLUSDT r90 oli 61.4 %", TAULUKKO), ["luku:61.4"])

    def test_tuntematon_symboli_liputetaan(self):
        self.assertEqual(tk.tarkista_perustelu("FOOUSDT nousee", TAULUKKO), ["symboli:FOOUSDT"])

    def test_vakiot_ja_pienet_kokonaisluvut_sallitaan(self):
        self.assertEqual(tk.tarkista_perustelu("kulu 0.2 %, positiokatto 0.15, 3 kolikkoa, 90 pv", TAULUKKO), [])

    def test_iso_kokonaisluku_ilman_osumaa_liputetaan(self):
        self.assertEqual(tk.tarkista_perustelu("hinta 70000", TAULUKKO), ["luku:70000"])

    def test_tyhja_tai_ei_tekstia_ei_kaada(self):
        self.assertEqual(tk.tarkista_perustelu(None, TAULUKKO), [])
        self.assertEqual(tk.tarkista_perustelu("", TAULUKKO), [])
        self.assertEqual(tk.tarkista_perustelu("teksti ilman lukuja", ""), [])

    def test_pilkkudesimaali(self):
        self.assertEqual(tk.tarkista_perustelu("r30 18,7 %", TAULUKKO), [])


if __name__ == "__main__":
    unittest.main()
