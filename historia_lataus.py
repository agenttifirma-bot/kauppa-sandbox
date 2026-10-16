"""K11a: lataa paivadatan KAIKILLE USDT-pareille (myos kuolleille) erilliseen kantaan historia.db.
Lahde: symbolit_historia.csv (K10). Kirjoittaa VAIN historia.db:hen: ei kosketa markkina.db:hen, salkkuihin eika kauppoihin.
Idempotentti ja jatkettava (haku_loki). Ajo: python3 historia_lataus.py [--tyontekijoita 6] [--rajoita 10]"""
import argparse
import csv
import fcntl
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timezone

import config
import db
import lahde

HISTORIA_DB = os.environ.get("KAUPPA_HISTORIA_DB", "/srv/kauppa/data/historia.db")
CSV_POLKU = os.environ.get("KAUPPA_SYMBOLIT_CSV", "/srv/kauppa/data/symbolit_historia.csv")
ALKU_KK = config.ALKU          # (2021, 10): sama alku kuin markkina.db:ssa -> tulokset vertailukelpoisia
PAUSSI = 0.05


def loki(*a):
    print(datetime.now().strftime("%H:%M:%S"), *a, flush=True)


def _kk(teksti):
    y, m = teksti.split("-")
    return int(y), int(m)


def lue_csv(polku):
    """[(symbol, eka(y,m), vika(y,m), kuollut_bool)]"""
    ulos = []
    with open(polku, newline="") as f:
        for r in csv.DictReader(f):
            ulos.append((r["symbol"], _kk(r["eka_kk"]), _kk(r["vika_kk"]), str(r["kuollut"]).strip().lower() in ("1", "true", "kylla", "yes")))
    return ulos


def _seuraava(y, m):
    return (y + 1, 1) if m == 12 else (y, m + 1)


def _edellinen(y, m):
    return (y - 1, 12) if m == 1 else (y, m - 1)


def tyot(rivit, tanaan, rajoita=None):
    """Tyolista [(symbol, laji, jakso, url)]. Vain kuukaudet joille S3-listaus kertoo tiedoston olevan olemassa
    (ei turhia 404-pyyntoja); eilisiin asti paivatiedostot kuluvan kuun osalta elossa oleville kolikoille."""
    nyt = (tanaan.year, tanaan.month)
    ed = _edellinen(*nyt)
    lista = []
    for s, eka, vika, kuollut in rivit:
        if vika < ALKU_KK:
            continue                      # kuollut ennen datan alkua: ei kuulu tutkimusjaksolle
        y, m = max(eka, ALKU_KK)
        while (y, m) <= vika:
            lista.append((s, "spot_kk", "%d-%02d" % (y, m), lahde.url_spot_kk(s, y, m)))
            y, m = _seuraava(y, m)
        if not kuollut and vika >= ed:     # elossa: kuluva kuu paivatiedostoina
            for d in range(1, tanaan.day):
                lista.append((s, "spot_pv", date(tanaan.year, tanaan.month, d).isoformat(),
                              lahde.url_spot_pv(s, tanaan.year, tanaan.month, d)))
    if rajoita:
        sallitut = []
        for s, *_ in lista:
            if s not in sallitut:
                sallitut.append(s)
        sallitut = set(sallitut[:rajoita])
        lista = [t for t in lista if t[0] in sallitut]
    return lista


def _hae_yksi(hae, url, paussi):
    if paussi:
        time.sleep(paussi)
    return hae(url)


def kasittele(con, tyo, data, tulos):
    """Jasentaa ja kirjoittaa yhden tiedoston. data=None -> puuttuu. Yksikin huono rivi hylkaa koko tiedoston."""
    s, laji, jakso, _ = tyo
    if data is None:
        if laji == "spot_kk":
            db.kirjaa(con, laji, s, jakso, "puuttuu")
            tulos["puuttuu"] += 1
        return
    try:
        rivit = lahde.parse_klines(lahde.pura_zip(data))
    except lahde.Parsevirhe as e:
        db.kirjaa(con, laji, s, jakso, "virhe")
        tulos["virheet"].append("%s %s: %s" % (s, jakso, e))
        return
    tulos["hinnat"] += db.lisaa_hinnat(con, s, rivit)
    db.kirjaa(con, laji, s, jakso, "ok", len(rivit))


def aja(con, lista, hae, tyontekijoita=6, paussi=PAUSSI, edistyminen=500):
    tulos = {"hinnat": 0, "puuttuu": 0, "virheet": [], "tehty": 0, "ohitettu": 0}
    tehtavat = []
    for t in lista:
        if db.tila(con, t[1], t[0], t[2]) in ("ok", "puuttuu"):
            tulos["ohitettu"] += 1
        else:
            tehtavat.append(t)
    loki("tyota yhteensa %d, jo tehty %d, haetaan %d" % (len(lista), tulos["ohitettu"], len(tehtavat)))
    with ThreadPoolExecutor(max_workers=max(1, tyontekijoita)) as ex:
        tulevat = {ex.submit(_hae_yksi, hae, t[3], paussi): t for t in tehtavat}
        for f in as_completed(tulevat):
            t = tulevat.pop(f)
            try:
                data = f.result()
            except lahde.Estetty:
                for g in tulevat:
                    g.cancel()
                raise
            except lahde.Verkkovirhe as e:
                tulos["virheet"].append("%s %s: %s" % (t[0], t[2], e))
                continue
            kasittele(con, t, data, tulos)
            tulos["tehty"] += 1
            if edistyminen and tulos["tehty"] % edistyminen == 0:
                loki("  ... %d/%d" % (tulos["tehty"], len(tehtavat)))
    return tulos


def yhteenveto(con):
    r = con.execute("SELECT COUNT(DISTINCT symbol), COUNT(*), MIN(ts), MAX(ts) FROM hinnat").fetchone()
    pvm = lambda ms: "-" if ms is None else datetime.fromtimestamp(ms / 1000, timezone.utc).date().isoformat()
    return "kannassa %d symbolia, %d paivariviä, %s .. %s" % (r[0], r[1], pvm(r[2]), pvm(r[3]))


def main(argv=None):
    ap = argparse.ArgumentParser(description="K11a: kaikkien USDT-parien paivadata historia.db:hen")
    ap.add_argument("--db", default=HISTORIA_DB)
    ap.add_argument("--csv", default=CSV_POLKU)
    ap.add_argument("--tyontekijoita", type=int, default=6)
    ap.add_argument("--rajoita", type=int, default=0, help="vain n ensimmaista symbolia (testaus)")
    ap.add_argument("--ohita-testi", action="store_true")
    a = ap.parse_args(argv)
    if os.path.abspath(a.db) == os.path.abspath(config.DB_POLKU):
        loki("EI SALLITTU: kohde ei saa olla markkina.db")
        return 3
    lukko = open(a.db + ".lock", "w")
    try:
        fcntl.flock(lukko, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        loki("toinen ajo kaynnissa, lopetetaan")
        return 3
    rivit = lue_csv(a.csv)
    tanaan = datetime.now(timezone.utc).date()
    con = db.avaa(a.db)
    try:
        if not a.ohita_testi:
            import lataa
            if not lataa.yhteystesti(lahde.http_hae):
                loki("YHTEYSTESTI EPAONNISTUI")
                return 2
        lista = tyot(rivit, tanaan, a.rajoita or None)
        tulos = aja(con, lista, lahde.http_hae, a.tyontekijoita)
    except lahde.Estetty as e:
        loki("ALUE ESTETTY (451), ei yriteta kiertaa:", e)
        return 2
    except lahde.Verkkovirhe as e:
        loki("VERKKOVIRHE:", e)
        return 2
    loki("VALMIS: uusia rivejä %d, puuttuvia kuukausia %d, virheitä %d" % (tulos["hinnat"], tulos["puuttuu"], len(tulos["virheet"])))
    loki(yhteenveto(con))
    for v in tulos["virheet"][:30]:
        loki("  VIRHE", v)
    return 2 if tulos["virheet"] else 0


if __name__ == "__main__":
    sys.exit(main())
