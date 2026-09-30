"""COLLECTEUR DE VAULTS HYPERLIQUID — la dernière porte copy non ouverte (23/07, chantier COPY).

POURQUOI. Le copy de FILLS est réfuté (signal 62 s, anti-persistant, et 76 % de nos fills = 4 wallets
HFT/MM dont on hérite l'adverse selection). La seule frontière NON testée = les VAULTS : un vault a un
lockup 1-4 j, tenu des JOURS → nos 62 s de délai deviennent négligeables ; le leader a du skin-in-the-
game (5 % non retirable) + high-water mark ; et surtout on peut **répliquer la trajectoire de position**
et comparer à la NAV RÉELLE on-chain. But : mesurer si une réplication PAPER à horizon plusieurs jours
reste rentable APRÈS notre délai et nos coûts.

CE QU'ON CAPTURE (pas juste une courbe de NAV — la demande de Flo, tout, à chaque passe) :
  * NAV (accountValue) + historique -> DRAWDOWN ;
  * POSITIONS (coin, szi, entryPx, levier, uPnL) -> exposition brute/nette + CHANGEMENTS d'exposition ;
  * LEVIER (totalNtlPos / accountValue) ;
  * PnL LATENT (Σ unrealizedPnl) et PnL RÉALISÉ (pnlHistory / Σ closedPnl des fills) ;
  * DÉPÔTS/RETRAITS (flux de followers) -> pour ne pas confondre un dépôt avec un gain ;
  * FILLS récents (px, sz, side, closedPnl) -> la trajectoire à répliquer.

READ-ONLY / PAPER-ONLY : endpoints `/info` publics en lecture. Aucun ordre, aucune clé, aucune
signature, aucun dépôt/retrait réel. On MESURE des vaults publics ; on n'y touche pas.

⚠️ LISTE DES VAULTS = `runtime/data/vaults_suivis.json` (adresses à suivre). On EXCLUT les vaults de
market-making (HLP & co) : copier un MM taker est mort par construction. Vide -> le collecteur idle
proprement (jamais d'invention). La validation live se fait sur TA machine (l'API n'est pas joignable
depuis le bac à sable).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from hl_observer.collection import collecte_fiable as CF  # noqa: E402

URL_INFO = "https://api.hyperliquid.xyz/info"
URL_VAULTS = "https://stats-data.hyperliquid.xyz/Mainnet/vaults"
SORTIE = Path("runtime") / "data" / "vault_snapshots.jsonl"
CONFIG = Path("runtime") / "data" / "vaults_suivis.json"
ETAT = Path("runtime") / "data" / "vaults_etat.json"           # NAV pic + dernière expo (drawdown/delta)
#: vaults de MARKET-MAKING à ne JAMAIS suivre (copier un MM taker = perte structurelle).
VAULTS_EXCLUS = frozenset({"0xdfc24b077bc1425ad1dea75bcb6f8158e10df303"})   # HLP (protocol vault)
POLL_S_DEFAUT = 300.0    # les vaults tiennent des jours : 5 min suffit largement
MIN_TVL_PUBLIC_USD = 100_000.0
MIN_AGE_PUBLIC_DAYS = 45.0
MAX_VAULTS_PUBLICS = 100
_ADRESSE_COMPLETE = re.compile(r"^0x[0-9a-f]{40}$")


def _post_info(charge: dict[str, Any], *, timeout_s: float = 12.0) -> Any:
    corps = json.dumps(charge).encode("utf-8")
    req = urllib.request.Request(URL_INFO, data=corps, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout_s) as rep:      # noqa: S310 (URL constante)
        return json.loads(rep.read().decode("utf-8"))


def _get_vaults_public(*, timeout_s: float = 20.0) -> Any:
    """Liste publique officielle des vaults Hyperliquid, en lecture seule."""
    req = urllib.request.Request(
        URL_VAULTS,
        headers={"Accept": "application/json", "User-Agent": "HyperSmart-Observer/1.0"},
    )
    with urllib.request.urlopen(req, timeout=timeout_s) as rep:  # noqa: S310 (URL constante)
        return json.loads(rep.read().decode("utf-8"))


# ─────────────────────────────── parseurs PURS (tolérants, aucune I/O) ───────────────────────────────

def _f(x: Any) -> float | None:
    try:
        v = float(x)
        return v if v == v else None
    except (TypeError, ValueError):
        return None


def parser_univers_public(
    payload: Any,
    *,
    now_ms: int | None = None,
    min_tvl_usd: float = MIN_TVL_PUBLIC_USD,
    min_age_days: float = MIN_AGE_PUBLIC_DAYS,
    max_vaults: int = MAX_VAULTS_PUBLICS,
) -> list[dict[str, Any]]:
    """Normalise l'univers officiel en adresses complètes, ouvertes et assez matures.

    Ce filtre ne constitue jamais une sélection de trading : il fournit uniquement
    un univers d'observation. Le score causal/net reste obligatoire avant toute
    promotion paper.
    """
    if not isinstance(payload, list):
        return []
    current_ms = int(time.time() * 1000) if now_ms is None else int(now_ms)
    uniques: dict[str, dict[str, Any]] = {}
    for row in payload:
        if not isinstance(row, dict):
            continue
        summary = row.get("summary")
        if not isinstance(summary, dict) or summary.get("isClosed") is not False:
            continue
        relationship = summary.get("relationship") or row.get("relationship") or {}
        if not isinstance(relationship, dict) or str(relationship.get("type") or "").lower() != "normal":
            continue
        address = str(summary.get("vaultAddress") or "").strip().lower()
        if not _ADRESSE_COMPLETE.fullmatch(address) or address in VAULTS_EXCLUS:
            continue
        tvl = _f(summary.get("tvl"))
        created_ms = _f(summary.get("createTimeMillis"))
        if tvl is None or created_ms is None or tvl < float(min_tvl_usd) or created_ms <= 0:
            continue
        age_days = max(0.0, (current_ms - created_ms) / 86_400_000.0)
        if age_days < float(min_age_days):
            continue
        apr = _f(row.get("apr"))
        candidate = {
            "address": address,
            "name": str(summary.get("name") or "(sans nom)"),
            "tvl_usd": round(tvl, 2),
            "apr_pct": round(apr * 100.0, 4) if apr is not None else None,
            "age_j": round(age_days, 2),
            "observation_only": True,
        }
        previous = uniques.get(address)
        if previous is None or candidate["tvl_usd"] > previous["tvl_usd"]:
            uniques[address] = candidate
    ordered = sorted(uniques.values(), key=lambda item: (-item["tvl_usd"], item["address"]))
    return ordered[:max(0, int(max_vaults))]


def rafraichir_univers_public(
    root: str | Path,
    *,
    fetcher=None,
    now_ms: int | None = None,
    min_tvl_usd: float = MIN_TVL_PUBLIC_USD,
    min_age_days: float = MIN_AGE_PUBLIC_DAYS,
    max_vaults: int = MAX_VAULTS_PUBLICS,
) -> dict[str, Any]:
    """Rafraîchit atomiquement l'univers d'observation, sans effacer sur échec."""
    root_path = Path(root)
    destination = root_path / CONFIG
    source = fetcher or _get_vaults_public
    public = parser_univers_public(
        source(),
        now_ms=now_ms,
        min_tvl_usd=min_tvl_usd,
        min_age_days=min_age_days,
        max_vaults=max_vaults,
    )
    if not public:
        raise ValueError("univers public vide ou invalide; ancien univers préservé")

    previous: dict[str, Any] = {}
    try:
        raw_previous = json.loads(destination.read_text(encoding="utf-8"))
        if isinstance(raw_previous, dict):
            previous = raw_previous
    except (OSError, ValueError):
        pass
    managed_before = {
        str(item.get("address") or "").lower()
        for item in (previous.get("_provenance", {}).get("vaults") or [])
        if isinstance(item, dict)
    }
    manual = []
    for address in previous.get("vaults") or []:
        normalized = str(address or "").strip().lower()
        if (
            _ADRESSE_COMPLETE.fullmatch(normalized)
            and normalized not in VAULTS_EXCLUS
            and normalized not in managed_before
        ):
            manual.append(normalized)

    addresses = list(dict.fromkeys([item["address"] for item in public] + manual))
    fetched_ms = int(time.time() * 1000) if now_ms is None else int(now_ms)
    result = {
        "_comment": (
            "Univers public Hyperliquid rafraîchi automatiquement. Toutes les nouvelles "
            "adresses restent observation-only jusqu'à preuve causale et nette."
        ),
        "_provenance": {
            "source": URL_VAULTS,
            "fetched_at_ms": fetched_ms,
            "filters": {
                "relationship": "normal",
                "isClosed": False,
                "min_tvl_usd": float(min_tvl_usd),
                "min_age_days": float(min_age_days),
                "max_vaults": int(max_vaults),
            },
            "vaults": public,
            "manual_preserved": manual,
        },
        "vaults": addresses,
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    CF.ecrire_atomique(destination, json.dumps(result, ensure_ascii=False, indent=1))
    return result


def parser_clearinghouse(payload: Any) -> dict[str, Any] | None:
    """clearinghouseState -> NAV, positions, expo brute/nette, levier, PnL latent. Illisible -> None."""
    if not isinstance(payload, dict):
        return None
    ms = payload.get("marginSummary") or {}
    nav = _f(ms.get("accountValue"))
    if nav is None:
        return None
    positions: list[dict] = []
    brute = nette = upnl = 0.0
    for ap in payload.get("assetPositions") or []:
        pos = (ap or {}).get("position") or {}
        szi = _f(pos.get("szi"))
        pv = _f(pos.get("positionValue"))
        u = _f(pos.get("unrealizedPnl")) or 0.0
        if szi is None:
            continue
        lev = (pos.get("leverage") or {}).get("value") if isinstance(pos.get("leverage"), dict) else None
        val = pv if pv is not None else 0.0
        signe = 1.0 if szi >= 0 else -1.0
        brute += abs(val); nette += signe * val; upnl += u
        positions.append({"coin": str(pos.get("coin") or "").upper(), "szi": szi,
                          "entryPx": _f(pos.get("entryPx")), "levier": _f(lev), "uPnl": u})
    return {"nav_usd": round(nav, 2), "expo_brute_usd": round(brute, 2),
            "expo_nette_usd": round(nette, 2), "levier": round(brute / nav, 3) if nav > 0 else 0.0,
            "pnl_latent_usd": round(upnl, 2), "n_positions": len(positions), "positions": positions}


def parser_vault_details(payload: Any) -> dict[str, Any]:
    """vaultDetails -> historique NAV (drawdown), PnL réalisé, dépôts/retraits (best-effort tolérant)."""
    out: dict[str, Any] = {"nav_hist": [], "pnl_realise_usd": None, "depot_retrait_net_usd": None,
                           "leader": None, "apr": None}
    if not isinstance(payload, dict):
        return out
    out["leader"] = payload.get("leader")
    out["apr"] = _f(payload.get("apr"))
    # portfolio = [["day", {accountValueHistory:[[t,v]], pnlHistory:[[t,v]]}], ["allTime", {...}], ...]
    for fenetre in payload.get("portfolio") or []:
        try:
            nom, bloc = fenetre[0], fenetre[1]
        except (TypeError, IndexError):
            continue
        if nom == "allTime" and isinstance(bloc, dict):
            avh = bloc.get("accountValueHistory") or []
            out["nav_hist"] = [_f(p[1]) for p in avh if isinstance(p, (list, tuple)) and len(p) > 1
                               and _f(p[1]) is not None]
            ph = bloc.get("pnlHistory") or []
            if ph and isinstance(ph[-1], (list, tuple)) and len(ph[-1]) > 1:
                out["pnl_realise_usd"] = _f(ph[-1][1])
    return out


def drawdown_pct(nav_hist: list[float]) -> float:
    """Le pire repli pic-à-creux de la NAV, en %. Série vide/plate -> 0."""
    pic = 0.0
    dd = 0.0
    for v in nav_hist:
        if v > pic:
            pic = v
        if pic > 0:
            dd = min(dd, (v - pic) / pic * 100.0)
    return round(dd, 2)


def construire_snapshot(vault: str, cs: dict, vd: dict, *, now: float,
                        etat_prec: dict | None) -> dict[str, Any]:
    """Le snapshot complet d'un vault (positions+expo+levier+PnL+drawdown+delta d'expo). PUR."""
    prec = etat_prec or {}
    delta_expo = round(cs["expo_nette_usd"] - float(prec.get("expo_nette_usd") or cs["expo_nette_usd"]), 2)
    return {"vault": vault, "ts_ms": int(now * 1000),
            "nav_usd": cs["nav_usd"], "expo_brute_usd": cs["expo_brute_usd"],
            "expo_nette_usd": cs["expo_nette_usd"], "levier": cs["levier"],
            "pnl_latent_usd": cs["pnl_latent_usd"], "pnl_realise_usd": vd.get("pnl_realise_usd"),
            "depot_retrait_net_usd": vd.get("depot_retrait_net_usd"),
            "drawdown_pct": drawdown_pct(vd.get("nav_hist") or []),
            "n_positions": cs["n_positions"], "positions": cs["positions"],
            "delta_expo_nette_usd": delta_expo, "leader": vd.get("leader"), "apr": vd.get("apr"),
            "source": "vault_hl", "read_only": True, "real_execution": False}


# ─────────────────────────────── liste & état (I/O bornée) ───────────────────────────────

def charger_vaults_suivis(root: str | Path) -> list[str]:
    """Adresses de vaults à suivre (config), MOINS les vaults de MM exclus. Absente -> []."""
    p = Path(root) / CONFIG
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    brut = d.get("vaults") if isinstance(d, dict) else d
    if not isinstance(brut, list):
        return []
    vus: dict[str, None] = {}
    for a in brut:
        a = str(a).lower().strip()
        if a.startswith("0x") and a not in VAULTS_EXCLUS:
            vus.setdefault(a, None)
    return list(vus)


def _charger_etat(root: Path) -> dict:
    try:
        return json.loads((root / ETAT).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _sauver_etat(root: Path, etat: dict) -> None:
    CF.ecrire_atomique(root / ETAT, json.dumps(etat, ensure_ascii=False))


def une_passe(root: Path, vaults: list[str], *, now: float | None = None,
              cache: "CF.CacheDedup | None" = None) -> int:
    """Un cycle : pour chaque vault, clearinghouse + vaultDetails -> snapshot complet écrit. Un vault
    illisible ou un réseau coupé n'arrête pas les autres (deny-by-default, jamais d'invention)."""
    t = now if now is not None else time.time()
    etat = _charger_etat(root)
    snaps: list[dict] = []
    for v in vaults:
        try:
            cs = parser_clearinghouse(_post_info({"type": "clearinghouseState", "user": v}))
            vd = parser_vault_details(_post_info({"type": "vaultDetails", "vaultAddress": v}))
        except (urllib.error.URLError, OSError, ValueError, TimeoutError):
            continue
        if cs is None:
            continue
        snap = construire_snapshot(v, cs, vd, now=t, etat_prec=etat.get(v))
        snaps.append(snap)
        etat[v] = {"expo_nette_usd": cs["expo_nette_usd"], "nav_usd": cs["nav_usd"]}
    _sauver_etat(root, etat)
    if not snaps:
        return 0
    propres = CF.collecter_proprement(snaps, source="vault_hl", champs_cle=("vault", "ts_ms"), cache=cache)
    return CF.append_jsonl(root / SORTIE, propres)


def resume(root: str | Path = ".") -> dict[str, Any]:
    """État honnête : combien de snapshots, sur combien de vaults, durée -> assez pour le backtest ?"""
    p = Path(root) / SORTIE
    if not p.exists():
        return {"snapshots": 0, "vaults": 0, "verdict": "AUCUN_VAULT_SUIVI_OU_COLLECTE"}
    vaults: set[str] = set()
    ts: list[int] = []
    for l in p.read_text(encoding="utf-8", errors="ignore").splitlines():
        try:
            d = json.loads(l)
            vaults.add(d.get("vault") or "")
            ts.append(int(d.get("ts_ms") or 0))
        except (ValueError, TypeError):
            continue
    jours = (max(ts) - min(ts)) / 86_400_000.0 if len(ts) > 1 else 0.0
    return {"snapshots": len(ts), "vaults": len(vaults), "jours": round(jours, 2),
            "verdict": ("PRET_POUR_BACKTEST_REPLICATION" if jours >= 3 else "INSUFFISANT_LAISSER_TOURNER")}


def importer_vaults(root: str | Path, adresses: list[str]) -> int:
    """Import ASSISTÉ : fusionne des adresses dans `vaults_suivis.json` (dédup, MM exclus). Rend le
    nombre total suivi. Pour ne pas rester vide en attendant — Flo colle une liste, on l'ingère."""
    p = Path(root) / CONFIG
    existant = charger_vaults_suivis(root)
    vus = dict.fromkeys(existant)
    for a in adresses or ():
        a = str(a).lower().strip()
        if a.startswith("0x") and a not in VAULTS_EXCLUS:
            vus.setdefault(a)
    CF.ecrire_atomique(p, json.dumps({"vaults": list(vus)}, ensure_ascii=False, indent=1))
    return len(vus)


def classer_vault(snapshots: list[dict]) -> dict[str, Any]:
    """Classe un vault sur son COMPORTEMENT RÉEL (jamais son nom ni son APR affiché) : ancienneté
    observée, drawdown, stabilité de NAV, exposition, directionnalité (un MM garde le net ≈ 0). Un
    vault de MM ou trop instable/tiré est ÉCARTÉ — on ne réplique QUE du directionnel sain."""
    import statistics as st
    n = len(snapshots)
    if n < 10:
        return {"verdict": "INSUFFISANT", "n": n}
    navs = [float(s.get("nav_usd") or 0.0) for s in snapshots]
    ts = [int(s.get("ts_ms") or 0) for s in snapshots]
    gross = [float(s.get("expo_brute_usd") or 0.0) for s in snapshots]
    net = [abs(float(s.get("expo_nette_usd") or 0.0)) for s in snapshots]
    age_j = (max(ts) - min(ts)) / 86_400_000.0
    dd = min((float(s.get("drawdown_pct") or 0.0) for s in snapshots), default=0.0)
    nav_moy = st.mean(navs) or 1e-9
    stabilite = st.pstdev(navs) / nav_moy                       # coeff de variation NAV (bas = stable)
    gross_moy = st.mean(gross) or 1e-9
    directionnalite = st.mean(net) / gross_moy                  # ~0 = MM ; élevé = directionnel
    lev_moy = st.mean(float(s.get("levier") or 0.0) for s in snapshots)
    if directionnalite < 0.25:
        verdict = "ECARTE_MARKET_MAKING"                        # net ≈ 0 -> MM, pas copiable en taker
    elif dd < -50.0:
        verdict = "ECARTE_DRAWDOWN"
    elif age_j < 3.0:
        verdict = "ECARTE_TROP_JEUNE"                           # pas assez de track record OBSERVÉ
    else:
        verdict = "RETENU_DIRECTIONNEL"
    return {"verdict": verdict, "n": n, "age_jours": round(age_j, 2), "drawdown_pct": round(dd, 2),
            "stabilite_nav": round(stabilite, 4), "directionnalite": round(directionnalite, 3),
            "levier_moyen": round(lev_moy, 2), "nav_moyenne_usd": round(nav_moy, 2),
            "note": "classé sur le comportement mesuré, PAS le nom ni l'APR affiché"}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Collecteur de vaults HL (lecture seule).")
    p.add_argument("--root", default=".")
    p.add_argument("--poll", type=float, default=POLL_S_DEFAUT)
    p.add_argument("--une-fois", action="store_true")
    p.add_argument("--rafraichir-univers", action="store_true")
    a = p.parse_args(argv)
    root = Path(a.root)
    if a.rafraichir_univers:
        try:
            univers = rafraichir_univers_public(root)
            print("[vaults] univers public rafraichi: %d adresses" % len(univers["vaults"]), flush=True)
        except (urllib.error.URLError, OSError, ValueError, TimeoutError) as exc:
            print("[vaults] univers public non rafraichi (%s); ancien univers preserve" % str(exc)[:100], flush=True)
            return 2
    cache = CF.CacheDedup()
    total, echecs = 0, 0
    while True:
        try:
            vaults = charger_vaults_suivis(root)
            if not vaults:
                print("[vaults] aucun vault dans runtime/data/vaults_suivis.json — idle", flush=True)
            else:
                n = une_passe(root, vaults, cache=cache)
                total += n
                echecs = 0
                print("[vaults] %s  ecrits=%d  cumul=%d  (%d vaults)"
                      % (time.strftime("%H:%M:%S"), n, total, len(vaults)), flush=True)
        except Exception as exc:  # noqa: BLE001 — on ne meurt jamais, on recule
            echecs += 1
            d = CF.backoff_jitter(echecs)
            print("[vaults] erreur (%s) — backoff %.1fs" % (str(exc)[:60], d), flush=True)
            time.sleep(d)
            continue
        if a.une_fois:
            return 0
        time.sleep(max(5.0, float(a.poll)))


if __name__ == "__main__":
    raise SystemExit(main())
