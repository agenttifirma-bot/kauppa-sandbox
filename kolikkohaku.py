"""K1b osa 1 (VAIN LUKU): selvittaa data.binance.vision-arkistosta kaikki USDT-spot-parit ja milloin kullakin on
paivadataa (ensimmainen ja viimeinen kuukausi). Tarkoitus: nahda kuolleet kolikot (selviytymisharhan korjaus).
Ei kirjoita tietokantaan, ei kosketa kauppoihin. Tulos: CSV + yhteenveto. Ajo: python3 kolikkohaku.py"""
import csv
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date

LISTA_BASE = os.environ.get("KAUPPA_LISTA_BASE", "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision")
ULOS = os.environ.get("KAUPPA_SYMBOLIT_CSV", "/srv/kauppa/data/symbolit_historia.csv")
PREFIX = "data/spot/monthly/klines/"
MAX_VASTAUS = 5_000_000
AIKAKATKAISU = 30
YRITYKSET = 3
PAUSSI = 0.15
MAX_SIVUJA = 50          # per listaus (1000 rivia/sivu)

# ei kaupankaynnin kohteita: vakaakolikot, vipu-tokenit
VAKAAT = {"USDC", "FDUSD", "TUSD", "BUSD", "USDP", "DAI", "USDD", "USDS", "PAXG", "EUR", "EURI", "AEUR", "UST", "USTC", "BKRW", "XUSD", "USD1", "RLUSD"}
VIPU = re.compile(r"(UP|DOWN|BULL|BEAR)$")
KK = re.compile(r"-1d-(\d{4})-(\d{2})\.zip$")


class Hakuvirhe(Exception):
    pass


def _hae(url):
    viimeinen = None
    for y in range(YRITYKSET):
        try:
            pyynto = urllib.request.Request(url, headers={"User-Agent": "kauppatiimi-k1b/1.0"})
            with urllib.request.urlopen(pyynto, timeout=AIKAKATKAISU) as v:
                data = v.read(MAX_VASTAUS + 1)
            if len(data) > MAX_VASTAUS:
                raise Hakuvirhe("liian suuri vastaus")
            return data
        except urllib.error.HTTPError as e:
            viimeinen = "HTTP %s" % e.code
            if e.code in (400, 403, 404):
                break
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            viimeinen = type(e).__name__
        time.sleep(1.5 * (y + 1))
    raise Hakuvirhe("%s: %s" % (url, viimeinen))


def _nimi(tag):
    return tag.rsplit("}", 1)[-1]


def listaa(prefix, delimiter="/", hae=_hae):
    """S3-listaus. Palauttaa (alihakemistot, avaimet). Sivutus markerilla."""
    prefixit, avaimet, marker = [], [], ""
    for _ in range(MAX_SIVUJA):
        q = {"prefix": prefix, "max-keys": "1000"}
        if delimiter:
            q["delimiter"] = delimiter
        if marker:
            q["marker"] = marker
        data = hae(LISTA_BASE + "?" + urllib.parse.urlencode(q))
        try:
            juuri = ET.fromstring(data)
        except ET.ParseError:
            raise Hakuvirhe("listaus ei ole XML-vastaus")
        katkaistu, seuraava, viimeinen_avain = False, "", ""
        for el in juuri:
            n = _nimi(el.tag)
            if n == "IsTruncated":
                katkaistu = (el.text or "").strip().lower() == "true"
            elif n == "NextMarker":
                seuraava = el.text or ""
            elif n == "CommonPrefixes":
                for p in el:
                    if _nimi(p.tag) == "Prefix" and p.text:
                        prefixit.append(p.text)
            elif n == "Contents":
                for k in el:
                    if _nimi(k.tag) == "Key" and k.text:
                        avaimet.append(k.text)
                        viimeinen_avain = k.text
        if not katkaistu:
            return prefixit, avaimet
        marker = seuraava or viimeinen_avain or (prefixit[-1] if prefixit else "")
        if not marker:
            raise Hakuvirhe("sivutus ei etene")
    raise Hakuvirhe("liian monta sivua")


def kelvollinen_symboli(s):
    if not re.fullmatch(r"[A-Z0-9]{2,20}USDT", s):
        return False
    pohja = s[:-4]
    return pohja not in VAKAAT and not VIPU.search(pohja)


def symbolit(hae=_hae):
    prefixit, _ = listaa(PREFIX, "/", hae)
    ulos = []
    for p in prefixit:
        s = p[len(PREFIX):].strip("/")
        if kelvollinen_symboli(s):
            ulos.append(s)
    return sorted(ulos)


def kuukaudet(avaimet):
    """Palauttaa lajitellun listan (vuosi, kk) avaimista; ohittaa .CHECKSUM-tiedostot."""
    ulos = set()
    for a in avaimet:
        m = KK.search(a)
        if m:
            ulos.add((int(m.group(1)), int(m.group(2))))
    return sorted(ulos)


def historia(s, hae=_hae):
    _, avaimet = listaa("%s%s/1d/" % (PREFIX, s), "", hae)
    kk = kuukaudet(avaimet)
    if not kk:
        return None
    return kk[0], kk[-1], len(kk)


def _kk_str(t):
    return "%04d-%02d" % t


def kuollut(vika, tanaan=None):
    """Kuollut = viimeisin kuukausiarkisto vahintaan 3 kuukautta vanha (arkisto julkaistaan kuukausittain)."""
    tanaan = tanaan or date.today()
    ero = (tanaan.year - vika[0]) * 12 + (tanaan.month - vika[1])
    return ero >= 3


def main(hae=_hae, tanaan=None, ulos=None, paussi=PAUSSI):
    ulos = ulos or ULOS
    syms = symbolit(hae)
    print("USDT-pareja (ilman vakaita ja vipu-tokeneita): %d" % len(syms))
    rivit, ohitettu = [], 0
    for i, s in enumerate(syms):
        try:
            h = historia(s, hae)
        except Hakuvirhe as e:
            print("VIRHE %s: %s" % (s, e))
            ohitettu += 1
            continue
        if h:
            rivit.append((s, _kk_str(h[0]), _kk_str(h[1]), h[2], int(kuollut(h[1], tanaan))))
        time.sleep(paussi)
        if (i + 1) % 100 == 0:
            print("  ... %d/%d" % (i + 1, len(syms)))
    tmp = ulos + ".tmp"
    with open(tmp, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["symbol", "eka_kk", "vika_kk", "kuukausia", "kuollut"])
        w.writerows(rivit)
    os.replace(tmp, ulos)
    kuolleet = [r for r in rivit if r[4]]
    print("Symboleja datalla: %d, joista kuolleita (ei dataa viimeiseen 3 kk): %d, haku epaonnistui: %d" % (len(rivit), len(kuolleet), ohitettu))
    ennen_2022 = [r for r in rivit if r[1] <= "2021-10"]
    print("Noteerattuja jo 2021-10 tai aiemmin: %d" % len(ennen_2022))
    print("Kuolleita, joilla yli 12 kk dataa (esimerkkeja, enintaan 25):")
    for r in sorted(kuolleet, key=lambda r: -r[3])[:25]:
        print("  %s %s..%s (%d kk)" % (r[0], r[1], r[2], r[3]))
    print("CSV: %s" % ulos)
    return 0 if ohitettu == 0 and rivit else 1


if __name__ == "__main__":
    sys.exit(main())
