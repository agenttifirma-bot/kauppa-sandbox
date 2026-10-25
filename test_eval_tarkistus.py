"""Eval-joukko tarkistus.py:lle (doc 42: keksityn faktan tarkistimen tarkkuus mitataan kasin merkityilla tapauksilla ennen kuin
'0 keksittya' kelpaa portiksi). Jokaisella tapauksella on ihmisen merkitsema oikea vastaus: keksittyja havaintoja on (True) tai ei (False).
Mittarit: tarkkuus (precision) ja osuvuus (recall). Rajat ovat vahvistettava mitta, ei hyvaksymisehto muulle kuin tarkistimelle."""
import unittest

import tarkistus

TAULUKKO = """symbol rank ret7d ret30d vol_usd
BTCUSDT 1 3.42 -8.10 1250000000
ETHUSDT 2 -1.05 4.77 640000000
SOLUSDT 3 12.30 20.45 210000000
XRPUSDT 4 0.88 -2.31 95000000
"""

# (perustelu, onko_keksittya)
TAPAUKSET = [
    ("BTCUSDT nousi 3.42 % viikossa ja on rankissa 1.", False),
    ("SOLUSDT on vahvin: 12.3 % viikossa, 20.45 % kuukaudessa.", False),
    ("Pidan 10 % kateisessa ja positiokatto on 0.2.", False),
    ("ETHUSDT laski 1.1 % viikossa, mutta kuukausituotto on 4.77 %.", False),
    ("Valitsin 3 kolikkoa 4:sta, koska rankit 1-3 ovat vahvimpia.", False),
    ("DOGEUSDT nousi vahvasti, ostan sita.", True),
    ("BTCUSDT nousi 7.9 % viikossa.", True),
    ("XRPUSDT:n volyymi on 450000000, joten likviditeetti on hyva.", True),
    ("SOLUSDT tuotto 20.45 % ja AVAXUSDT 15.2 % tukevat trendia.", True),
    ("ETHUSDT on rankissa 2 ja sen 30 paivan tuotto on 12.9 %.", True),
    # Tunnettu sokea piste: kokonaisluvut 0..100 sallitaan aina (lukumaarat, rankit), joten keksitty kokonaisluku ei jää kiinni.
    ("ETHUSDT nousi 45 % viikossa.", True),
    ("SOLUSDT on rankissa 9, joten se on heikoin.", True),
    ("", False),
    ("Ei muutosta, markkina on epavarma.", False),
]


def _keksitty(perustelu):
    return len(tarkistus.tarkista_perustelu(perustelu, TAULUKKO)) > 0


class TarkistinEval(unittest.TestCase):
    def test_tarkkuus_ja_osuvuus(self):
        tp = fp = fn = tn = 0
        eroavat = []
        for teksti, oikea in TAPAUKSET:
            ennuste = _keksitty(teksti)
            if ennuste and oikea:
                tp += 1
            elif ennuste and not oikea:
                fp += 1
                eroavat.append(("vaara halytys", teksti))
            elif not ennuste and oikea:
                fn += 1
                eroavat.append(("jai huomaamatta", teksti))
            else:
                tn += 1
        tarkkuus = tp / (tp + fp) if tp + fp else 1.0
        osuvuus = tp / (tp + fn) if tp + fn else 1.0
        self.assertGreaterEqual(tarkkuus, 0.9, eroavat)
        self.assertGreaterEqual(osuvuus, 0.7, eroavat)  # sokeat pisteet huomioiden; nosta kun tarkistin paranee


if __name__ == "__main__":
    unittest.main()
