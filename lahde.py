"""Datan haku (data.binance.vision + julkinen funding-REST) ja jasennys. Ei API-avaimia."""
import csv
import io
import json
import time
import urllib.error
import urllib.request
import zipfile

import config


class Verkkovirhe(Exception):
    pass


class Estetty(Exception):
    """HTTP 451: alue estetty. Ei yriteta kiertaa."""


class Parsevirhe(Exception):
    pass


def http_hae(url):
    """Palauttaa bytes tai None (404/403/400 = ei loydy). Nostaa Verkkovirhe/Estetty."""
    viimeinen = None
    for yritys in range(config.YRITYKSET):
        try:
            pyynto = urllib.request.Request(url, headers={"User-Agent": "kauppatiimi-k1/1.0"})
            with urllib.request.urlopen(pyynto, timeout=config.AIKAKATKAISU) as v:
                data = v.read(config.MAX_ZIP + 1)
            if len(data) > config.MAX_ZIP:
                raise Verkkovirhe("liian suuri vastaus")
            return data
        except urllib.error.HTTPError as e:
            if e.code in (400, 403, 404):
                return None
            if e.code == 451:
                raise Estetty(url)
            viimeinen = "HTTP %s" % e.code
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            viimeinen = type(e).__name__
        time.sleep(1.5 * (yritys + 1))
    raise Verkkovirhe("%s: %s" % (url, viimeinen))


def pura_zip(data):
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            nimet = z.namelist()
            if len(nimet) != 1:
                raise Parsevirhe("zipissa %d tiedostoa" % len(nimet))
            if z.getinfo(nimet[0]).file_size > config.MAX_PURETTU:
                raise Parsevirhe("purettu liian suuri")
            return z.read(nimet[0]).decode("utf-8")
    except zipfile.BadZipFile:
        raise Parsevirhe("rikkinainen zip")
    except UnicodeDecodeError:
        raise Parsevirhe("ei utf-8")


def _ms(x):
    v = int(x)
    if v > 10 ** 14:  # Binance spot siirtyi mikrosekunteihin 2025
        v //= 1000
    return v


def parse_klines(teksti):
    """Palauttaa listan (ts,o,h,l,c,v,qv,n). Yksikin virheellinen rivi hylkaa koko tiedoston."""
    ulos = []
    for rivi in csv.reader(io.StringIO(teksti)):
        if not rivi or not rivi[0].strip().isdigit():
            continue  # otsikkorivi
        if len(rivi) < 9:
            raise Parsevirhe("liian vahan sarakkeita")
        try:
            ts = _ms(rivi[0])
            o, h, l, c, v, qv = (float(rivi[i]) for i in (1, 2, 3, 4, 5, 7))
            n = int(rivi[8])
        except ValueError:
            raise Parsevirhe("luku ei jasenny")
        if ts % 86400000 != 0:
            raise Parsevirhe("aikaleima ei paivan alussa")
        if min(o, h, l, c) <= 0 or v < 0 or qv < 0 or n < 0:
            raise Parsevirhe("epakelpo arvo")
        if h < max(o, c, l) or l > min(o, c, h):
            raise Parsevirhe("OHLC ristiriita")
        ulos.append((ts, o, h, l, c, v, qv, n))
    return ulos


def parse_funding(teksti):
    ulos = []
    for rivi in csv.reader(io.StringIO(teksti)):
        if not rivi or not rivi[0].strip().isdigit():
            continue
        try:
            if len(rivi) >= 3:
                ts, interval, rate = _ms(rivi[0]), float(rivi[1]), float(rivi[2])
            elif len(rivi) == 2:
                ts, interval, rate = _ms(rivi[0]), None, float(rivi[1])
            else:
                raise Parsevirhe("funding-rivi liian lyhyt")
        except ValueError:
            raise Parsevirhe("funding luku ei jasenny")
        if abs(rate) > 0.1:
            raise Parsevirhe("funding epauskottava")
        ulos.append((ts, interval, rate))
    return ulos


def parse_funding_rest(data):
    try:
        lista = json.loads(data.decode("utf-8"))
        ulos = []
        for r in lista:
            rate = float(r["fundingRate"])
            if abs(rate) > 0.1:
                raise Parsevirhe("funding epauskottava")
            ulos.append((int(r["fundingTime"]), None, rate))
        return ulos
    except (ValueError, KeyError, TypeError):
        raise Parsevirhe("funding REST jasennys")


def url_spot_kk(s, y, m):
    return "%s/data/spot/monthly/klines/%s/1d/%s-1d-%d-%02d.zip" % (config.BASE, s, s, y, m)


def url_spot_pv(s, y, m, d):
    return "%s/data/spot/daily/klines/%s/1d/%s-1d-%d-%02d-%02d.zip" % (config.BASE, s, s, y, m, d)


def _fut(s):
    """Futures-symbolin nimi (esim. PEPEUSDT -> 1000PEPEUSDT); muuten sama kuin spot."""
    return getattr(config, "FUTURES_NIMI", {}).get(s, s)


def url_funding_kk(s, y, m):
    s = _fut(s)
    return "%s/data/futures/um/monthly/fundingRate/%s/%s-fundingRate-%d-%02d.zip" % (config.BASE, s, s, y, m)


def url_funding_rest(s, alku_ms):
    s = _fut(s)
    return "%s?symbol=%s&startTime=%d&limit=1000" % (config.FUNDING_REST, s, alku_ms)
