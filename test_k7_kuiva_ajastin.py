"""K7 kuiva-ajastin: ajaa vain --kuiva-tilassa, ei koskaan oikeaa K7-ajoa eika lahetä Telegramia."""
import os
import unittest

HAKEMISTO = os.path.dirname(os.path.abspath(__file__))


def lue(nimi):
    with open(os.path.join(HAKEMISTO, nimi), encoding="utf-8") as f:
        return f.read()


class KuivaAjastinTesti(unittest.TestCase):
    def test_jokainen_ajo_on_kuiva_ja_ilman_tg(self):
        ajot = [r for r in lue("kauppa-k7-kuiva.service").splitlines() if r.startswith("ExecStart=")]
        self.assertEqual(len(ajot), 2)
        for rivi in ajot:
            self.assertIn("k7.py --kuiva --malli ", rivi)
            self.assertIn("--ei-tg", rivi)
        mallit = sorted(r.split("--malli ")[1].split()[0] for r in ajot)
        self.assertEqual(mallit, ["flash", "pro"])

    def test_ei_kirjoitusta_datakansion_ulkopuolelle(self):
        s = lue("kauppa-k7-kuiva.service")
        self.assertIn("ProtectSystem=strict", s)
        self.assertIn("ReadWritePaths=/srv/kauppa/data", s)
        self.assertIn("NoNewPrivileges=true", s)
        self.assertIn("User=kauppa", s)

    def test_ajastin_ei_osu_muihin_ajoihin(self):
        t = lue("kauppa-k7-kuiva.timer")
        self.assertIn("OnCalendar=*-*-* 15:20:00", t)
        self.assertIn("OnCalendar=*-*-* 22:20:00", t)
        self.assertIn("Persistent=false", t)

    def test_viikkoajastin_ei_muutu(self):
        self.assertIn("OnCalendar=Sat *-*-* 10:00:00", lue("kauppa-k7.timer"))
        self.assertNotIn("--kuiva", lue("kauppa-k7.service"))


if __name__ == "__main__":
    unittest.main()
