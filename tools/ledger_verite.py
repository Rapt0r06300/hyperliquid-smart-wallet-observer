"""LEDGER REPRODUCTIBLE, CRASH RECOVERY EXACT, TRUTH RECONCILER (IDEA-11, 33, 34, 35).

`portefeuille_global` tient déjà un ledger d'événements et sait le réconcilier. Ce qui manquait pour que le
PnL soit VÉRIFIABLE plutôt que cru sur parole :

  • IDEA-33 : chaque événement porte `event_seq` (monotone), `event_id`, `candidate_id`, timestamp,
    requested/filled_notional, fill_fraction, `price_source`, coûts et `state_version` ;
  • IDEA-34 : reprise EXACTE quand le ledger a été appendé mais le snapshot pas sauvegardé —
    `last_applied_event_seq` + rejeu IDEMPOTENT (rejouer deux fois ne double jamais le PnL) ;
  • IDEA-35 : snapshot corrompu ≠ portefeuille neuf — `RECOVERY_REQUIRED`, reconstruction depuis le ledger
    ou blocage deny-by-default. Le cash n'est JAMAIS réinitialisé en silence ;
  • IDEA-11 : TruthReconciler — la chaîne CANONICAL EVENT → SIGNAL → PAPER FILL → OPEN → REDUCE → CLOSE →
    COSTS → CANDIDATE PNL → PORTFOLIO PNL → DASHBOARD doit se recouper à chaque maillon. Toute divergence
    donne PNL_UNTRUSTED + quarantaine + promotion interdite.

Calcul pur (+ lecture fichier) : 0 réseau, 0 ordre, paper-only.
"""
from __future__ import annotations

import json
from pathlib import Path

STATE_VERSION = 1

#: maillons de la chaîne de vérité (IDEA-11), dans l'ordre.
CHAINE = ("CANONICAL_EVENT", "SIGNAL", "PAPER_FILL", "OPEN", "REDUCE", "CLOSE",
          "COSTS", "CANDIDATE_PNL", "PORTFOLIO_PNL", "DASHBOARD")

RECOVERY_REQUIRED = "RECOVERY_REQUIRED"
LEDGER_CORRUPTED = "LEDGER_CORRUPTED"
PNL_UNTRUSTED = "PNL_UNTRUSTED"
OK = "OK"


def evenement_ledger(*, event_seq: int, event_id: str, candidate_id: str, type_: str, ts_ms: float,
                     requested_notional=None, filled_notional=None, price_source: str | None = None,
                     couts_bps: dict | None = None, pnl_usd=None, cout_usd=None,
                     state_version: int = STATE_VERSION) -> dict:
    """IDEA-33 — un événement de ledger COMPLET et reproductible. `fill_fraction` est dérivée, jamais
    supposée : sans requested_notional, elle vaut None (et non 1.0)."""
    req = None if requested_notional is None else float(requested_notional)
    fil = None if filled_notional is None else float(filled_notional)
    frac = (round(fil / req, 6) if (req and req > 0 and fil is not None) else None)
    return {"event_seq": int(event_seq), "event_id": str(event_id), "candidate_id": str(candidate_id),
            "type": str(type_).upper(), "ts_ms": float(ts_ms),
            "requested_notional": req, "filled_notional": fil, "fill_fraction": frac,
            "price_source": price_source, "couts_bps": dict(couts_bps or {}),
            "pnl_usd": (None if pnl_usd is None else float(pnl_usd)),
            "cout_usd": (None if cout_usd is None else float(cout_usd)),
            "state_version": int(state_version)}


def lire_ledger(chemin: Path, *, strict: bool = True) -> dict:
    """IDEA-36-adjacent (déjà utile ici) : une ligne JSON invalide n'est JAMAIS ignorée en silence — on rend
    LEDGER_CORRUPTED avec le numéro de ligne et l'offset. `strict=False` permet un diagnostic partiel."""
    p = Path(chemin)
    evts, erreurs = [], []
    if not p.exists():
        return {"statut": OK, "evenements": [], "erreurs": [], "n": 0}
    offset = 0
    with p.open("r", encoding="utf-8", errors="ignore") as f:
        for i, ligne in enumerate(f, 1):
            brut = ligne.rstrip("\n")
            try:
                evts.append(json.loads(brut))
            except ValueError as e:
                erreurs.append({"ligne": i, "offset": offset, "erreur": str(e)[:120]})
                if strict:
                    break
            offset += len(ligne.encode("utf-8"))
    statut = LEDGER_CORRUPTED if erreurs else OK
    return {"statut": statut, "evenements": evts, "erreurs": erreurs, "n": len(evts),
            "promotion_autorisee": not erreurs}


def rejouer(evenements, *, capital_initial: float = 1000.0, levier: float = 3.0,
            depuis_seq: int = 0) -> dict:
    """IDEA-34 — rejeu IDEMPOTENT : seuls les événements dont `event_seq > depuis_seq` sont appliqués.
    Rejouer deux fois le même ledger donne EXACTEMENT le même état (aucun double comptage)."""
    cash = float(capital_initial)
    realized = 0.0
    marge = 0.0
    dernier = int(depuis_seq)
    vus = set()
    n_appliques = 0
    for e in sorted(evenements or [], key=lambda x: int(x.get("event_seq", 0))):
        seq = int(e.get("event_seq", 0))
        if seq <= int(depuis_seq) or seq in vus:
            continue                                          # déjà appliqué : on n'applique jamais deux fois
        vus.add(seq)
        t = str(e.get("type", "")).upper()
        notional = float(e.get("filled_notional") or e.get("requested_notional") or 0.0)
        m = abs(notional) / max(1e-9, float(levier))
        cout = float(e.get("cout_usd") or 0.0)
        pnl = float(e.get("pnl_usd") or 0.0)
        if t in ("OPEN", "ADD"):
            cash -= (m + cout); realized -= cout; marge += m
        elif t in ("REDUCE", "CLOSE"):
            cash += (m + pnl - cout); realized += pnl - cout; marge = max(0.0, marge - m)
        dernier = max(dernier, seq)
        n_appliques += 1
    return {"cash": round(cash, 6), "realized": round(realized, 6), "marge_engagee": round(marge, 6),
            "equity": round(cash + marge, 6), "last_applied_event_seq": dernier,
            "n_appliques": n_appliques, "state_version": STATE_VERSION}


def reprise_apres_crash(chemin_ledger: Path, snapshot: dict | None, *, capital_initial: float = 1000.0,
                        levier: float = 3.0) -> dict:
    """IDEA-34/35 — reprise EXACTE.

    • ledger illisible                      -> LEDGER_CORRUPTED, aucune reconstruction hasardeuse ;
    • snapshot absent/corrompu + ledger OK  -> RECOVERY_REQUIRED puis reconstruction COMPLÈTE depuis le
      ledger (le cash n'est jamais remis à neuf en silence) ;
    • snapshot valide                       -> on n'applique que la QUEUE (event_seq > last_applied_event_seq)."""
    lu = lire_ledger(chemin_ledger, strict=True)
    if lu["statut"] == LEDGER_CORRUPTED:
        return {"statut": LEDGER_CORRUPTED, "erreurs": lu["erreurs"],
                "promotion_autorisee": False, "etat": None,
                "motif": "ledger illisible — reconstruction refusee (deny-by-default)"}
    snap_valide = isinstance(snapshot, dict) and all(
        isinstance(snapshot.get(k), (int, float)) for k in ("cash", "realized")
    ) and isinstance(snapshot.get("last_applied_event_seq"), int)
    if not snap_valide:
        etat = rejouer(lu["evenements"], capital_initial=capital_initial, levier=levier, depuis_seq=0)
        return {"statut": RECOVERY_REQUIRED, "etat": etat, "promotion_autorisee": True,
                "reconstruit_depuis_ledger": True,
                "motif": "snapshot absent ou invalide — reconstruit depuis le ledger, cash JAMAIS remis a neuf"}
    depuis = int(snapshot["last_applied_event_seq"])
    queue = rejouer(lu["evenements"], capital_initial=float(snapshot["cash"]), levier=levier, depuis_seq=depuis)
    return {"statut": OK, "etat": {**queue, "realized": round(float(snapshot["realized"]) + queue["realized"], 6)},
            "promotion_autorisee": True, "reconstruit_depuis_ledger": False,
            "motif": "snapshot valide — seule la queue du ledger a ete appliquee"}


class TruthReconciler:
    """IDEA-11 — recoupe la chaîne de vérité maillon par maillon, POUR CHAQUE CANDIDAT.

    On ne compare pas des impressions : chaque maillon apporte un nombre, et deux maillons voisins doivent
    concorder à la tolérance près. La moindre divergence produit PNL_UNTRUSTED + quarantaine du candidat +
    interdiction de promotion (on ne « corrige » jamais un chiffre pour faire coller le tableau de bord)."""

    def __init__(self, *, tolerance_usd: float = 1e-4):
        self.tolerance = float(tolerance_usd)

    def verifier_candidat(self, candidate_id: str, maillons: dict) -> dict:
        """`maillons` : {maillon: valeur}. Les maillons de COMPTAGE (événements/signaux/fills/open/close)
        sont des entiers ; les maillons de PnL sont des USD. Un maillon absent = UNMEASURABLE (bloquant)."""
        manquants = [m for m in CHAINE if m not in (maillons or {})]
        ecarts = []
        m = maillons or {}
        # comptages : on ne peut pas avoir plus de fills que de signaux, ni plus d'OPEN que de fills.
        for amont, aval in (("SIGNAL", "PAPER_FILL"), ("PAPER_FILL", "OPEN"), ("OPEN", "CLOSE")):
            a, b = m.get(amont), m.get(aval)
            if isinstance(a, (int, float)) and isinstance(b, (int, float)) and b > a:
                ecarts.append({"maillon": "%s>%s" % (aval, amont), "amont": a, "aval": b,
                               "motif": "plus d'aval que d'amont — impossible"})
        # PnL : candidat == portefeuille == dashboard, à la tolérance près.
        for amont, aval in (("CANDIDATE_PNL", "PORTFOLIO_PNL"), ("PORTFOLIO_PNL", "DASHBOARD")):
            a, b = m.get(amont), m.get(aval)
            if isinstance(a, (int, float)) and isinstance(b, (int, float)) and abs(a - b) > self.tolerance:
                ecarts.append({"maillon": "%s vs %s" % (amont, aval), "amont": a, "aval": b,
                               "ecart": round(abs(a - b), 6)})
        fiable = not ecarts and not manquants
        return {"candidate_id": str(candidate_id),
                "statut": (OK if fiable else PNL_UNTRUSTED),
                "quarantaine": not fiable,
                "promotion_autorisee": fiable,
                "maillons_manquants": manquants, "ecarts": ecarts,
                "tolerance_usd": self.tolerance}

    def verifier_tous(self, par_candidat: dict) -> dict:
        res = {cid: self.verifier_candidat(cid, m) for cid, m in (par_candidat or {}).items()}
        en_quarantaine = [c for c, r in res.items() if r["quarantaine"]]
        return {"resultats": res, "n_candidats": len(res),
                "n_quarantaine": len(en_quarantaine), "quarantaine": en_quarantaine,
                "promotion_globale_autorisee": not en_quarantaine}


__all__ = ["STATE_VERSION", "CHAINE", "RECOVERY_REQUIRED", "LEDGER_CORRUPTED", "PNL_UNTRUSTED", "OK",
           "evenement_ledger", "lire_ledger", "rejouer", "reprise_apres_crash", "TruthReconciler"]
