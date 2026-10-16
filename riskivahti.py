"""Riskivahti: puhdasta koodia, ei mallia. Malli ehdottaa tavoitepainot, tama rajaa tai hylkaa.
Virheellinen ehdotus hylataan kokonaan (fail closed)."""
import math

import rajat


class Ehdotusvirhe(Exception):
    pass


def siisti_ehdotus(ehdotus, sallitut):
    """ehdotus: {symbol: tavoitepaino 0..1}. Palauttaa (painot, huomautukset)."""
    if not isinstance(ehdotus, dict):
        raise Ehdotusvirhe("ehdotus ei ole sanakirja")
    painot, huom = {}, []
    for s, w in ehdotus.items():
        if s not in sallitut:
            raise Ehdotusvirhe("ei sallittu kolikko: %s" % (s,))
        if isinstance(w, bool) or not isinstance(w, (int, float)) or not math.isfinite(w) or w < 0:
            raise Ehdotusvirhe("virheellinen paino: %s" % (s,))
        if w > rajat.MAX_POSITIO:
            huom.append("%s rajattu %.3f -> %.2f" % (s, w, rajat.MAX_POSITIO))
        painot[s] = min(float(w), rajat.MAX_POSITIO)
    summa = sum(painot.values())
    ylaraja = 1.0 - rajat.KATEISPUSKURI_MIN
    if summa > ylaraja:
        k = ylaraja / summa
        painot = {s: w * k for s, w in painot.items()}
        huom.append("kokonaispaino skaalattu %.3f -> %.2f (kateispuskuri)" % (summa, ylaraja))
    return painot, huom


def tila(arvohistoria, jarru_lukossa):
    """arvohistoria: paivan paattymisarvot kronologisesti. Palauttaa (jarru, ostot_estetty, drawdown)."""
    if not arvohistoria:
        return bool(jarru_lukossa), False, 0.0
    huippu = max(arvohistoria)
    dd = 1.0 - arvohistoria[-1] / huippu if huippu > 0 else 0.0
    jarru = bool(jarru_lukossa) or dd >= rajat.MAX_DRAWDOWN
    tappio = len(arvohistoria) >= 2 and arvohistoria[-1] / arvohistoria[-2] - 1.0 <= -rajat.PAIVATAPPIO_RAJA
    return jarru, tappio, dd
