"""EXÉCUTION PAPER HONNÊTE (LOT14 #5/#6/#7, Flo 26/07). Cœurs PURS, testables sans réseau.

#5 dislocation DEUX JAMBES : chaque jambe conservée+réconciliée (venue/side/entry_exec/exit_exec/size/fee/
   slippage/latency/realized) ; le PnL total = SOMME EXACTE des jambes (jamais un seul mid HL ou un gap synth).
#6 copy-vault REDUCE PROPORTIONNEL : une réduction du leader ne ferme pas tout ; on ferme la fraction
   réduite (frais sur la partie fermée), on garde la taille résiduelle ; close intégral seulement si la taille
   leader est réellement ~0. Un coin absent d'un snapshot INCOMPLET ne conclut jamais à un close.
#7 DONNÉE MANQUANTE : grace period courte, mark conservateur, slippage de stress, sortie DATA_MISSING_TIMEOUT.
0 ordre, 0 clé.
"""
from __future__ import annotations

from hl_observer.experimental import invariants as INV

# ─────────────── #5 dislocation deux jambes ───────────────
def pnl_jambe(jambe: dict) -> float:
    """PnL réalisé d'UNE jambe au prix EXÉCUTABLE. jambe = {side:+1 long/−1 short, entry_px, exit_px, size_usd,
    fee_bps, slippage_bps}. Long : (exit−entry)/entry ; short : (entry−exit)/entry. − frais − slippage."""
    for k in ("side", "entry_px", "exit_px", "size_usd"):
        if not INV.est_fini(jambe.get(k)):
            raise ValueError("jambe invalide: %s" % k)
    e, x, s = float(jambe["entry_px"]), float(jambe["exit_px"]), float(jambe["size_usd"])
    if e <= 0 or x <= 0 or s <= 0:
        raise ValueError("prix/taille non positifs")
    brut = ((x - e) / e if int(jambe["side"]) > 0 else (e - x) / e)
    cout = (float(jambe.get("fee_bps") or 0.0) + float(jambe.get("slippage_bps") or 0.0)) / 1e4
    return round((brut - cout) * s, 6)


def pnl_deux_jambes(jambes: list[dict]) -> dict:
    """PnL total = SOMME EXACTE des jambes réconciliées. Rend {realized_usd, jambes:[...détail], n_jambes}."""
    detail = []
    total = 0.0
    for j in jambes:
        p = pnl_jambe(j)
        total += p
        detail.append({"venue": j.get("venue"), "side": int(j["side"]), "entry_px": float(j["entry_px"]),
                       "exit_px": float(j["exit_px"]), "size_usd": float(j["size_usd"]),
                       "fee_bps": float(j.get("fee_bps") or 0.0), "slippage_bps": float(j.get("slippage_bps") or 0.0),
                       "latency_ms": float(j.get("latency_ms") or 0.0), "realized_usd": p})
    return {"realized_usd": round(total, 6), "n_jambes": len(detail), "jambes": detail}


# ─────────────── #6 copy-vault REDUCE proportionnel ───────────────
def snapshot_complet_ok(snapshot: dict, coin: str, *, ts_entree_ms: float, now_ms: float,
                        fraicheur_max_ms: float = 60_000.0) -> tuple[bool, str | None]:
    """Un close/reduce sur suivi leader n'est VALIDE que si le snapshot est COMPLET (marqué complet),
    FRAIS, et POSTÉRIEUR à l'entrée. Un coin absent d'un snapshot incomplet -> NE PAS conclure au close."""
    if not snapshot or not snapshot.get("complet"):
        return False, "SNAPSHOT_INCOMPLET"
    ts = snapshot.get("ts_ms")
    if not INV.est_fini(ts):
        return False, "SNAPSHOT_SANS_TS"
    if float(ts) <= float(ts_entree_ms):
        return False, "SNAPSHOT_ANTERIEUR_ENTREE"
    if float(now_ms) - float(ts) > fraicheur_max_ms:
        return False, "SNAPSHOT_PERIME"
    return True, None


def classifier_changement_leader(*, entry_szi: float, current_szi: float, last_applied_szi: float,
                                 tol_frac: float = 0.02) -> str:
    """P2 — classe le changement d'exposition SIGNÉE du leader depuis le dernier état DÉJÀ appliqué. Détecte
    toute variation au-delà d'une tolérance relative (pas seulement > 50 %) : REDUCE, ADD, CLOSE, FLIP_*,
    AUCUN. Un FLIP (changement de signe) est explicite, JAMAIS interprété comme 'aucun changement'."""
    if not (INV.est_fini(entry_szi) and INV.est_fini(current_szi) and INV.est_fini(last_applied_szi)) \
            or abs(float(entry_szi)) <= 0:
        return "INVALIDE"
    e, cur, last = float(entry_szi), float(current_szi), float(last_applied_szi)
    if cur != 0 and last != 0 and (cur > 0) != (last > 0):     # changement de SIGNE = flip explicite
        return "FLIP_LONG_SHORT" if last > 0 else "FLIP_SHORT_LONG"
    if abs(cur) <= abs(e) * 1e-9:                              # exposition ~0 -> clos
        return "CLOSE"
    delta = abs(cur) - abs(last)
    seuil = abs(e) * float(tol_frac)
    if delta < -seuil:
        return "REDUCE"
    if delta > seuil:
        return "ADD"
    return "AUCUN"


def reduire_vers_cible(pos: dict, *, entry_leader_szi: float, current_leader_szi: float, prix_sortie: float,
                       cout_sortie_bps: float, cout_entree_bps: float = 0.0, quasi_zero: float = 0.05) -> dict:
    """P1 (idempotence) + P4 (coût d'entrée réparti). Le notionnel CIBLE se calcule TOUJOURS depuis le
    notionnel INITIAL et la taille COURANTE du leader :
        cible = initial_paper_notional × |current_leader_szi / entry_leader_szi|
        à_fermer = current_paper_notional − cible          (JAMAIS un résidu re-multiplié par un ratio)
    Rejouer EXACTEMENT le même snapshot -> current == cible -> 0 à fermer (idempotent).
    realized = brut(sur la tranche) − coût d'entrée réparti − coût de sortie."""
    initial = float(pos.get("initial_paper_notional_usd") or pos.get("notional_usd") or 0.0)
    current = float(pos.get("notional_usd") or 0.0)
    if not (INV.est_fini(entry_leader_szi) and INV.est_fini(current_leader_szi)) or abs(float(entry_leader_szi)) <= 0:
        return {"action": "AUCUNE", "motif": "TAILLE_LEADER_INVALIDE"}
    ratio = abs(float(current_leader_szi)) / abs(float(entry_leader_szi))     # 1 = inchangé ; 0 = leader clos
    if ratio <= quasi_zero:                                    # leader ~0 -> close intégral
        ferme, residuel, action = current, 0.0, "CLOSE_INTEGRAL"
    else:
        cible = min(current, initial * ratio)                 # borne au courant (une réduction ne fait pas ADD)
        ferme = round(current - cible, 6)
        if ferme <= 1e-9:                                     # même snapshot rejoué / pas de réduction nette
            return {"action": "AUCUNE", "ratio_restant": round(ratio, 4), "notional_ferme_usd": 0.0,
                    "notional_residuel_usd": round(current, 6)}
        residuel, action = round(current - ferme, 6), "REDUCE"
    sens = int(pos["sens"]); entree = float(pos["prix_entree"])
    brut = (float(prix_sortie) - entree) / entree if sens > 0 else (entree - float(prix_sortie)) / entree
    entry_cost = float(cout_entree_bps) / 1e4 * ferme          # P4 : coût d'ENTRÉE de la tranche fermée
    exit_cost = float(cout_sortie_bps) / 1e4 * ferme
    realized = round(brut * ferme - entry_cost - exit_cost, 6)
    return {"action": action, "ratio_restant": round(ratio, 4), "notional_ferme_usd": round(ferme, 6),
            "notional_residuel_usd": residuel, "realized_usd": realized,
            "entry_cost_allocated_usd": round(entry_cost, 6), "exit_cost_usd": round(exit_cost, 6),
            "frais_partie_fermee_usd": round(entry_cost + exit_cost, 6)}


# ─────────────── #7 donnée manquante ───────────────
def politique_data_missing(pos: dict, *, now_ms: float, grace_ms: float = 120_000.0,
                           slippage_stress_bps: float = 25.0) -> dict:
    """Dislocation sans carnet frais : on NE GARDE PAS indéfiniment. Grace period courte ; au-delà, sortie
    DATA_MISSING_TIMEOUT à un mark CONSERVATEUR (entrée, gain nul) + slippage de STRESS. Rend la décision."""
    # 🔴 ne PAS utiliser `or` : ts=0 est falsy et ferait sauter la référence (même piège que moteur_paper #166).
    ref = pos.get("ts_derniere_donnee_ms")
    if ref is None:
        ref = pos.get("ts_ouverture_ms")
    if ref is None:
        ref = now_ms
    depuis = float(now_ms) - float(ref)
    if depuis < grace_ms:
        return {"action": "ATTENDRE", "grace_restante_ms": round(grace_ms - depuis, 1)}
    return {"action": "SORTIE", "raison": "DATA_MISSING_TIMEOUT",
            "mark_conservateur": float(pos.get("prix_entree")),      # gain nul, conservateur
            "slippage_stress_bps": slippage_stress_bps}


__all__ = ["pnl_jambe", "pnl_deux_jambes", "snapshot_complet_ok", "classifier_changement_leader",
           "reduire_vers_cible", "politique_data_missing"]
