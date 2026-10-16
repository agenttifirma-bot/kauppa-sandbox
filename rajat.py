"""LUKITTU OSA: vain Tony muuttaa nama (koodi on laki). Malli ei koskaan kirjoita tahan tiedostoon."""
import os

ALKUPAOMA = 10000.0          # USDT, leikkiraha
MAX_POSITIO = 0.15           # max osuus salkusta per kolikko
KATEISPUSKURI_MIN = 0.10     # kateista vahintaan 10 % salkusta
MAX_DRAWDOWN = 0.25          # hatajarru: kaikki kateiseksi, lukko kunnes Tony nollaa (Tony nosti 20 -> 25 % 15.10.2026)
PAIVATAPPIO_RAJA = 0.05      # yli 5 % paivatappion jalkeen ei osteta
MAX_KAUPPOJA_PAIVA = 10      # ALUSTAVA, Tony vahvistaa
MIN_KAUPPA_OSUUS = 0.005     # alle 0,5 % salkusta olevia kauppoja ei tehda
KULU = 0.001                 # 0,1 % per kauppa
SLIPPAGE = 0.001             # 0,1 % epafavorable hintavaikutus per kauppa (konservatiivinen)

SALKKU_DB = os.environ.get("KAUPPA_SALKKU_DB", "/srv/kauppa/data/salkku.db")

# Aiemmin havinneet strategiaperheet: tutkija ei saa ehdottaa naita uudelleen.
MUSTA_LISTA = (
    "EMA-scalping", "MACD", "RSI-variantit", "DCA+RSI",
    "adaptiivinen markkinatila", "pitkan aikavalin paivataso-indikaattoriyhdistelmat",
)

# --- K4/K5 ---
MALLIT = {"flash": "deepseek-flash", "pro": "deepseek-pro"}   # A/B-vertailu, LiteLLM-mallinimet
MAX_LLM_KUTSUJA_PAIVA = 6      # per salkku (analyytikko + kriitikko = 2/pv normaalisti)
LLM_MAX_TOKENS = 16000
LLM_AIKAKATKAISU = 120

# Vertailusalkku = Tonyn nykyinen salkku osta-ja-pida (Binance spot 15.10.2026: ~79 % USDC = kateinen, ~21 % BNB).
VERTAILU_PAINOT = {"BNBUSDT": 0.21}

# --- K6 (rehellinen backtest) ---
HOLDOUT_ALKU = (2026, 4, 15)   # LUKITTU loppujakso: ei saa kayttaa strategian kehitykseen; yksi katsaus per strategia
BACKTEST_ALKU = (2022, 2, 1)   # 91 paivan hakuikkuna + 30 paivan universumi tarvitsee historiaa (data alkaa 2021-10)
KOKEILU_DB = os.environ.get("KAUPPA_KOKEILU_DB", "/srv/kauppa/data/kokeilut.db")

# --- Operointi: kill switch ja sykemittari ---
# Tiedoston olemassaolo = kaikki salkkuajot pysayvat (ei LLM-kutsuja, ei kauppoja). Tony: touch = pysayta, rm = jatka.
PYSAYTYS = os.environ.get("KAUPPA_PYSAYTYS", "/srv/kauppa/data/PYSAYTYS")
SALKUT = {"flash": "/srv/kauppa/data/salkku_flash.db", "pro": "/srv/kauppa/data/salkku_pro.db"}
