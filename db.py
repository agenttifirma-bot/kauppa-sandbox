"""SQLite-kanta: hinnat, funding, hakuloki."""
import sqlite3
from datetime import datetime, timezone

SKEEMA = """
CREATE TABLE IF NOT EXISTS hinnat (
  symbol TEXT NOT NULL, ts INTEGER NOT NULL,
  open REAL NOT NULL, high REAL NOT NULL, low REAL NOT NULL, close REAL NOT NULL,
  volume REAL NOT NULL, quote_volume REAL NOT NULL, kaupat INTEGER NOT NULL,
  PRIMARY KEY (symbol, ts)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS funding (
  symbol TEXT NOT NULL, ts INTEGER NOT NULL,
  interval_h REAL, rate REAL NOT NULL,
  PRIMARY KEY (symbol, ts)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS haku_loki (
  laji TEXT NOT NULL, symbol TEXT NOT NULL, jakso TEXT NOT NULL,
  tila TEXT NOT NULL, rivit INTEGER NOT NULL DEFAULT 0, aika TEXT NOT NULL,
  PRIMARY KEY (laji, symbol, jakso)
) WITHOUT ROWID;
"""


def avaa(polku):
    con = sqlite3.connect(polku, timeout=30)
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(SKEEMA)
    return con


def _nyt():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def lisaa_hinnat(con, symbol, rivit):
    """rivit: (ts,o,h,l,c,v,qv,n). Palauttaa uusien rivien maaran. Vanhaa ei ylikirjoiteta."""
    ennen = con.total_changes
    with con:
        con.executemany(
            "INSERT OR IGNORE INTO hinnat VALUES (?,?,?,?,?,?,?,?,?)",
            [(symbol,) + tuple(r) for r in rivit],
        )
    return con.total_changes - ennen


def lisaa_funding(con, symbol, rivit):
    """rivit: (ts, interval_h tai None, rate)."""
    ennen = con.total_changes
    with con:
        con.executemany(
            "INSERT OR IGNORE INTO funding VALUES (?,?,?,?)",
            [(symbol,) + tuple(r) for r in rivit],
        )
    return con.total_changes - ennen


def kirjaa(con, laji, symbol, jakso, tila, rivit=0):
    with con:
        con.execute(
            "INSERT OR REPLACE INTO haku_loki VALUES (?,?,?,?,?,?)",
            (laji, symbol, jakso, tila, rivit, _nyt()),
        )


def tila(con, laji, symbol, jakso):
    r = con.execute(
        "SELECT tila FROM haku_loki WHERE laji=? AND symbol=? AND jakso=?",
        (laji, symbol, jakso),
    ).fetchone()
    return r[0] if r else None


def viimeisin_funding(con, symbol):
    r = con.execute("SELECT MAX(ts) FROM funding WHERE symbol=?", (symbol,)).fetchone()
    return r[0]
