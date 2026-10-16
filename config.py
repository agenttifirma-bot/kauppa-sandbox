"""K1 asetukset. Muutokset vain Tonyn luvalla (lukittu osa: SYMBOLIT, lahde)."""
import os

# Top ~20 markkinaa volyymin mukaan, stablecoinit pois. LISTA ON KOVAKOODATTU.
# HUOM: lista on Clauden arvio, tarkistetaan Binancen 24h-volyymeja vastaan.
SYMBOLIT = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
    "DOGEUSDT", "ADAUSDT", "TRXUSDT", "AVAXUSDT", "LINKUSDT",
    "DOTUSDT", "LTCUSDT", "BCHUSDT", "NEARUSDT", "SUIUSDT",
    "AAVEUSDT", "UNIUSDT", "ATOMUSDT", "ETCUSDT", "HBARUSDT",
]

ALKU = (2021, 10)  # historia tasta kuukaudesta alkaen (5 vuotta)

DB_POLKU = os.environ.get("KAUPPA_DB", "/srv/kauppa/data/markkina.db")
LUKKO_POLKU = DB_POLKU + ".lock"

BASE = "https://data.binance.vision"
FUNDING_REST = "https://fapi.binance.com/fapi/v1/fundingRate"

AIKAKATKAISU = 30      # sekuntia per pyynto
YRITYKSET = 3
PAUSSI = 0.15          # sekuntia pyyntojen valilla
MAX_ZIP = 20_000_000   # tavua
MAX_PURETTU = 10_000_000
VANHENTUNUT_PV = 3     # spot-data saa olla enintaan 3 paivaa vanhaa

# Futures-symbolit jotka poikkeavat spot-nimesta (funding haetaan futures-nimella, tallennetaan spot-nimella)
FUTURES_NIMI = {"PEPEUSDT": "1000PEPEUSDT"}
