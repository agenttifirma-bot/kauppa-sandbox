"""Automergen paatossaannot: testit, dokumentit ja testillinen pieni koodimuutos saman repon haarasta; lakitiedostot ja ajastus eivat koskaan."""
import importlib.util
import os
import unittest

_polku = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tools", "automerge.py")
if not os.path.exists(_polku):
    # Palvelinpaketti (hae.sh) ei sisalla tools/-kansiota: automerge on repon CI-tyokalu, ei tuotantokoodia.
    raise unittest.SkipTest("tools/automerge.py ei ole paketissa (vain repon CI-tyokalu)")
_spec = importlib.util.spec_from_file_location("automerge", _polku)
am = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(am)

PR = {"draft": False, "head_repo": "a/k", "base_repo": "a/k", "labels": []}


def tiedosto(nimi, status="added", changes=10):
    return {"filename": nimi, "status": status, "changes": changes}


class ArvioiTesti(unittest.TestCase):
    def ok(self, pr, tiedostot):
        return am.arvioi(pr, tiedostot)[0]

    def test_testit_ja_dokumentit_kelpaavat(self):
        self.assertTrue(self.ok(PR, [tiedosto("test_eval_k7_spec.py"), tiedosto("README.md", "modified")]))

    def test_koodi_kelpaa_vain_testin_kanssa(self):
        for nimi in ("paiva.py", "tarkistus.py", "tapahtumat.py"):
            self.assertFalse(self.ok(PR, [tiedosto(nimi, "modified")]), nimi + " ilman testia")
            self.assertTrue(self.ok(PR, [tiedosto(nimi, "modified"), tiedosto("test_tarkistus.py", "modified")]), nimi)

    def test_koodimuutos_liian_suuri(self):
        self.assertFalse(self.ok(PR, [tiedosto("paiva.py", "modified", 151), tiedosto("test_x.py")]))
        self.assertTrue(self.ok(PR, [tiedosto("paiva.py", "modified", 150), tiedosto("test_x.py")]))

    def test_lakitiedostot_eivat_kelpaa_testin_kanssakaan(self):
        for nimi in ("k7.py", "riskivahti.py"):
            self.assertFalse(self.ok(PR, [tiedosto(nimi, "modified"), tiedosto("test_k7.py", "modified")]), nimi)

    def test_suojatut_eivat_kelpaa(self):
        for nimi in ("rajat.py", "config.py", "kauppa-k7.service", "kauppa-k7.timer", ".github/workflows/ci.yml", "tools/automerge.py", ".env", "test_secret.py"):
            self.assertFalse(self.ok(PR, [tiedosto(nimi)]), nimi)

    def test_sekapr_ei_kelpaa(self):
        self.assertFalse(self.ok(PR, [tiedosto("test_x.py"), tiedosto("k7.py", "modified")]))

    def test_poisto_ja_uudelleennimeaminen_eivat_kelpaa(self):
        self.assertFalse(self.ok(PR, [tiedosto("test_x.py", "removed")]))
        self.assertFalse(self.ok(PR, [dict(tiedosto("test_x.py", "renamed"), previous_filename="k7.py")]))

    def test_koko_ja_tilat(self):
        self.assertFalse(self.ok(PR, [tiedosto("test_x.py", changes=301)]))
        self.assertFalse(self.ok(PR, [tiedosto("test_%d.py" % i) for i in range(21)]))
        self.assertFalse(self.ok(PR, []))
        self.assertFalse(self.ok(dict(PR, draft=True), [tiedosto("test_x.py")]))
        self.assertFalse(self.ok(dict(PR, labels=["ei-automerge"]), [tiedosto("test_x.py")]))
        self.assertFalse(self.ok(dict(PR, head_repo="b/k"), [tiedosto("test_x.py")]))

    def test_dokumentti_alikansiossa_ei_kelpaa(self):
        self.assertFalse(self.ok(PR, [tiedosto("docs/muistio.md")]))

    def test_polkutemput(self):
        for nimi in ("../test_x.py", "tools/../test_x.py", "alikansio/test_x.py"):
            self.assertFalse(self.ok(PR, [tiedosto(nimi)]), nimi)


if __name__ == "__main__":
    unittest.main()
