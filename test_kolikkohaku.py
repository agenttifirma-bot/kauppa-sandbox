import os
import tempfile
import unittest
from datetime import date

import kolikkohaku as kh


def xml(prefixit=(), avaimet=(), katkaistu=False, nm=None):
    s = '<?xml version="1.0"?><ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">'
    s += "<IsTruncated>%s</IsTruncated>" % ("true" if katkaistu else "false")
    if nm:
        s += "<NextMarker>%s</NextMarker>" % nm
    for p in prefixit:
        s += "<CommonPrefixes><Prefix>%s</Prefix></CommonPrefixes>" % p
    for a in avaimet:
        s += "<Contents><Key>%s</Key></Contents>" % a
    return (s + "</ListBucketResult>").encode()


class HakuTesti(unittest.TestCase):
    def test_symbolit_suodatus(self):
        p = ["data/spot/monthly/klines/%s/" % x for x in ("BTCUSDT", "USDCUSDT", "BTCUPUSDT", "LUNAUSDT", "ETHBTC", "SOLUSDT", "FDUSDUSDT")]
        self.assertEqual(kh.symbolit(lambda u: xml(prefixit=p)), ["BTCUSDT", "LUNAUSDT", "SOLUSDT"])

    def test_kuukaudet_ohittaa_checksum(self):
        a = ["x/LUNAUSDT-1d-2022-03.zip", "x/LUNAUSDT-1d-2022-03.zip.CHECKSUM", "x/LUNAUSDT-1d-2022-04.zip", "x/LUNAUSDT-1d-2021-11.zip"]
        self.assertEqual(kh.kuukaudet(a), [(2021, 11), (2022, 3), (2022, 4)])

    def test_sivutus(self):
        sivut = [xml(avaimet=["a-1d-2022-01.zip"], katkaistu=True, nm="a-1d-2022-01.zip"), xml(avaimet=["a-1d-2022-02.zip"])]
        kutsut = []

        def hae(u):
            kutsut.append(u)
            return sivut[len(kutsut) - 1]
        _, avaimet = kh.listaa("p/", "", hae)
        self.assertEqual(len(avaimet), 2)
        self.assertIn("marker=a-1d-2022-01.zip", kutsut[1])

    def test_sivutus_ilman_nextmarker_kayttaa_viimeista_avainta(self):
        sivut = [xml(avaimet=["k1", "k2"], katkaistu=True), xml(avaimet=["k3"])]
        kutsut = []

        def hae(u):
            kutsut.append(u)
            return sivut[len(kutsut) - 1]
        _, avaimet = kh.listaa("p/", "", hae)
        self.assertEqual(avaimet, ["k1", "k2", "k3"])
        self.assertIn("marker=k2", kutsut[1])

    def test_ei_xml_kaatuu_selvasti(self):
        with self.assertRaises(kh.Hakuvirhe):
            kh.listaa("p/", "/", lambda u: b"<html>ei")

    def test_kuollut_raja(self):
        t = date(2026, 10, 16)
        self.assertTrue(kh.kuollut((2022, 6), t))
        self.assertTrue(kh.kuollut((2026, 7), t))
        self.assertFalse(kh.kuollut((2026, 8), t))
        self.assertFalse(kh.kuollut((2026, 9), t))

    def test_main_kirjoittaa_csv(self):
        def hae(u):
            if "klines%2FLUNAUSDT" in u or "LUNAUSDT" in u:
                return xml(avaimet=["data/spot/monthly/klines/LUNAUSDT/1d/LUNAUSDT-1d-2022-03.zip", "data/spot/monthly/klines/LUNAUSDT/1d/LUNAUSDT-1d-2022-04.zip"])
            if "BTCUSDT" in u:
                return xml(avaimet=["data/spot/monthly/klines/BTCUSDT/1d/BTCUSDT-1d-2021-10.zip", "data/spot/monthly/klines/BTCUSDT/1d/BTCUSDT-1d-2026-09.zip"])
            return xml(prefixit=["data/spot/monthly/klines/BTCUSDT/", "data/spot/monthly/klines/LUNAUSDT/"])
        with tempfile.TemporaryDirectory() as d:
            polku = os.path.join(d, "s.csv")
            r = kh.main(hae, date(2026, 10, 16), polku, 0)
            self.assertEqual(r, 0)
            with open(polku) as f:
                rivit = f.read().splitlines()
        self.assertEqual(rivit[0], "symbol,eka_kk,vika_kk,kuukausia,kuollut")
        self.assertIn("LUNAUSDT,2022-03,2022-04,2,1", rivit)
        self.assertIn("BTCUSDT,2021-10,2026-09,2,0", rivit)

    def test_main_virhe_palauttaa_1(self):
        def hae(u):
            if "BTCUSDT/1d" in urllib_unquote(u):
                raise kh.Hakuvirhe("x")
            return xml(prefixit=["data/spot/monthly/klines/BTCUSDT/"])
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(kh.main(hae, date(2026, 10, 16), os.path.join(d, "s.csv"), 0), 1)


def urllib_unquote(u):
    import urllib.parse
    return urllib.parse.unquote(u)


if __name__ == "__main__":
    unittest.main()
