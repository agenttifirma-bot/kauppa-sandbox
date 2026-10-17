"""Regressio 17.10.2026: palvelimen config.SYMBOLIT palautui 20 kolikkoon, ja PEPE/ENA/TAO/ZEC jai lataamatta
-> salkut eivat saaneet hintaa omistetuille kolikoille -> DATAVIRHE. Lista on lukittu: 26 kolikkoa."""
import re
import unittest

import config


class TestSymbolit(unittest.TestCase):
    def test_26_kolikkoa_ei_duplikaatteja(self):
        self.assertEqual(len(config.SYMBOLIT), 26)
        self.assertEqual(len(set(config.SYMBOLIT)), 26)

    def test_lisatyt_kolikot_mukana(self):
        for s in ("ZECUSDT", "ENAUSDT", "PEPEUSDT", "HYPEUSDT", "WLDUSDT", "TAOUSDT"):
            self.assertIn(s, config.SYMBOLIT)

    def test_nimet_kelvollisia(self):
        for s in config.SYMBOLIT:
            self.assertRegex(s, r"^[A-Z0-9]+USDT$")

    def test_futures_nimet_listalla(self):
        for s in config.FUTURES_NIMI:
            self.assertIn(s, config.SYMBOLIT)


if __name__ == "__main__":
    unittest.main()
