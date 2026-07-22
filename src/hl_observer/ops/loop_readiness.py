"""LOOP READINESS — un SCORE UNIQUE de maturité du bot + le niveau d'autonomie PERMIS.

ORIGINE (22/07) : repo `cobusgreyling/loop-engineering` (Cobus Greyling), analysé sur demande
de Flo. Sa meilleure idée réutilisable : `loop-audit` réduit un projet à UN score de maturité
(0-100) et à un NIVEAU D'AUTONOMIE (L0 brouillon → L1 rapport → L2 assisté → L3 non-surveillé),
avec la règle « score honnêtement — une boucle sans vérification n'est PAS prête ». Classement
portage : **COPY_ADAPTED**. Cousin de [[lecons_du_ledger]] (autre source « loop engineering »).

CE QU'ON PORTE, ET CE QU'ON REFUSE
----------------------------------
On refuse le framework npm (STATE.md/LOOP.md/gate.yaml : une 3ᵉ architecture, du code non
audité). On porte l'IDÉE, dans notre idiome, avec une lentille TRADING :

  * leur échelle L0-L3 devient NOTRE ladder de sécurité (addendum 2026-07-04) :
        N0 OBSERVE (mainnet lecture seule)  →  N1 PAPER (décision locale + simulation)
        →  N2 TESTNET (fausse monnaie, tous verrous).
  * le RÉEL n'est **jamais** un niveau atteignable. Il n'existe aucune constante « N3 » ici :
    la fonction ne PEUT PAS l'émettre. Le plafond est codé en dur.
  * `no_real_trade` n'est pas une dimension pondérée parmi d'autres : c'est un **GATE DUR**.
    La moindre brèche force le grade F et le niveau N0, quels que soient les autres signaux.

Ainsi ce module RENFORCE le no-real-trade au lieu de l'affaiblir : il ne « débloque » jamais
rien ; il refuse de déclarer prêt tant que la sécurité, la vérité du PnL, la fraîcheur des
données et les portes de coût ne sont pas TOUTES réunies. Deny-by-default : un signal absent
compte comme NON PRÊT (0), jamais comme supposé-vert — exactement la discipline `INSUFFISANT`.

CE QUE ÇA APPORTE À FLO
----------------------
Un seul nombre + une lettre + LE MAILLON FAIBLE nommé + le niveau d'autonomie actuellement
sûr. Là où le RECAP disait « 7/9 étapes vertes », on répond désormais « BOT-READY 72/100 (C) —
maillon faible : fraîcheur des données — autonomie sûre : N1 PAPER ». MESURE only : lire des
signaux et rendre un verdict n'est pas passer un ordre.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ── L'échelle d'autonomie : NOTRE ladder, pas la leur. Le réel n'y figure PAS. ──────────────
NIVEAU_OBSERVE = "N0_OBSERVE"                 # mainnet lecture seule — le plancher, toujours atteint
NIVEAU_PAPER = "N1_PAPER_DECIDE"              # décision locale + simulation paper (où vit le bot)
NIVEAU_TESTNET = "N2_TESTNET_VERROUILLE"      # testnet fausse monnaie, tous les verrous posés
#: Il n'existe volontairement AUCUN "N3_REEL". Un niveau qu'on ne nomme pas ne peut être émis.

MOTIF_BREACHE = "NO_REAL_TRADE_COMPROMIS_PLAFOND_N0"
SEUIL_DONNEES_FRAICHES = 0.80                 # < 80 % de couverture fraîche => on ne « trade » pas

#: (clé de signal, poids). Somme = 100. Poids pensés TRADING : la sécurité, la vérité du PnL,
#: la fraîcheur et le coût-net dominent ; l'ingénierie (tests/câblage/journal) complète.
DIMENSIONS: tuple[tuple[str, float, str], ...] = (
    ("securite_no_real_trade", 18.0, "no-real-trade intact (aucun chemin d'exécution réel)"),
    ("pnl_reconcilie",         16.0, "vérité du PnL : dashboard == ledger d'audit"),
    ("donnees_fraiches",       16.0, "fraîcheur des données (stale => NO_TRADE)"),
    ("tests_verts",            14.0, "suite de tests verte (un test rouge = une mesure qui ment)"),
    ("portes_cout_actives",    12.0, "portes d'edge NET après frais+spread+slippage câblées"),
    ("kill_switch_cable",      10.0, "kill-switch / halt gradué joignable depuis la porte"),
    ("cablage_sain",            8.0, "câblage : orphelins sous le plafond (mention != porte)"),
    ("journal_present",         6.0, "journal d'évidence / run-log présent (observabilité)"),
)


def _s(signaux: dict, cle: str) -> float | None:
    """Le signal `cle` normalisé dans [0,1], ou None si ABSENT (deny-by-default plus haut).
    Accepte bool (True=1) ou nombre déjà dans [0,1] (fraction). NaN/inf -> None."""
    if cle not in signaux or signaux[cle] is None:
        return None
    v = signaux[cle]
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    if isinstance(v, (int, float)):
        x = float(v)
        if x != x or x in (float("inf"), float("-inf")):
            return None
        return max(0.0, min(1.0, x))
    return None


@dataclass(frozen=True)
class RapportReadiness:
    score_0_100: float
    grade: str                                # A..F
    niveau_autonomie: str                     # N0 / N1 / N2 (jamais réel)
    maillon_faible: str
    no_real_trade_intact: bool
    dimensions: dict[str, dict] = field(default_factory=dict)
    drapeaux_rouges: list[str] = field(default_factory=list)
    real_execution: bool = False              # ce module ne fait que LIRE et JUGER

    def as_dict(self) -> dict[str, Any]:
        return {
            "score_0_100": self.score_0_100, "grade": self.grade,
            "niveau_autonomie": self.niveau_autonomie, "maillon_faible": self.maillon_faible,
            "no_real_trade_intact": self.no_real_trade_intact,
            "dimensions": self.dimensions, "drapeaux_rouges": self.drapeaux_rouges,
            "real_execution": False, "plafond": "N2_TESTNET_VERROUILLE (le RÉEL est hors échelle)",
        }


def _grade(score: float) -> str:
    return ("A" if score >= 90 else "B" if score >= 80 else "C" if score >= 70
            else "D" if score >= 60 else "F")


def evaluer(signaux: dict[str, Any], *, verrous_testnet: bool | None = None) -> RapportReadiness:
    """Le SCORE de maturité + le niveau d'autonomie permis, deny-by-default.

    `signaux` : un dict des clés de `DIMENSIONS` (bool ou fraction). Toute clé absente compte
    comme 0 (non prouvé = non prêt) et lève un drapeau. `verrous_testnet` : les verrous du
    ladder testnet (REAL_MAINNET_TRADING=false, TESTNET_ONLY=true…) — requis pour AUTORISER N2,
    jamais pour le réel.
    """
    dims: dict[str, dict] = {}
    drapeaux: list[str] = []
    score = 0.0
    for cle, poids, desc in DIMENSIONS:
        s = _s(signaux, cle)
        if s is None:
            drapeaux.append("évidence ABSENTE : %s (compté 0 — deny-by-default)" % cle)
            s = 0.0
        contrib = poids * s
        score += contrib
        dims[cle] = {"score": round(s, 3), "poids": poids, "points": round(contrib, 2),
                     "manque_points": round(poids * (1.0 - s), 2), "desc": desc}

    # ── LE GATE DUR : no-real-trade. Une brèche (ou une évidence absente) plafonne tout. ──
    secu = _s(signaux, "securite_no_real_trade")
    no_real_trade_intact = (secu == 1.0)
    if not no_real_trade_intact:
        drapeaux.insert(0, "🔴 NO-REAL-TRADE non prouvé intact : plafond N0, grade F "
                           "(la sécurité prime sur tout score)")
        maillon = "securite_no_real_trade"
        return RapportReadiness(min(round(score, 1), 15.0), "F", NIVEAU_OBSERVE, maillon,
                                False, dims, drapeaux)

    # ── quelques drapeaux « red flags » nommés (adaptés de leur checklist) ──
    if _s(signaux, "pnl_reconcilie") not in (None, 1.0):
        drapeaux.append("PnL dashboard != audit : la vérité du PnL est cassée")
    if (_s(signaux, "donnees_fraiches") or 0.0) < SEUIL_DONNEES_FRAICHES:
        drapeaux.append("données trop vieilles (< %d%% frais) : régime NO_TRADE"
                        % int(SEUIL_DONNEES_FRAICHES * 100))
    if _s(signaux, "tests_verts") not in (None, 1.0):
        drapeaux.append("tests rouges : une mesure ment peut-être — réparer avant d'avancer")

    # ── le niveau d'autonomie PERMIS (jamais le réel) ──
    tests_ok = _s(signaux, "tests_verts") == 1.0
    pnl_ok = _s(signaux, "pnl_reconcilie") == 1.0
    data_ok = (_s(signaux, "donnees_fraiches") or 0.0) >= SEUIL_DONNEES_FRAICHES
    niveau = NIVEAU_OBSERVE
    if tests_ok and pnl_ok and data_ok:
        niveau = NIVEAU_PAPER
        cout_ok = _s(signaux, "portes_cout_actives") == 1.0
        halt_ok = _s(signaux, "kill_switch_cable") == 1.0
        obs_ok = _s(signaux, "journal_present") == 1.0
        vt = bool(verrous_testnet)
        if cout_ok and halt_ok and obs_ok and vt:
            niveau = NIVEAU_TESTNET
        elif not vt:
            drapeaux.append("N2 testnet refusé : verrous testnet non prouvés "
                            "(REAL_MAINNET_TRADING=false, TESTNET_ONLY=true, caps)")

    maillon = max(DIMENSIONS, key=lambda d: dims[d[0]]["manque_points"])[0]
    return RapportReadiness(round(score, 1), _grade(score), niveau, maillon,
                            True, dims, drapeaux)


def markdown(rap: RapportReadiness) -> str:
    """Le bloc BOT-READY pour le RECAP / le rapport — dérivé, jamais inventé."""
    lignes = ["## 🤖 BOT-READY — %.0f/100 (%s) · autonomie sûre : %s"
              % (rap.score_0_100, rap.grade, rap.niveau_autonomie),
              "",
              "_Plafond codé en dur : **N2 testnet verrouillé**. Le trading RÉEL est hors "
              "échelle — ce score ne peut jamais l'autoriser._",
              "",
              "- maillon faible : **%s**" % rap.maillon_faible,
              "- no-real-trade intact : **%s**" % ("oui" if rap.no_real_trade_intact else "NON")]
    if rap.drapeaux_rouges:
        lignes.append("- drapeaux : " + " · ".join(rap.drapeaux_rouges[:4]))
    lignes += ["", "| dimension | points | /max |", "|---|---:|---:|"]
    for cle, poids, _desc in DIMENSIONS:
        d = rap.dimensions.get(cle, {})
        lignes.append("| %s | %.1f | %.0f |" % (cle, d.get("points", 0.0), poids))
    return "\n".join(lignes)


def depuis_etapes(etapes: dict[str, Any], *, verrous_testnet: bool | None = None
                  ) -> RapportReadiness:
    """ADAPTATEUR pour `tools/lanceur_tout_tester.py` : mappe les résultats d'étapes DÉJÀ
    calculés (securite/tests/cablage/donnees…) vers les signaux. On NE recalcule rien — on
    réutilise ce que l'audit a déjà mesuré (pas de doublon de travail).

    `etapes` : dict {nom_etape: {"statut": "OK"|"ECHEC"|..., ...}} tel que produit par le
    lanceur, éventuellement enrichi de `donnees_fraiches_pct`, `pnl_reconcilie`, etc.
    """
    def ok(nom: str) -> bool:
        e = etapes.get(nom) or {}
        return str(e.get("statut", "")).upper() in ("OK", "VERT", "PASS", "GREEN")

    frais = etapes.get("donnees_fraiches_pct")
    signaux = {
        "securite_no_real_trade": ok("securite"),
        "tests_verts": ok("tests"),
        "cablage_sain": ok("cablage") or ok("invariants"),
        "donnees_fraiches": (float(frais) / 100.0 if isinstance(frais, (int, float)) else
                             (1.0 if ok("donnees") else None)),
        # ces trois-là ne sont pas des étapes du lanceur : le lanceur peut les fournir
        # explicitement s'il les connaît, sinon deny-by-default (None -> 0).
        "pnl_reconcilie": etapes.get("pnl_reconcilie"),
        "portes_cout_actives": etapes.get("portes_cout_actives"),
        "kill_switch_cable": etapes.get("kill_switch_cable"),
        "journal_present": etapes.get("journal_present"),
    }
    return evaluer(signaux, verrous_testnet=verrous_testnet)


# ── LE COLLECTEUR : lire ce que le dernier TOUT-TESTER a DÉJÀ mesuré ─────────────────────────
# Centralisé ICI (et pas dans le tool) pour une source unique : le lanceur ET `tools/bot_ready.py`
# appellent `depuis_le_recap`. On NE recalcule rien — on lit le RECAP + les verrous testnet.

def _statuts_recap(recap: str) -> dict[str, str]:
    """Statuts par étape lus dans le tableau du RECAP (| nom | ✅ OK | … |). Tolérant."""
    statuts: dict[str, str] = {}
    for ligne in recap.splitlines():
        if not ligne.lstrip().startswith("|"):
            continue
        cols = [c.strip() for c in ligne.strip().strip("|").split("|")]
        if len(cols) < 2 or not cols[0]:
            continue
        cell = cols[1].upper()
        if "OK" in cell:
            statuts[cols[0]] = "OK"
        elif "ECHEC" in cell or "ÉCHEC" in cell or "FAIL" in cell:
            statuts[cols[0]] = "ECHEC"
        elif "BUDGET" in cell:
            statuts[cols[0]] = "BUDGET"
    return statuts


def _verrous_testnet(racine: Path) -> bool | None:
    """REAL_MAINNET_TRADING=false ET TESTNET_ONLY=true prouvés dans .env(.example). Sinon None."""
    txt = ""
    for nom in (".env", ".env.example"):
        p = racine / nom
        if p.exists():
            txt += "\n" + p.read_text(encoding="utf-8", errors="ignore")
    if not txt:
        return None
    real_off = re.search(r"REAL_MAINNET_TRADING\s*=\s*false", txt, re.I) is not None
    testnet_only = re.search(r"TESTNET_ONLY\s*=\s*true", txt, re.I) is not None
    return bool(real_off and testnet_only)


def depuis_le_recap(racine: str | Path, *, nom_recap: str = "RECAP-COMPLET.md"
                    ) -> RapportReadiness:
    """Le score dérivé du dernier RECAP. Deny-by-default : pas de RECAP -> sécurité non prouvée
    -> gate dur (F/N0). Les invariants gardés par des tests nommés (vérité du PnL, portes de
    coût, kill-switch) sont dérivés d'une suite VERTE — c'est leur preuve, pas une supposition."""
    racine = Path(racine)
    p = racine / nom_recap
    recap = p.read_text(encoding="utf-8", errors="ignore") if p.exists() else ""
    st = _statuts_recap(recap)
    m = re.search(r'"couverture_pct":\s*([0-9.]+)', recap)
    tests_ok = st.get("tests") == "OK"
    cablage_ok = st.get("cablage") == "OK" or st.get("invariants") == "OK"
    etapes = {
        "securite": {"statut": st.get("securite", "?")},
        "tests": {"statut": st.get("tests", "?")},
        "cablage": {"statut": st.get("cablage", st.get("invariants", "?"))},
        "donnees_fraiches_pct": float(m.group(1)) if m else None,
        "journal_present": bool(recap),
        # gardés par test_pnl_reconciliation / test_carry_benchmark_gate+arb_cout_all_in /
        # test_circuit_breaker+risk_guards : suite verte = preuve ; suite rouge = deny-by-default.
        "pnl_reconcilie": True if tests_ok else None,
        "portes_cout_actives": True if (tests_ok and cablage_ok) else None,
        "kill_switch_cable": True if (tests_ok and cablage_ok) else None,
    }
    return depuis_etapes(etapes, verrous_testnet=_verrous_testnet(racine))


__all__ = ["NIVEAU_OBSERVE", "NIVEAU_PAPER", "NIVEAU_TESTNET", "MOTIF_BREACHE",
           "SEUIL_DONNEES_FRAICHES", "DIMENSIONS", "RapportReadiness",
           "evaluer", "markdown", "depuis_etapes", "depuis_le_recap"]
