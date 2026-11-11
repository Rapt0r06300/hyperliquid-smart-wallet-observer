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
from hl_observer.collection import vault_portfolio_history as VPH  # noqa: E402
from hl_observer.collection.portefeuille_compte import construire_portefeuille  # noqa: E402

URL_INFO = "https://api.hyperliquid.xyz/info"
URL_VAULTS = "https://stats-data.hyperliquid.xyz/Mainnet/vaults"
SORTIE = Path("runtime") / "data" / "vault_snapshots.jsonl"
#: courbes valeur / PnL / volume publiées par vaultDetails (points nouveaux à chaque passe)
SORTIE_HISTORIQUE = Path("runtime") / "data" / "vault_portfolio_history.jsonl"
ETAT_HISTORIQUE = Path("runtime") / "data" / "vault_portfolio_etat.json"
#: Balayage lent de l'univers ÉLARGI (vaults fermés compris) pour l'historique de portefeuille.
#: Mesuré le 2026-11-11 : 6 421 vaults fermés sur 9 478 créés. Ne garder que les 69 vaults ouverts
#: et gros d'aujourd'hui, c'est n'observer que les survivants : toute mesure de compétence en est
#: biaisée. Le balayage relit donc aussi les vaults qui ont compté puis disparu.
ETAT_BALAYAGE = Path("runtime") / "data" / "vault_portfolio_balayage.json"
BALAYAGE_MIN_TVL_USD = 1_000.0          # vault ouvert : au moins 1 000 USD aujourd'hui
BALAYAGE_MIN_PNL_ABS_USD = 1_000.0      # vault fermé : son PnL cumulé a dépassé 1 000 USD en valeur absolue
BALAYAGE_PAR_PASSE = 12                 # 12 lectures par passe de 5 min : environ 4 % du budget d'API par IP
BALAYAGE_LISTE_MAX_AGE_S = 24 * 3600.0  # la liste publique est relue une fois par jour
#: Portefeuilles complets des LEADERS lents (traders suivis, pas seulement les vaults). Le labo les
#: réclame (besoin POSITIONS_COMPLETES) : sans eux, la position d'un leader n'est connue que sur les
#: coins qu'il a tradés pendant la fenêtre, et le portefeuille répliqué est partiel.
SORTIE_PORTEFEUILLES = Path("runtime") / "data" / "copy_vault_snapshots_lane.jsonl"
BESOINS_LABO = Path("runtime") / "data" / "copy_vault_besoins_collecte.json"
ARCHETYPES_LENTS = frozenset({"DIRECTIONAL_SLOW", "SWING"})
DEXS_PORTEFEUILLES = ("", "xyz")        # dex principal + dex HIP-3 portant la majorité du notionnel
MAX_LEADERS_PORTEFEUILLES = 150
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


def _charger_etat_historique(root: Path) -> dict[str, dict]:
    """Dernier point déjà émis par vault et par fenêtre. Illisible ou absent -> rattrapage complet."""
    try:
        brut = json.loads((root / ETAT_HISTORIQUE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    # Un état écrit avec un autre schéma de ligne est ignoré : tout est réémis dans le schéma
    # courant (les lignes déjà au coffre restent, elles sont dédupliquées ou distinguées par schéma).
    if not isinstance(brut, dict) or brut.get("_schema") != VPH.SCHEMA_PORTFOLIO_HISTORY:
        return {}
    return {str(k): v for k, v in brut.items() if isinstance(v, dict)}


def _sauver_etat_historique(root: Path, etat_historique: dict[str, dict]) -> None:
    CF.ecrire_atomique(root / ETAT_HISTORIQUE, json.dumps(
        {"_schema": VPH.SCHEMA_PORTFOLIO_HISTORY, **etat_historique}, ensure_ascii=False))


def une_passe(root: Path, vaults: list[str], *, now: float | None = None,
              cache: "CF.CacheDedup | None" = None) -> int:
    """Un cycle : pour chaque vault, clearinghouse + vaultDetails -> snapshot complet écrit. Un vault
    illisible ou un réseau coupé n'arrête pas les autres (deny-by-default, jamais d'invention)."""
    t = now if now is not None else time.time()
    etat = _charger_etat(root)
    etat_historique = _charger_etat_historique(root)
    snaps: list[dict] = []
    historique: list[dict] = []
    for v in vaults:
        try:
            cs = parser_clearinghouse(_post_info({"type": "clearinghouseState", "user": v}))
            vd_brut = _post_info({"type": "vaultDetails", "vaultAddress": v})
        except (urllib.error.URLError, OSError, ValueError, TimeoutError):
            continue
        # La réponse vaultDetails porte des mois de courbe valeur/PnL/volume : on la conserve
        # (points nouveaux seulement), datée de NOTRE réception. Sans effet sur le snapshot.
        recu_ms = int((now if now is not None else time.time()) * 1000)
        lignes, haute_eau = VPH.construire_lignes(
            v, vd_brut, observed_at_ms=recu_ms, etat_vault=etat_historique.get(v))
        if lignes:
            historique.extend(lignes)
            etat_historique[v] = haute_eau
        if cs is None:
            continue
        vd = parser_vault_details(vd_brut)
        snap = construire_snapshot(v, cs, vd, now=t, etat_prec=etat.get(v))
        snaps.append(snap)
        etat[v] = {"expo_nette_usd": cs["expo_nette_usd"], "nav_usd": cs["nav_usd"]}
    _sauver_etat(root, etat)
    if historique:
        # Lignes d'abord, haute eau ensuite : une coupure entre les deux réémet des points déjà
        # écrits (dédupliqués à la certification), elle n'en perd jamais.
        CF.append_jsonl(root / SORTIE_HISTORIQUE, historique)
        _sauver_etat_historique(root, etat_historique)
    if not snaps:
        return 0
    propres = CF.collecter_proprement(snaps, source="vault_hl", champs_cle=("vault", "ts_ms"), cache=cache)
    return CF.append_jsonl(root / SORTIE, propres)


def univers_historique(payload: Any, *, min_tvl_usd: float = BALAYAGE_MIN_TVL_USD,
                       min_pnl_abs_usd: float = BALAYAGE_MIN_PNL_ABS_USD) -> list[str]:
    """Adresses dont l'historique mérite d'être relu : vaults ouverts non négligeables ET vaults
    fermés qui ont compté. PUR. Ce n'est pas une sélection de trading : un univers d'observation,
    choisi sur la taille, jamais sur le signe du résultat (un vault ruiné y entre comme un gagnant)."""
    if not isinstance(payload, list):
        return []
    retenus: dict[str, None] = {}
    for row in payload:
        summary = row.get("summary") if isinstance(row, dict) else None
        if not isinstance(summary, dict):
            continue
        relation = summary.get("relationship") or {}
        if not isinstance(relation, dict) or str(relation.get("type") or "").lower() != "normal":
            continue
        adresse = str(summary.get("vaultAddress") or "").strip().lower()
        if not _ADRESSE_COMPLETE.fullmatch(adresse) or adresse in VAULTS_EXCLUS:
            continue
        if summary.get("isClosed") is False:
            tvl = _f(summary.get("tvl"))
            if tvl is not None and tvl >= float(min_tvl_usd):
                retenus.setdefault(adresse, None)
            continue
        cumul: list[float] = []
        for fenetre in row.get("pnls") or ():
            if isinstance(fenetre, (list, tuple)) and len(fenetre) > 1 and fenetre[0] == "allTime":
                cumul = [v for v in (_f(x) for x in fenetre[1] or ()) if v is not None]
        if cumul and max(abs(v) for v in cumul) >= float(min_pnl_abs_usd):
            retenus.setdefault(adresse, None)
    return sorted(retenus)


def balayer_historique(root: Path, *, max_vaults: int = BALAYAGE_PAR_PASSE, now: float | None = None,
                       pause_s: float = 0.0) -> dict[str, Any]:
    """Relit l'historique de portefeuille des ``max_vaults`` vaults suivants de l'univers élargi.

    Reprise exacte : un curseur persistant avance vault après vault ; la liste publique est
    relue au plus une fois par jour ; une lecture en échec n'arrête rien (le vault sera relu au
    tour suivant). Seuls les points nouveaux sont écrits (même haute eau que les vaults suivis).
    """
    t = now if now is not None else time.time()
    try:
        etat = json.loads((root / ETAT_BALAYAGE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        etat = {}
    adresses = etat.get("adresses") if isinstance(etat, dict) else None
    liste_ms = etat.get("liste_ms") if isinstance(etat, dict) else None
    perimee = not isinstance(liste_ms, (int, float)) or t * 1000 - liste_ms > BALAYAGE_LISTE_MAX_AGE_S * 1000
    if not isinstance(adresses, list) or not adresses or perimee:
        try:
            nouvelles = univers_historique(_get_vaults_public())
        except (urllib.error.URLError, OSError, ValueError, TimeoutError):
            nouvelles = []
        if nouvelles:                       # une liste vide ou illisible ne remplace jamais l'ancienne
            adresses, liste_ms = nouvelles, int(t * 1000)
    if not isinstance(adresses, list) or not adresses:
        return {"univers": 0, "lus": 0, "lignes": 0, "echecs": 0, "tour": 0}
    curseur = int(etat.get("curseur") or 0) % len(adresses) if isinstance(etat, dict) else 0
    tour = int(etat.get("tour") or 0) if isinstance(etat, dict) else 0
    etat_historique = _charger_etat_historique(root)
    lignes: list[dict] = []
    lus = echecs = 0
    for _ in range(min(max(0, int(max_vaults)), len(adresses))):
        vault = str(adresses[curseur])
        curseur += 1
        if curseur >= len(adresses):
            curseur, tour = 0, tour + 1
        try:
            brut = _post_info({"type": "vaultDetails", "vaultAddress": vault})
        except (urllib.error.URLError, OSError, ValueError, TimeoutError):
            echecs += 1
            continue
        lus += 1
        recu_ms = int((now if now is not None else time.time()) * 1000)
        nouvelles_lignes, haute_eau = VPH.construire_lignes(
            vault, brut, observed_at_ms=recu_ms, etat_vault=etat_historique.get(vault))
        if nouvelles_lignes:
            lignes.extend(nouvelles_lignes)
            etat_historique[vault] = haute_eau
        if pause_s > 0:
            time.sleep(pause_s)
    if lignes:
        CF.append_jsonl(root / SORTIE_HISTORIQUE, lignes)
        _sauver_etat_historique(root, etat_historique)
    CF.ecrire_atomique(root / ETAT_BALAYAGE, json.dumps(
        {"liste_ms": liste_ms, "adresses": adresses, "curseur": curseur, "tour": tour,
         "maj_ms": int(t * 1000), "read_only": True}, ensure_ascii=False))
    return {"univers": len(adresses), "lus": lus, "lignes": len(lignes), "echecs": echecs,
            "tour": tour, "curseur": curseur}


def leaders_lents(root: Path) -> list[str]:
    """Adresses des leaders que le labo classe lents ou swing (plan publié par l'étude de copiabilité).
    Les robots HFT et les grappes de clones n'y figurent pas : leur portefeuille change trop vite pour
    une réplication lente. Plan absent ou illisible -> liste vide (jamais d'univers inventé)."""
    try:
        plan = json.loads((root / BESOINS_LABO).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    retenus: dict[str, None] = {}
    for leader in plan.get("leaders") or () if isinstance(plan, dict) else ():
        if not isinstance(leader, dict) or leader.get("archetype") not in ARCHETYPES_LENTS:
            continue
        for adresse in leader.get("addresses") or ():
            adresse = str(adresse).strip().lower()
            if _ADRESSE_COMPLETE.fullmatch(adresse):
                retenus.setdefault(adresse, None)
    return list(retenus)[:MAX_LEADERS_PORTEFEUILLES]


def passe_portefeuilles_leaders(root: Path, *, now: float | None = None,
                                dexs: tuple[str, ...] = DEXS_PORTEFEUILLES) -> dict[str, int]:
    """Un instantané complet de portefeuille par leader lent et par dex (``clearinghouseState``,
    lecture seule, requête légère). Un leader illisible n'arrête pas les autres ; rien n'est inventé."""
    leaders = leaders_lents(root)
    lignes: list[dict] = []
    echecs = 0
    for adresse in leaders:
        for dex in dexs:
            charge = {"type": "clearinghouseState", "user": adresse}
            if dex:
                charge["dex"] = dex
            try:
                etat = _post_info(charge)
            except (urllib.error.URLError, OSError, ValueError, TimeoutError):
                echecs += 1
                continue
            recu_ms = int((now if now is not None else time.time()) * 1000)
            snap = construire_portefeuille(etat, user=adresse, recv_ms=recu_ms, dex=dex,
                                           source="CLEARINGHOUSE_REST")
            if snap is None:
                echecs += 1
                continue
            lignes.append(snap)
    if lignes:
        CF.append_jsonl(root / SORTIE_PORTEFEUILLES, lignes)
    return {"leaders": len(leaders), "portefeuilles": len(lignes), "echecs": echecs}


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
    p.add_argument("--sans-balayage", action="store_true",
                   help="ne relit pas l'historique de l'univers élargi (vaults fermés compris) à cette passe")
    p.add_argument("--sans-leaders", action="store_true",
                   help="ne relève pas les portefeuilles complets des leaders lents à cette passe")
    p.add_argument("--balayage-complet", action="store_true",
                   help="un tour complet de l'univers élargi maintenant (lecture seule, cadence bornée), puis sort")
    a = p.parse_args(argv)
    root = Path(a.root)
    if a.balayage_complet:
        fait, premier = 0, None
        while True:
            bilan = balayer_historique(root, max_vaults=60, pause_s=1.2)
            fait += bilan["lus"] + bilan["echecs"]
            premier = bilan["tour"] if premier is None else premier
            print("[vaults] balayage complet : %d / %d vaults (lignes +%d, echecs %d)"
                  % (fait, bilan["univers"], bilan["lignes"], bilan["echecs"]), flush=True)
            if not bilan["univers"] or fait >= bilan["univers"] or bilan["tour"] > premier + 1:
                return 0 if bilan["univers"] else 2
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
            if not a.sans_leaders:
                # Portefeuilles complets des leaders lents désignés par le labo (boucle labo -> collecte).
                bilan_leaders = passe_portefeuilles_leaders(root)
                print("[vaults] portefeuilles leaders lents : %d ecrits pour %d leaders (echecs %d)"
                      % (bilan_leaders["portefeuilles"], bilan_leaders["leaders"], bilan_leaders["echecs"]), flush=True)
            if not a.sans_balayage:
                # Historique de l'univers élargi : quelques vaults par passe, jamais de rafale.
                bilan = balayer_historique(root, pause_s=0.5)
                print("[vaults] historique univers elargi : %d lus sur %d (tour %d), +%d lignes"
                      % (bilan["lus"], bilan["univers"], bilan["tour"], bilan["lignes"]), flush=True)
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
