"""LOT 1 — COLLECTEUR DE DONNÉES DU LABO (isolé). REST public borné, écrit UNIQUEMENT sous
runtime/research_lab/data (jamais runtime/data). Provenance + wall+monotonic + checksum + dédup + trous +
archivage. Reconnexion = REST sans état (retry). 0 clé, 0 signature, 0 ordre. N'utilise AUCUN slot userFills.

Flux :
  * asset_ctx           : metaAndAssetCtxs -> OI, mark, oracle, premium, funding, volume, impactPxs ;
  * predicted_fundings  : predictedFundings -> funding prédit par venue + prochaine échéance ;
  * oi_cap              : perpsAtOpenInterestCap -> coins au plafond d'OI (entrée/sortie) ;
  * hlp_inventory       : clearinghouseState(HLP + liquidateurs) -> inventaire par coin (sans slot userFills).

Posters injectables -> testable sans réseau. Chaque parser est PUR.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any, Callable

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.research_parallel import isolation as ISO  # noqa: E402

try:
    from collecter_asset_ctx import parser_ctx_complet       # réutilise le parser P2
except ImportError:
    sys.path.insert(0, str(RACINE / "tools"))
    from collecter_asset_ctx import parser_ctx_complet       # noqa: E402

URL_INFO = "https://api.hyperliquid.xyz/info"
#: adresses PUBLIQUES : HLP (market-maker protocole) + un liquidateur connu. Lecture seule (clearinghouseState).
HLP_ADDR = "0xdfc24b077bc1425ad1dea75bcb6f8158e10df303"
LIQUIDATEURS = (HLP_ADDR,)                                    # extensible ; on ne prend AUCUN slot userFills
POLL_S_DEFAUT = 30.0


def _post(charge: dict, *, timeout_s: float = 10.0) -> Any:
    corps = json.dumps(charge).encode("utf-8")
    req = urllib.request.Request(URL_INFO, data=corps, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout_s) as rep:      # noqa: S310 (URL publique constante)
        return json.loads(rep.read().decode("utf-8"))


# ─────────────────────────── parsers PURS ───────────────────────────

def parser_predicted_fundings(payload: Any) -> list[dict]:
    """predictedFundings -> [{coin, venue, taux, prochaine_ms}]. Format HL : [[coin, [[venue, {...}], ...]], ...]."""
    out = []
    if not isinstance(payload, list):
        return out
    for item in payload:
        try:
            coin = str(item[0]).upper()
            venues = item[1]
        except (TypeError, IndexError):
            continue
        if not isinstance(venues, list):
            continue
        for v in venues:
            try:
                venue = str(v[0])
                d = v[1] or {}
                taux = d.get("fundingRate")
                if taux is None:
                    continue
                out.append({"coin": coin, "venue": venue, "taux": float(taux),
                            "prochaine_ms": d.get("nextFundingTime")})
            except (TypeError, IndexError, ValueError):
                continue
    return out


def parser_oi_cap(payload: Any) -> list[str]:
    """perpsAtOpenInterestCap -> liste de coins au plafond d'OI (majuscules, dédup)."""
    if not isinstance(payload, list):
        return []
    return sorted({str(c).upper() for c in payload if isinstance(c, str)})


def parser_hlp_inventory(payload: Any, *, addr: str) -> list[dict]:
    """clearinghouseState -> [{addr, coin, szi, entryPx, position_value}]. szi signé = inventaire directionnel."""
    out = []
    try:
        positions = payload["assetPositions"]
    except (TypeError, KeyError):
        return out
    if not isinstance(positions, list):
        return out
    for ap in positions:
        try:
            p = ap["position"]
            coin = str(p["coin"]).upper()
            szi = float(p["szi"])
        except (TypeError, KeyError, ValueError):
            continue
        out.append({"addr": addr[:10], "coin": coin, "szi": szi,
                    "entry_px": _f(p.get("entryPx")), "position_value": _f(p.get("positionValue"))})
    return out


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


# ─────────────────────────── écriture isolée (dédup + provenance + checksum) ───────────────────────────

def _ecrire(root: Path, flux: str, lignes: list[dict], *, dedup_cle=None, etat: dict | None = None) -> int:
    """Append dans research_lab/data/<flux>.jsonl avec provenance wall+mono + checksum. Dédup optionnelle :
    si `dedup_cle(l)` inchangé depuis la dernière fois (via `etat`), la ligne est sautée (borne la croissance
    sans PERDRE d'info : on n'écrit que les CHANGEMENTS). Rend le nb écrit. Best-effort."""
    if not lignes:
        return 0
    base = ISO.lab_root(root) / "data"
    base.mkdir(parents=True, exist_ok=True)
    p = base / ("%s.jsonl" % flux)
    now_ms = int(time.time() * 1000)
    mono = time.monotonic_ns()
    n = 0
    try:
        with p.open("a", encoding="utf-8") as f:
            for l in lignes:
                if dedup_cle is not None and etat is not None:
                    k = dedup_cle(l)
                    sig = hashlib.sha256(json.dumps(l, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:12]
                    if etat.get(k) == sig:
                        continue
                    etat[k] = sig
                corps = {**l, "ts_wall_ms": now_ms, "ts_mono_ns": mono, "flux": flux,
                         "source": "hl_rest_public", "read_only": True, "real_execution": False}
                corps["checksum"] = hashlib.sha256(
                    json.dumps(corps, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:12]
                f.write(json.dumps(corps, ensure_ascii=False) + "\n")
                n += 1
        ISO.archiver_si_gros(root, flux)                     # scelle + archive si trop gros (jamais supprime)
    except OSError:
        return n
    return n


def une_passe(root: Path, *, poster: Callable = _post, etats: dict | None = None, now: float | None = None) -> dict:
    """Un cycle : les 4 flux, écrits isolés. Un flux KO n'empêche pas les autres (isolation). Rend un compte."""
    etats = etats if etats is not None else {}
    res = {}
    # asset_ctx (dédup par coin sur oi/premium/mark)
    try:
        ctx = parser_ctx_complet(poster({"type": "metaAndAssetCtxs"}))
        lignes = [{"coin": c, **d} for c, d in ctx.items()]
        res["asset_ctx"] = _ecrire(root, "asset_ctx", lignes, dedup_cle=lambda l: l["coin"],
                                   etat=etats.setdefault("asset_ctx", {}))
    except Exception as e:  # noqa: BLE001
        res["asset_ctx"] = "KO:%s" % str(e)[:60]
    # predicted_fundings
    try:
        pf = parser_predicted_fundings(poster({"type": "predictedFundings"}))
        res["predicted_fundings"] = _ecrire(root, "predicted_fundings", pf,
                                            dedup_cle=lambda l: "%s|%s" % (l["coin"], l["venue"]),
                                            etat=etats.setdefault("predicted_fundings", {}))
    except Exception as e:  # noqa: BLE001
        res["predicted_fundings"] = "KO:%s" % str(e)[:60]
    # oi_cap (on écrit la LISTE à chaque changement d'ensemble)
    try:
        cap = parser_oi_cap(poster({"type": "perpsAtOpenInterestCap"}))
        res["oi_cap"] = _ecrire(root, "oi_cap", [{"coins_au_cap": cap, "n": len(cap)}],
                                dedup_cle=lambda l: "set", etat=etats.setdefault("oi_cap", {}))
    except Exception as e:  # noqa: BLE001
        res["oi_cap"] = "KO:%s" % str(e)[:60]
    # hlp_inventory (par adresse, dédup par (addr,coin) sur szi)
    inv_total = 0
    for addr in LIQUIDATEURS:
        try:
            inv = parser_hlp_inventory(poster({"type": "clearinghouseState", "user": addr}), addr=addr)
            inv_total += _ecrire(root, "hlp_inventory", inv, dedup_cle=lambda l: "%s|%s" % (l["addr"], l["coin"]),
                                 etat=etats.setdefault("hlp_inventory", {}))
        except Exception as e:  # noqa: BLE001
            res["hlp_inventory_%s" % addr[:6]] = "KO:%s" % str(e)[:40]
    res["hlp_inventory"] = inv_total
    return res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Collecteur de données du labo (isolé, REST public, read-only).")
    ap.add_argument("--root", default=str(RACINE))
    ap.add_argument("--poll-s", type=float, default=POLL_S_DEFAUT)
    ap.add_argument("--une-passe", action="store_true")
    a = ap.parse_args(argv)
    root = Path(a.root)
    ISO.preparer(root)
    etats: dict = {}
    if a.une_passe:
        print("[lab_ctx] %s" % une_passe(root, etats=etats), flush=True)
        return 0
    while True:
        try:
            print("[lab_ctx] %s" % une_passe(root, etats=etats), flush=True)
        except Exception as e:  # noqa: BLE001
            print("[lab_ctx] passe KO: %s" % e, flush=True)
        time.sleep(a.poll_s)


if __name__ == "__main__":
    raise SystemExit(main())
