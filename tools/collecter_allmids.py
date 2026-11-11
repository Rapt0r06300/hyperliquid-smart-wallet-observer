"""COLLECTEUR allMids — prix HL frais TOUS-COINS pour Copy-Vaults.

POURQUOI (23/07)
----------------
Le signal Copy-Vaults détecte un changement d'exposition d'un vault suivi PAR COIN. Mais les vaults
tradent ~100 coins (0G, AAVE, ... ZRO) alors que le flux BBO synchro n'en couvre que 8 (BTC/ETH/SOL/
INJ/DASH/AVAX/LINK/NEO). Sans prix HL exécutable pour les 92 autres, la plupart des moves copiables
sont refusés (PRIX_NON_EXECUTABLE_HL). `allMids` est UN SEUL appel public qui renvoie le mid de TOUS
les coins → on le persiste ici pour que le tick copy-vault (process séparé) le lise.

RELIABLE, PAS DU HAMMERING
--------------------------
Un seul POST {"type":"allMids"} par tick (pas par coin) → coût de rate minuscule, on peut rafraîchir
souvent (10-20 s) → mids frais. Limiteur + backoff+jitter (socle collecte_fiable). Chaque écriture
est estampillée (ts_ms). Écriture atomique (tmp → replace) pour que le lecteur ne voie jamais un
fichier tronqué.

READ-ONLY / PAPER-ONLY : lire allMids public n'est pas passer un ordre. Aucune signature, aucune clé.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))
sys.path.insert(0, str(RACINE / "tools"))

import heartbeat_collecteur as HB  # noqa: E402

from hl_observer.collection import collecte_fiable as CF  # noqa: E402
from hl_observer.instrument_identity import preserve_native_instrument_symbol  # noqa: E402

URL_HL = "https://api.hyperliquid.xyz/info"
SORTIE = Path("runtime") / "data" / "hl_allmids.json"
TAPE = Path("runtime") / "data" / "hl_allmids_tape.jsonl"   # HISTORIQUE (pour mesurer l'edge forward de copie)


def _env_f(nom: str, defaut: float) -> float:
    """Surcharge par variable d'environnement (tuning sans toucher au code). Fail-soft."""
    try:
        v = float(os.environ.get(nom, ""))
        return v if v > 0 else defaut
    except (TypeError, ValueError):
        return defaut


# Plus de points historiques = plus de matière backtest (écritures locales, gratuit).
TAPE_INTERVALLE_S = _env_f("ALLMIDS_TAPE_S", 3.0)           # archive à CHAQUE passe en mode persistant (densité max ; était 30 s)
INTERVALLE_S_DEFAUT = _env_f("ALLMIDS_INTERVALLE_S", 4.0)   # PERSISTANT : 1 snapshot prix / 4 s (~15/min vs 2/min ; 1 POST léger ; était 15 s en respawn)
_PLANCHER_S = _env_f("ALLMIDS_PLANCHER_S", 3.0)             # garde-fou mini entre 2 passes
# En-têtes polis : User-Agent identifie le client (évite certains blocages), connexion réutilisable.
_HEADERS = {"Content-Type": "application/json", "User-Agent": "alina-smart-flow/allmids (read-only)"}


BESOINS_COLLECTE = Path("runtime") / "data" / "copy_vault_besoins_collecte.json"
DEX_INTERVALLE_S = _env_f("ALLMIDS_DEX_INTERVALLE_S", 8.0)   # cadence des mids HIP-3 (1 POST léger par dex)
DEX_MAX = 8                                                   # borne dure : jamais plus de 8 dex par passe
DEX_FRAICHEUR_CACHE_S = 30.0                                  # au-delà, un mid HIP-3 sort du cache courant
DEX_PART_MIN = 0.001                                          # part minimale du notionnel leader sans prix (0,1 %)
_DEX_NOM = re.compile(r"^[a-z0-9]{1,16}$")
_DEX_ETAT: dict[str, tuple[float, dict[str, float]]] = {}     # dex -> (instant du fetch, mids)


def parser_allmids(rep: Any, dex: str = "") -> dict[str, float]:
    """{coin: mid_float} depuis la réponse allMids. HL renvoie {coin: "prix_str"} (parfois enveloppé
    dans {'mids': {...}}). Prix illisible / <= 0 → ignoré (jamais un prix inventé).

    Le symbole est conservé TEL QUEL (identité native, sensible à la casse : ``kPEPE`` n'est pas
    ``KPEPE``) : la mise en majuscules rendait ces coins introuvables côté fills et labo. Pour un
    dex HIP-3, la clé est normalisée en ``dex:COIN`` (même identité que le champ ``coin`` des fills)."""
    src = rep.get("mids") if isinstance(rep, dict) and "mids" in rep else rep
    out: dict[str, float] = {}
    if isinstance(src, dict):
        for c, v in src.items():
            if isinstance(v, bool):
                continue
            try:
                px = float(v)
            except (TypeError, ValueError):
                continue
            coin = preserve_native_instrument_symbol(c)
            if dex and coin and not coin.startswith(f"{dex}:"):
                coin = f"{dex}:{coin}"
            if coin and math.isfinite(px) and px > 0:
                out[coin] = px
    return out


def dexs_a_collecter(root: Path) -> list[str]:
    """Dex HIP-3 dont il faut les mids, par priorité économique décroissante.

    Source 1 : ``ALLMIDS_DEXS=xyz,io`` (réglage opérateur explicite ; vide = aucun dex).
    Source 2 : le besoin ``PRIX_MANQUANT`` publié par le labo dans
    ``copy_vault_besoins_collecte.json``, classé par notionnel leader sans prix.
    Aucune source → aucun dex (comportement historique inchangé). Les noms sont validés et
    bornés : le fichier de besoins oriente la collecte, il n'est jamais une autorité d'ordre."""
    brut = os.environ.get("ALLMIDS_DEXS")
    if brut is not None:
        noms = [n.strip() for n in brut.split(",")]
    else:
        noms = []
        try:
            besoins = json.loads((root / BESOINS_COLLECTE).read_text(encoding="utf-8"))
            for besoin in besoins.get("needs") or []:
                if isinstance(besoin, dict) and besoin.get("need") == "PRIX_MANQUANT":
                    parts = besoin.get("by_dex_prefix") or {}
                    # tri par part de notionnel décroissante (l'ordre du fichier n'est pas garanti) ;
                    # sous DEX_PART_MIN le dex ne justifie pas une requête par passe.
                    classes = sorted(
                        ((float(v), str(n)) for n, v in parts.items()
                         if isinstance(v, (int, float)) and not isinstance(v, bool) and v >= DEX_PART_MIN),
                        key=lambda kv: (-kv[0], kv[1]),
                    )
                    noms = [n for _, n in classes]
        except (OSError, ValueError, AttributeError):
            noms = []
    vus: list[str] = []
    for nom in noms:
        if _DEX_NOM.match(nom) and nom not in vus:
            vus.append(nom)
    return vus[:DEX_MAX]


def _retry_after_s(exc: urllib.error.HTTPError) -> float | None:
    """Secondes demandées par le serveur via l'en-tête Retry-After (si fourni)."""
    try:
        v = exc.headers.get("Retry-After") if exc.headers else None
        s = float(v) if v else None
        return s if (s is not None and 0 < s <= 30) else None
    except (ValueError, AttributeError, TypeError):
        return None


def _post_allmids(*, dex: str = "", timeout_s: float = 8.0, tentatives: int = 3) -> Any:
    """POST allMids avec RETRY interne : un blip réseau ou un 429 transitoire est
    réessayé silencieusement (respecte Retry-After sur 429) au lieu de compter comme
    un échec. Un seul appel public et léger ; aucune signature, aucune clé.

    ``dex`` (optionnel, doc HL « info endpoint ») : nom d'un perp dex HIP-3 ; vide = dex principal."""
    requete: dict[str, str] = {"type": "allMids"}
    if dex:
        requete["dex"] = dex
    corps = json.dumps(requete).encode("utf-8")
    derniere: Exception | None = None
    for essai in range(1, max(1, tentatives) + 1):
        req = urllib.request.Request(URL_HL, data=corps, headers=_HEADERS)
        try:
            with urllib.request.urlopen(req, timeout=timeout_s) as rep:  # noqa: S310 (URL constante)
                return json.loads(rep.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            derniere = exc
            if exc.code == 429 and essai < tentatives:
                time.sleep(_retry_after_s(exc) or min(1.5 * essai, 5.0))
                continue
            raise
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            derniere = exc
            if essai < tentatives:
                time.sleep(min(0.4 * essai, 1.5))  # petit délai + jitter implicite réseau
                continue
            raise
    if derniere is not None:
        raise derniere
    raise RuntimeError("allMids: tentatives epuisees")


def _cache_sample_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def ecrire_cache(
    root: Path,
    mids: dict[str, float],
    *,
    fetched_at_ms: int | None = None,
    transport_latency_ms: float = 0.0,
    data_mode: str = "LIVE",
) -> int:
    """Écrit {ts_ms, n, mids} de façon ATOMIQUE (tmp → replace). Rend le nombre de coins."""
    dest = root / SORTIE
    dest.parent.mkdir(parents=True, exist_ok=True)
    timestamp = int(time.time() * 1000) if fetched_at_ms is None else int(fetched_at_ms)
    payload = {
        "ts_ms": timestamp,
        "n": len(mids),
        "source": "hyperliquid allMids (public, read-only)",
        "mids": mids,
    }
    payload["coverage_capture"] = {
        "schema_version": "hypersmart.allmids_coverage_capture.v1",
        "source_id": "hyperliquid-info-allmids",
        "endpoint": URL_HL,
        "request_type": "allMids",
        "fetched_at_ms": timestamp,
        "transport_latency_ms": round(float(transport_latency_ms), 6),
        "data_mode": str(data_mode),
        "sample_hash": _cache_sample_hash(payload),
        "paper_read_only": True,
        "real_execution": False,
    }
    tmp = dest.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    tmp.replace(dest)
    return len(mids)


def ecrire_tape(root: Path, mids: dict[str, float], *, ts_ms: int | None = None) -> None:
    """Append UN point (ts + mids compacts) à la tape historique — la matière du backtest d'edge.

    ``ts_ms`` = instant de RÉCEPTION du fetch principal : un prix n'est jamais daté plus tard
    qu'il n'a été observé (sinon le labo croirait disposer d'un prix plus frais qu'en réalité)."""
    dest = root / TAPE
    dest.parent.mkdir(parents=True, exist_ok=True)
    horodatage = int(time.time() * 1000) if ts_ms is None else int(ts_ms)
    ligne = json.dumps({"ts_ms": horodatage, "mids": {c: round(p, 8) for c, p in mids.items()}},
                       ensure_ascii=False)
    with dest.open("a", encoding="utf-8") as f:
        f.write(ligne + "\n")


def une_passe(root: Path, *, post_allmids=_post_allmids, archiver_tape: bool = False) -> int:
    """Un fetch allMids → cache courant (+ tape historique si `archiver_tape`). Rend le nb de coins (0 si KO)."""
    try:
        started = time.perf_counter()
        mids = parser_allmids(post_allmids())
        latency_ms = (time.perf_counter() - started) * 1000.0
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        return 0
    if not mids:
        return 0
    recu_ms = int(time.time() * 1000)
    frais = _collecter_dexs(root, post_allmids)
    maintenant = time.monotonic()
    courant = dict(mids)
    for instant, dex_mids in _DEX_ETAT.values():
        if maintenant - instant <= DEX_FRAICHEUR_CACHE_S:
            courant.update(dex_mids)
    n = ecrire_cache(
        root,
        courant,
        fetched_at_ms=recu_ms,
        transport_latency_ms=latency_ms,
        data_mode="LIVE" if post_allmids is _post_allmids else "TEST_FIXTURE",
    )
    HB.battre(root, "allmids-collector", pid=os.getppid(), n_ecrites=1,
              souscription_ack=True, note=f"{n} real allMids prices")
    if archiver_tape:
        # la tape ne reçoit que les mids OBTENUS À CETTE PASSE : jamais un prix HIP-3 plus ancien
        # redaté à l'instant courant (ce serait une fraîcheur inventée).
        ecrire_tape(root, {**mids, **frais}, ts_ms=recu_ms)
    return n


def _collecter_dexs(root: Path, post_allmids) -> dict[str, float]:
    """Mids des dex HIP-3 demandés, à cadence bornée ; un dex en échec n'annule jamais les autres."""
    frais: dict[str, float] = {}
    maintenant = time.monotonic()
    for dex in dexs_a_collecter(root):
        dernier = _DEX_ETAT.get(dex)
        if dernier is not None and maintenant - dernier[0] < DEX_INTERVALLE_S:
            continue
        try:
            dex_mids = parser_allmids(post_allmids(dex=dex), dex)
        except (urllib.error.URLError, OSError, ValueError, TimeoutError, TypeError):
            continue  # fail-soft par dex : inconnu reste inconnu, aucun prix inventé
        if dex_mids:
            _DEX_ETAT[dex] = (maintenant, dex_mids)
            frais.update(dex_mids)
    return frais


def _tape_due(root: Path) -> bool:
    """La tape est-elle « en retard » ? Décision basée sur le DERNIER ts de la tape (robuste même en
    --une-fois relancé toutes les 15 s par boucle_collecteur : on n'archive qu'1 point/min)."""
    p = root / TAPE
    try:
        with p.open("rb") as f:
            f.seek(0, 2)
            taille = f.tell()
            f.seek(max(0, taille - 4096))
            derniere = f.read().decode("utf-8", "ignore").splitlines()[-1]
        ts = float(json.loads(derniere).get("ts_ms") or 0)
    except (OSError, ValueError, IndexError):
        return True
    return (time.time() * 1000 - ts) >= TAPE_INTERVALLE_S * 1000


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Collecteur allMids HL (lecture seule, tous-coins).")
    p.add_argument("--root", default=str(RACINE))
    p.add_argument("--intervalle", type=float, default=INTERVALLE_S_DEFAUT)
    p.add_argument("--une-fois", action="store_true")
    a = p.parse_args(argv)
    root = Path(a.root)
    echecs = 0.0
    while True:
        try:
            n = une_passe(root, archiver_tape=_tape_due(root))
            if n:
                echecs = 0
                print(
                    f"[allmids] {time.strftime('%H:%M:%S')}  coins={n}  -> {SORTIE}",
                    flush=True,
                )
            else:
                echecs += 1
                d = CF.backoff_jitter(echecs)
                # 1er échec = blip transitoire (déjà réessayé en interne) : on ne
                # pollue pas le log. On n'alerte qu'à partir du 2e échec consécutif.
                if echecs >= 2:
                    print(f"[allmids] fetch vide/KO x{int(echecs)} — backoff {d:.1f}s", flush=True)
                time.sleep(d)
        except Exception as exc:  # noqa: BLE001 — on ne meurt jamais
            echecs += 1
            d = CF.backoff_jitter(echecs)
            if echecs >= 2:
                print(f"[allmids] erreur ({str(exc)[:60]}) x{int(echecs)} — backoff {d:.1f}s", flush=True)
            time.sleep(d)
        if a.une_fois:
            return 0
        time.sleep(max(_PLANCHER_S, float(a.intervalle)))


if __name__ == "__main__":
    raise SystemExit(main())
