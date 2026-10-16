"""LiteLLM-asiakas (OpenAI-yhteensopiva). Avain luetaan vain env-tiedostosta, ei koskaan tulosteta."""
import json
import urllib.error
import urllib.request

import rajat


class LLMVirhe(Exception):
    pass


def lue_env(polku):
    ulos = {}
    try:
        with open(polku) as f:
            for rivi in f:
                rivi = rivi.strip()
                if rivi and not rivi.startswith("#") and "=" in rivi:
                    k, v = rivi.split("=", 1)
                    ulos[k.strip()] = v.strip().strip('"').strip("'")
    except OSError:
        raise LLMVirhe("env-tiedostoa ei voi lukea")
    return ulos


def _http_post(url, avain, payload):
    pyynto = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + avain},
    )
    try:
        with urllib.request.urlopen(pyynto, timeout=rajat.LLM_AIKAKATKAISU) as v:
            return json.loads(v.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise LLMVirhe("HTTP %s" % e.code)
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise LLMVirhe(type(e).__name__)
    except ValueError:
        raise LLMVirhe("vastaus ei ole JSON")


def kysy(viestit, malli, env, hae=None):
    """Palauttaa (teksti, kaytto_dict). Ei uusintayrityksia."""
    hae = hae or _http_post
    if not env.get("LLM_BASE_URL") or not env.get("LLM_API_KEY"):
        raise LLMVirhe("LLM_BASE_URL / LLM_API_KEY puuttuu")
    payload = {"model": malli, "messages": viestit, "max_tokens": rajat.LLM_MAX_TOKENS, "temperature": 0}
    vastaus = hae(env["LLM_BASE_URL"].rstrip("/") + "/chat/completions", env["LLM_API_KEY"], payload)
    try:
        teksti = vastaus["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise LLMVirhe("vastauksen rakenne")
    if not isinstance(teksti, str) or not teksti.strip():
        syy = vastaus["choices"][0].get("finish_reason")
        kaytto0 = vastaus.get("usage") if isinstance(vastaus, dict) else None
        lopetus = kaytto0.get("completion_tokens") if isinstance(kaytto0, dict) else None
        raise LLMVirhe("tyhja vastaus (finish=%s, completion_tokens=%s)" % (syy, lopetus))
    kaytto = vastaus.get("usage") if isinstance(vastaus, dict) else None
    return teksti, (kaytto if isinstance(kaytto, dict) else {})
