"""EDGE DE COPIE MESURÉ (rectif Flo 23/07) — on ne FIXE jamais l'edge, on le MESURE.

PRINCIPE
--------
Copier un vault n'a d'edge que si, APRÈS qu'il a changé son exposition sur un coin, le prix de ce coin
part RÉELLEMENT dans le sens du changement — assez pour battre les coûts ET un placebo (le même coin,
la même direction, mais à un instant ALÉATOIRE, pour neutraliser la dérive du coin). Ce module :

  1. détecte les ÉVÉNEMENTS de changement d'expo (Δszi par coin) dans l'historique des snapshots ;
  2. mesure le rendement FORWARD du coin dans le sens du move, sur plusieurs horizons, net de coûts ;
  3. compare au PLACEBO (mêmes coins/directions, instants aléatoires) ;
  4. refuse de conclure si trop peu d'événements (NEED_MORE_DATA) — jamais un edge sorti de rien.

C'est l'exact pendant de `lead_lag_shadow` pour la copie. Aucune exécution : lecture d'historique.
"""
from __future__ import annotations

import bisect
import gzip
import json
import random
import re
from pathlib import Path
from typing import Any

VAULTS_SNAP_RELPATH = Path("runtime") / "data" / "vault_snapshots.jsonl"
PRIX_TAPE_RELPATH = Path("runtime") / "data" / "hl_allmids_tape.jsonl"
BBO_TAPE_RELPATH = Path("runtime") / "data" / "bbo_tape.jsonl"
BBO_TAPE_PREV_RELPATH = Path("runtime") / "data" / "bbo_tape.jsonl.prev"
BBO_SHARDS_RELPATH = Path("runtime") / "data" / "bbo_shards"
BBO_SHARDS_ARCHIVE_RELPATH = Path("runtime") / "data" / "bbo_shards_archive"
CONFIG_GELE_RELPATH = Path("runtime") / "data" / "copy_edge_config_gele.json"

SEUIL_MOVE_FRAC_NAV = 0.05         # même seuil que le signal : un move < 5 % du NAV n'est pas une décision
HORIZONS_MS = (60_000.0, 300_000.0, 900_000.0, 3_600_000.0)   # 1 min, 5 min, 15 min, 1 h
TOL_LOOKUP_MS = 90_000.0          # on n'apparie un prix que si un point de tape est à < 90 s de la cible
FRAIS_SLIPPAGE_BPS = 12.0         # coût A/R conservateur (2× taker HL + spread alt + latence) — voir signaux
MIN_EVENTS = 30                   # en-dessous : NEED_MORE_DATA (comme le lead-lag)


# ─────────────────────────────── chargement ───────────────────────────────

def charger_evenements(root: str | Path, *, seuil: float = SEUIL_MOVE_FRAC_NAV) -> list[dict]:
    """Événements de changement d'expo PAR COIN : {ts_ms, vault, coin, direction, move_frac}.
    Direction = signe(Δszi). Un seul événement (le plus gros coin) par transition de snapshot."""
    from hl_observer.experimental.signaux import _positions_par_coin  # réutilise la même lecture
    p = Path(root) / VAULTS_SNAP_RELPATH
    try:
        lignes = p.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return []
    par_vault: dict[str, list[dict]] = {}
    for l in lignes:
        try:
            d = json.loads(l)
        except ValueError:
            continue
        a = str(d.get("vault") or "")
        if a:
            par_vault.setdefault(a, []).append(d)
    ev: list[dict] = []
    for adr, snaps in par_vault.items():
        snaps.sort(key=lambda s: int(s.get("ts_ms") or 0))
        for av, ap in zip(snaps, snaps[1:]):
            nav = float(ap.get("nav_usd") or 0.0)
            if nav <= 0:
                continue
            p0, p1 = _positions_par_coin(av), _positions_par_coin(ap)
            best_c, best_dnot, best_dszi = "", 0.0, 0.0
            for c in set(p0) | set(p1):
                dszi = p1.get(c, (0.0, 0.0))[0] - p0.get(c, (0.0, 0.0))[0]
                px = p1.get(c, (0.0, 0.0))[1] or p0.get(c, (0.0, 0.0))[1]
                if abs(dszi) * px > abs(best_dnot):
                    best_c, best_dnot, best_dszi = c, dszi * px, dszi
            move_frac = abs(best_dnot) / nav
            if best_c and move_frac >= seuil:
                ev.append({"ts_ms": int(ap.get("ts_ms") or 0), "vault": adr, "coin": best_c,
                           "direction": 1 if best_dszi > 0 else -1, "move_frac": round(move_frac, 4)})
    return ev


def charger_prix_tape(root: str | Path) -> dict[str, list[tuple[int, float]]]:
    """{coin: [(ts_ms, px)] trié} depuis la tape allMids historique. ⚠️ Cette tape commence AUJOURD'HUI
    (le collecteur allMids vient d'être créé) : pour la RECHERCHE historique, préférer
    `charger_prix_tape_candles` (candleSnapshot backfillé, remonte loin). L'allMids reste utile pour un
    contrôle récent."""
    p = Path(root) / PRIX_TAPE_RELPATH
    try:
        lignes = p.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return {}
    tape: dict[str, list[tuple[int, float]]] = {}
    for l in lignes:
        try:
            d = json.loads(l)
        except ValueError:
            continue
        ts = int(d.get("ts_ms") or 0)
        for c, px in (d.get("mids") or {}).items():
            try:
                tape.setdefault(str(c).upper(), []).append((ts, float(px)))
            except (TypeError, ValueError):
                continue
    for c in tape:
        tape[c].sort()
    return tape


def charger_prix_tape_ciblee(
    root: str | Path,
    cibles_par_coin: dict[str, list[int]],
    *,
    horizon_ms: int = 3_600_000,
    tolerance_ms: int = int(TOL_LOOKUP_MS),
    max_evenements_total: int = 2_500,
    max_evenements_par_coin: int = 256,
    delays_ms: tuple[int, ...] = (),
    inclure_historique_bbo: bool = False,
    sources_bbo: list[str | Path] | None = None,
) -> tuple[dict[str, list[tuple[int, float]]], dict[str, Any]]:
    """Charge uniquement les vrais prix nécessaires au shadow live.

    Le collecteur longue durée ne doit jamais matérialiser toute la tape
    ``allMids`` en mémoire : une ligne contient près de mille marchés et
    l'historique peut peser plusieurs centaines de Mo. Pour chaque OPEN causal,
    il suffit du premier prix réellement observable à partir de l'événement,
    des délais d'entrée pré-enregistrés et de ``+horizon``. Cette lecture
    streame donc le fichier et ne conserve que ces points causaux bornés. Un
    point antérieur, même plus proche, ne peut jamais servir d'exécution.
    Si ``allMids`` ne couvre pas une cible, le BBO Hyperliquid brut peut la
    compléter. Les shards historiques ne sont lus que sur demande explicite :
    le shadow live reste léger, tandis qu'un replay économique peut exploiter
    les enregistrements immuables déjà présents sur disque.

    Le bornage prend les événements les plus récents. Il ne change aucun seuil
    économique et reste exclusivement destiné au classement shadow.
    """

    path = Path(root) / PRIX_TAPE_RELPATH
    normalisees: list[tuple[int, str]] = []
    for coin_raw, timestamps_raw in (cibles_par_coin or {}).items():
        coin = str(coin_raw or "").strip().upper()
        if not coin:
            continue
        timestamps: set[int] = set()
        for value in timestamps_raw or []:
            try:
                ts_ms = int(value)
            except (TypeError, ValueError, OverflowError):
                continue
            if ts_ms > 0:
                timestamps.add(ts_ms)
        for ts_ms in sorted(timestamps)[-max(1, int(max_evenements_par_coin)):]:
            normalisees.append((ts_ms, coin))

    normalisees.sort(reverse=True)
    normalisees = normalisees[:max(1, int(max_evenements_total))]
    retenues: dict[str, list[int]] = {}
    for ts_ms, coin in normalisees:
        retenues.setdefault(coin, []).append(ts_ms)
    for coin in retenues:
        retenues[coin] = sorted(set(retenues[coin]))

    offsets = tuple(sorted({0, int(horizon_ms), *(max(0, int(value)) for value in delays_ms)}))
    cibles: dict[str, list[int]] = {
        coin: sorted({event_ts + offset for event_ts in events for offset in offsets})
        for coin, events in retenues.items()
    }
    meilleurs: dict[str, dict[int, tuple[int, int, float, str]]] = {
        coin: {} for coin in cibles
    }

    def retenir(coin: str, ts_ms: int, price: float, source: str) -> None:
        targets = cibles.get(coin)
        if not targets or price <= 0:
            return
        first = bisect.bisect_left(targets, ts_ms - tolerance_ms)
        last = bisect.bisect_right(targets, ts_ms)
        for target in targets[first:last]:
            delay = ts_ms - target
            candidate = (delay, ts_ms, price, source)
            previous = meilleurs[coin].get(target)
            if previous is None or (delay, ts_ms, source) < (previous[0], previous[1], previous[3]):
                meilleurs[coin][target] = candidate
    # La ligne allMids contient près de mille prix. ``json.loads`` créerait
    # autant d'objets temporaires à chaque tick et le processus longue durée
    # conserverait plusieurs Go d'arènes Python. Le format est notre JSONL
    # canonique, une ligne autonome; ce parseur ciblé ne lit que ``ts_ms`` et
    # les clés explicitement demandées, puis valide chaque nombre.
    ts_pattern = re.compile(r'"ts_ms"\s*:\s*(\d+)')
    encoded_coins = {
        json.dumps(coin, ensure_ascii=False): coin for coin in cibles
    }
    number = r"-?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"
    price_pattern = (
        re.compile(
            r"(" + "|".join(re.escape(value) for value in encoded_coins) + r")\s*:\s*(" + number + r")"
        )
        if encoded_coins
        else None
    )
    first_target = min((value for values in cibles.values() for value in values), default=0)
    last_target = max((value for values in cibles.values() for value in values), default=0)
    lignes_lues = 0
    lignes_valides = 0
    source_details: list[dict[str, Any]] = []
    source_allmids = str(PRIX_TAPE_RELPATH).replace("\\", "/")
    if cibles:
        try:
            handle = path.open("r", encoding="utf-8", errors="ignore")
        except OSError:
            handle = None
        if handle is not None:
            with handle:
                for line in handle:
                    lignes_lues += 1
                    ts_match = ts_pattern.search(line)
                    if ts_match is None:
                        continue
                    ts_ms = int(ts_match.group(1))
                    if ts_ms < first_target - tolerance_ms or ts_ms > last_target + tolerance_ms:
                        continue
                    lignes_valides += 1
                    for price_match in price_pattern.finditer(line) if price_pattern is not None else ():
                        coin = encoded_coins[price_match.group(1)]
                        try:
                            price = float(price_match.group(2))
                        except (ValueError, OverflowError):
                            continue
                        retenir(coin, ts_ms, price, source_allmids)

    source_details.append({
        "source": source_allmids,
        "kind": "ALLMIDS",
        "bytes": path.stat().st_size if path.exists() else 0,
        "lignes_lues": lignes_lues,
        "lignes_valides": lignes_valides,
    })

    def chemins_bbo() -> list[Path]:
        if sources_bbo is not None:
            return sorted({
                (Path(value) if Path(value).is_absolute() else Path(root) / Path(value)).resolve()
                for value in sources_bbo
                if (Path(value) if Path(value).is_absolute() else Path(root) / Path(value)).is_file()
            }, key=lambda value: value.as_posix())

        resultat: list[Path] = []
        for relpath in (BBO_TAPE_PREV_RELPATH, BBO_TAPE_RELPATH):
            candidate = Path(root) / relpath
            if candidate.is_file():
                resultat.append(candidate.resolve())
        if not inclure_historique_bbo:
            return resultat

        shard_pattern = re.compile(r"bbo_tape_(\d+)\.jsonl(?:\.gz)?$")
        shards: list[tuple[int, Path]] = []
        for relpath in (BBO_SHARDS_ARCHIVE_RELPATH, BBO_SHARDS_RELPATH):
            directory = Path(root) / relpath
            if not directory.is_dir():
                continue
            for candidate in directory.glob("bbo_tape_*.jsonl*"):
                match = shard_pattern.fullmatch(candidate.name)
                if match is not None:
                    shards.append((int(match.group(1)) // 1_000_000, candidate.resolve()))
        shards.sort(key=lambda item: (item[0], item[1].as_posix()))
        previous_end: int | None = None
        lower = first_target - tolerance_ms
        upper = last_target + tolerance_ms
        for end_ms, candidate in shards:
            start_ms = previous_end if previous_end is not None else end_ms - 15 * 60_000
            previous_end = end_ms
            if end_ms >= lower and start_ms <= upper:
                resultat.append(candidate)
        return list(dict.fromkeys(resultat))

    venue_hl_pattern = re.compile(r'"venue"\s*:\s*"HL"')
    for bbo_path in chemins_bbo() if cibles else []:
        bbo_lues = 0
        bbo_valides = 0
        source_name = (
            bbo_path.relative_to(Path(root).resolve()).as_posix()
            if bbo_path.is_relative_to(Path(root).resolve())
            else str(bbo_path)
        )
        opener = gzip.open if bbo_path.suffix == ".gz" else open
        try:
            handle = opener(bbo_path, "rt", encoding="utf-8", errors="ignore")
        except OSError:
            continue
        with handle:
            for line in handle:
                bbo_lues += 1
                if venue_hl_pattern.search(line) is None:
                    continue
                try:
                    record = json.loads(line)
                    coin = str(record.get("coin") or "").strip().upper()
                    ts_ms = int(record.get("ts_wall_ms") or record.get("recv_wall_ts_ms") or 0)
                    price = float(record.get("mid") or 0.0)
                except (AttributeError, TypeError, ValueError, OverflowError):
                    continue
                if coin not in cibles or ts_ms < first_target - tolerance_ms or ts_ms > last_target + tolerance_ms:
                    continue
                bbo_valides += 1
                retenir(coin, ts_ms, price, source_name)
        source_details.append({
            "source": source_name,
            "kind": "HL_BBO",
            "bytes": bbo_path.stat().st_size,
            "lignes_lues": bbo_lues,
            "lignes_valides": bbo_valides,
        })

    tape: dict[str, list[tuple[int, float]]] = {}
    for coin, matches in meilleurs.items():
        points = sorted({(match[1], match[2]) for match in matches.values()})
        if points:
            tape[coin] = points

    requested_targets = sum(len(values) for values in cibles.values())
    matched_targets = sum(len(values) for values in meilleurs.values())
    targets_by_source: dict[str, int] = {}
    for matches in meilleurs.values():
        for match in matches.values():
            targets_by_source[match[3]] = targets_by_source.get(match[3], 0) + 1
    metadata: dict[str, Any] = {
        "mode": "EVENT_TARGETED_BOUNDED",
        "source": source_allmids,
        "source_mode": "ALLMIDS_THEN_HL_BBO_FALLBACK",
        "source_bytes": path.stat().st_size if path.exists() else 0,
        "source_details": source_details,
        "cibles_par_source": targets_by_source,
        "historique_bbo_active": bool(inclure_historique_bbo or sources_bbo is not None),
        "horizon_ms": int(horizon_ms),
        "delays_ms": list(offset for offset in offsets if offset not in (0, int(horizon_ms))),
        "tolerance_ms": int(tolerance_ms),
        "max_evenements_total": int(max_evenements_total),
        "max_evenements_par_coin": int(max_evenements_par_coin),
        "evenements_demandes": sum(len(set(values or [])) for values in (cibles_par_coin or {}).values()),
        "evenements_retenus": len(normalisees),
        "coins_demandes": len(cibles),
        "coins_apparies": len(tape),
        "cibles_prix": requested_targets,
        "cibles_appariees": matched_targets,
        "couverture_cibles": round(matched_targets / requested_targets, 6) if requested_targets else 0.0,
        "lignes_lues": sum(int(item["lignes_lues"]) for item in source_details),
        "lignes_valides": sum(int(item["lignes_valides"]) for item in source_details),
    }
    return tape, metadata


CANDLES_HISTORY_DIR = Path("runtime") / "history"


def charger_prix_tape_candles(root: str | Path, *, intervalle: str = "1m") -> dict[str, list[tuple[int, float]]]:
    """{coin: [(t_ms, close)] trié} depuis les candles BACKFILLÉES (`runtime/history/candles_<i>.jsonl`).
    C'EST LA MATIÈRE DE LA RECHERCHE HISTORIQUE — séparée du forward exécutable (rectif Flo 23/07) :
    ici on ne mesure QUE l'historique ; le forward temps réel utilise le L2 local < 1 s, jamais ceci."""
    p = Path(root) / CANDLES_HISTORY_DIR / ("candles_%s.jsonl" % intervalle)
    try:
        lignes = p.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return {}
    tape: dict[str, list[tuple[int, float]]] = {}
    for l in lignes:
        try:
            d = json.loads(l)
        except ValueError:
            continue
        try:
            c = str(d.get("coin") or "").upper()
            t = int(d.get("t_ms"))
            px = float(d.get("c"))
        except (TypeError, ValueError):
            continue
        if c and px > 0:
            tape.setdefault(c, []).append((t, px))
    for c in tape:
        tape[c].sort()
    return tape


# ─────────────────────────────── mesure ───────────────────────────────

def _prix_a(serie: list[tuple[int, float]], cible_ms: int, *, tol_ms: float = TOL_LOOKUP_MS) -> float | None:
    """Prix au plus proche de `cible_ms` dans la série, si un point est à < tol_ms. Sinon None."""
    if not serie:
        return None
    ts = [t for t, _ in serie]
    i = bisect.bisect_left(ts, cible_ms)
    best: tuple[float, float] | None = None
    for j in (i - 1, i):
        if 0 <= j < len(serie):
            dt = abs(serie[j][0] - cible_ms)
            if dt <= tol_ms and (best is None or dt < best[0]):
                best = (dt, serie[j][1])
    return best[1] if best else None


def rendement_forward(ev: dict, serie: list[tuple[int, float]], horizon_ms: float) -> float | None:
    """Rendement forward (bps) du coin dans le SENS du changement, entre ts et ts+horizon. None si
    un des deux prix est inintrouvable (trou de tape) — jamais extrapolé."""
    p0 = _prix_a(serie, ev["ts_ms"])
    p1 = _prix_a(serie, int(ev["ts_ms"] + horizon_ms))
    if p0 is None or p1 is None or p0 <= 0:
        return None
    return ev["direction"] * (p1 - p0) / p0 * 1e4


def rendement_forward_candles(ev: dict, serie: list[tuple[int, float]], horizon_ms: float,
                              *, delai_ms: float = 0.0) -> float | None:
    """Rendement forward (bps) ANTI-LOOKAHEAD pour la RECHERCHE candles (rectif Flo 23/07) : entrée à la
    PREMIÈRE bougie STRICTEMENT APRÈS ts+délai (jamais le close de la bougie contenant le signal), sortie
    à la première bougie après ts+délai+horizon. `serie` = [(t_ms début de bougie, close)] trié. None si
    une des deux bougies manque (jamais extrapolé)."""
    if not serie:
        return None
    ts = [t for t, _ in serie]
    t_sig = int(ev["ts_ms"] + delai_ms)
    i = bisect.bisect_right(ts, t_sig)                             # 1re bougie qui COMMENCE après le signal+délai
    j = bisect.bisect_right(ts, t_sig + int(horizon_ms))          # 1re bougie après signal+délai+horizon
    if i >= len(serie) or j >= len(serie) or i == j:
        return None
    p_ent, p_sor = serie[i][1], serie[j][1]
    if p_ent <= 0:
        return None
    return ev["direction"] * (p_sor - p_ent) / p_ent * 1e4


def _placebo_forward(ev: dict, serie: list[tuple[int, float]], horizon_ms: float,
                     rng: random.Random) -> float | None:
    """Même coin/direction mais à un instant ALÉATOIRE de la tape (neutralise la dérive du coin)."""
    if len(serie) < 3:
        return None
    t0 = serie[rng.randrange(len(serie))][0]
    faux = {"ts_ms": t0, "direction": ev["direction"]}
    return rendement_forward(faux, serie, horizon_ms)


def mesurer(root: str | Path, *, horizons_ms=HORIZONS_MS, seuil: float = SEUIL_MOVE_FRAC_NAV,
            frais_bps: float = FRAIS_SLIPPAGE_BPS, min_events: int = MIN_EVENTS,
            graine: int = 12345) -> dict[str, Any]:
    """Mesure l'edge NET de copie par horizon + placebo. Rend un verdict honnête (NEED_MORE_DATA si
    trop peu d'événements appariables). Ne conclut JAMAIS un edge positif sans battre le placebo."""
    ev = charger_evenements(root, seuil=seuil)
    tape = charger_prix_tape(root)
    rng = random.Random(graine)
    par_h: dict[str, dict[str, Any]] = {}
    n_appariables_max = 0
    for h in horizons_ms:
        reels, placebos = [], []
        for e in ev:
            serie = tape.get(e["coin"])
            if not serie:
                continue
            r = rendement_forward(e, serie, h)
            if r is not None:
                reels.append(r)
                pb = _placebo_forward(e, serie, h, rng)
                if pb is not None:
                    placebos.append(pb)
        n = len(reels)
        n_appariables_max = max(n_appariables_max, n)
        if n:
            brut = sum(reels) / n
            net = brut - frais_bps
            pb_moy = (sum(placebos) / len(placebos)) if placebos else 0.0
            par_h["%d" % int(h)] = {"n": n, "brut_bps": round(brut, 3), "net_bps": round(net, 3),
                                    "placebo_bps": round(pb_moy, 3), "edge_vs_placebo_bps": round(brut - pb_moy, 3),
                                    "bat_placebo_et_couts": bool(net > 0 and (brut - pb_moy) > 0)}
    statut = "MESURE" if n_appariables_max >= min_events else "NEED_MORE_DATA"
    meilleur = max((v for v in par_h.values()), key=lambda v: v["net_bps"], default=None)
    return {"statut": statut, "n_evenements": len(ev), "n_appariables_max": n_appariables_max,
            "min_events": min_events, "seuil_move_frac": seuil, "frais_bps": frais_bps,
            "par_horizon": par_h, "meilleur_horizon": meilleur,
            "note": "Edge MESURÉ sur l'historique forward, jamais fixé. Un edge n'est retenu que si "
                    "net_bps>0 ET edge_vs_placebo_bps>0 sur un horizon, puis validé en forward paper."}


# ─────────────────────────────── gel de config validée ───────────────────────────────

def geler(root: str | Path, horizon_ms: float, edge_brut_bps: float, *, edge_net_mesure_bps: float | None = None,
          source: str = "mesure") -> dict:
    """Gèle la config de copie VALIDÉE. On stocke l'edge BRUT (rendement forward mesuré) : le signal
    recalculera le NET avec le coût L2 RÉEL au moment d'ouvrir (pas de double-comptage des coûts)."""
    cfg = {"horizon_ms": float(horizon_ms), "edge_brut_bps": float(edge_brut_bps),
           "edge_net_mesure_bps": edge_net_mesure_bps, "source": source, "gele": True,
           "note": "Config copie gelée : edge BRUT mesuré sur forward historique (net recalculé au coût L2 réel), "
                   "à re-valider en forward paper causal."}
    dest = Path(root) / CONFIG_GELE_RELPATH
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    return cfg


def config_gelee(root: str | Path) -> dict | None:
    try:
        return json.loads((Path(root) / CONFIG_GELE_RELPATH).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


__all__ = [
    "charger_evenements",
    "charger_prix_tape",
    "charger_prix_tape_ciblee",
    "rendement_forward",
    "mesurer",
    "geler",
    "config_gelee",
]
