"""Prosessitarkistus (vain havainto, ei vaikuta kauppoihin): onko analyytikon perustelussa asioita, joita <data>-taulukossa ei ole?
Konservatiivinen: kokonaisluvut 0..100 (lukumaarat, rankit, paivat) ja tunnetut vakiot sallitaan; liputetaan vain USDT-symbolit
ja desimaaliluvut/isot luvut, joita taulukossa ei ole (toleranssi pyoristykselle). Tulos kirjataan tapahtumalokiin kentaksi 'keksitty'."""
import re

LUKU = re.compile(r"(?<![\w.])[-+]?\d+(?:[.,]\d+)?")
PROSENTTI = re.compile(r"\s*(%|prosent)")   # kokonaisluku prosenttina on tuotto/osuus -> pitaa loytya taulukosta tai vakioista
SYMBOLI = re.compile(r"\b[A-Z0-9]{2,12}USDT\b")
VAKIOT = {0.2, 0.15, 0.9, 0.1, 0.05, 0.5, 0.25}   # kulu, positiokatto, kokonaiskatto, kateispuskuri, jarru jne. (rajat.py / kehote)


def _luvuiksi(teksti):
    ulos = []
    for m in LUKU.findall(teksti):
        try:
            ulos.append(float(m.replace(",", ".")))
        except ValueError:
            pass
    return ulos


def taulukon_luvut(teksti):
    """Kaikki taulukon luvut (itseisarvoina) ja symbolit."""
    luvut = {abs(x) for x in _luvuiksi(teksti)}
    return luvut, set(SYMBOLI.findall(teksti))


def _loytyy(x, luvut):
    x = abs(x)
    return any(abs(x - y) <= max(0.051, 0.005 * y) for y in luvut)


def tarkista_perustelu(perustelu, taulukko):
    """Palauttaa listan havainnoista, esim. ['symboli:FOOUSDT', 'luku:34.7']. Tyhja lista = ei havaintoja."""
    if not isinstance(perustelu, str) or not perustelu:
        return []
    luvut, symbolit = taulukon_luvut(taulukko)
    havainnot = []
    for s in sorted(set(SYMBOLI.findall(perustelu))):
        if s not in symbolit:
            havainnot.append("symboli:" + s)
    puhdas = SYMBOLI.sub(" ", perustelu)
    for m in LUKU.finditer(puhdas):
        try:
            x = float(m.group().replace(",", "."))
        except ValueError:
            continue
        prosentti = bool(PROSENTTI.match(puhdas, m.end()))
        if abs(x) in VAKIOT or _loytyy(x, luvut):
            continue
        if prosentti and abs(x) / 100 in VAKIOT:
            continue
        if x == int(x) and 0 <= abs(x) <= 100 and not prosentti:
            continue
        havainnot.append("luku:%g" % x)
    return havainnot
