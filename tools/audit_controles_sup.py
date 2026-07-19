"""CONTRÔLES D'AUDIT SUPPLÉMENTAIRES — nés des pannes RÉELLES des 18-19/07.

Chaque contrôle ici est la généralisation d'un bug qui a coûté de l'argent ou de la vérité :

  A. **Unité ×30** (19/07) : `gain_net_24h_bps` publiait un cumul 30 jours sous un nom de taux
     journalier → la rotation churnait sur des surplus fantômes (−5,07 $). Le contrôle refuse
     toute affectation d'un nom `*_24h*` depuis une expression `horizon` sans division par des
     jours. Marqueur d'exemption : `audit:unite-ok` en fin de ligne (à justifier en revue).

  B. **Interrupteurs du lanceur** (13/07, récidive 18/07) : des piles entières éteintes ou des
     planchers à zéro passés en LIVE. Le contrôle lit LANCER_HYPERSMART.cmd et exige les valeurs
     SÛRES (exécution réelle à 0, planchers hauts, sniper fermé) et la cohérence
     lanceur ↔ registre du superviseur (une dérive = un collecteur non supervisé).

  C. **Provenance dYdX** (19/07) : le panneau Hyperliquid a affiché 3 773 refus d'un moteur
     dYdX arrêté. Le contrôle verrouille `AUTORISER_DYDX_LEGACY = False`.

  D. **Chiffre rassurant sorti de rien** (19/07, screenshot de Flo) : « PROFIT FACTOR ≥1 »
     affiché avec 35 trades clos à −5,44 $ (le PnL de SESSION valait 0 → `rp>=0` → « ≥1 »).
     Le contrôle interdit les repli-affichages optimistes ('≥1') dans l'UI.

  E. **Santé runtime** (WARN, non bloquant) : collecteurs muets, inputs périmés — pour que
     `resultat-audit.md` raconte AUSSI l'état opérationnel au moment de l'audit.

100 % lecture seule. Aucun ordre réel.
"""
from __future__ import annotations

import ast
import re
import time
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]


# ------------------------------------------------------------------ A. unités *_24h*

_MARQUEUR_OK = "audit:unite-ok"


def trouver_affectations_24h_suspectes(source: str, nom_fichier: str = "?") -> list[str]:
    """Affectations d'une cible `*_24h*` dont l'expression mentionne `horizon` SANS division
    par une variable de jours. Analyse ligne à ligne (robuste aux appels par mot-clé)."""
    suspects: list[str] = []
    for i, ligne in enumerate(source.splitlines(), 1):
        l = ligne.strip()
        if _MARQUEUR_OK in l or l.startswith("#"):
            continue
        # cible nommee *_24h* (affectation OU argument nomme) et expression cote droit
        m = re.match(r"^([A-Za-z_][\w\.\[\]'\" ]*_24h[\w]*\s*=|.*\bgain_net_24h_bps\s*=)\s*(.+)$", l)
        if not m:
            continue
        droite = m.group(2)
        if "horizon" not in droite:
            continue
        if re.search(r"/\s*(jours|days|nb_jours|jours_horizon)", droite):
            continue                      # divise par des jours : c'est un vrai taux journalier
        suspects.append("%s:%d: %s" % (nom_fichier, i, l[:140]))
    return suspects


def controle_unites_24h(racine: Path = RACINE) -> tuple[str, list[str]]:
    """(resume, erreurs). Parcourt src/ : un cumul deguise en taux journalier = ECHEC."""
    erreurs: list[str] = []
    fichiers = list((racine / "src").rglob("*.py"))
    for p in fichiers:
        try:
            texte = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if "_24h" not in texte or "horizon" not in texte:
            continue
        erreurs += trouver_affectations_24h_suspectes(texte, str(p.relative_to(racine)))
    return ("%d fichiers scannes, %d affectation(s) suspecte(s)" % (len(fichiers), len(erreurs)),
            erreurs)


# ------------------------------------------------------------------ B. interrupteurs lanceur

#: (regex a trouver dans LANCER, message si absent). Valeurs SURES exigees.
_EXIGENCES_LANCEUR: tuple[tuple[str, str], ...] = (
    (r'HL_ENABLE_MAINNET_EXECUTION=0"', "execution mainnet doit etre 0"),
    (r'HL_ENABLE_TESTNET_EXECUTION=0"', "execution testnet doit etre 0"),
    (r'HYPERSMART_SINGLE_WALLET_MIN_EDGE_BPS=9999"', "le mode sniper doit rester ferme (9999)"),
    (r'HYPERSMART_FUSION_COPY_MIN_WALLETS=[2-9]"', "consensus copy >= 2 wallets"),
)

_INTERDITS_LANCEUR: tuple[tuple[str, str], ...] = (
    (r'HYPERSMART_SIMULATION_MIN_EDGE_BPS=0(\.0)?"', "plancher d'edge a ZERO = fail-open (13/07)"),
    (r'HYPERSMART_SUPERVISEUR_COLLECTEURS=0"', "superviseur eteint = famine silencieuse (19/07)"),
)


def controle_interrupteurs_lanceur(racine: Path = RACINE) -> tuple[str, list[str]]:
    erreurs: list[str] = []
    chemin = racine / "LANCER_HYPERSMART.cmd"
    try:
        texte = chemin.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ("LANCER_HYPERSMART.cmd illisible", ["fichier lanceur absent ou illisible"])
    for motif, msg in _EXIGENCES_LANCEUR:
        if not re.search(motif, texte):
            erreurs.append("EXIGENCE absente du lanceur : %s (motif %r)" % (msg, motif))
    for motif, msg in _INTERDITS_LANCEUR:
        if re.search(motif, texte):
            erreurs.append("VALEUR INTERDITE dans le lanceur : %s" % msg)
    # coherence lanceur <-> registre du superviseur (la panne du 19/07 en silence, sinon)
    try:
        import sys
        sys.path.insert(0, str(racine / "src"))
        from hl_observer.ops.superviseur_collecteurs import REGISTRE
        lignes = [l for l in texte.splitlines()
                  if "boucle_collecteur.cmd" in l and l.strip().lower().startswith("start")]
        if len(lignes) != len(REGISTRE):
            erreurs.append("lanceur: %d collecteur(s), superviseur: %d — un collecteur non "
                           "supervise mourra en silence" % (len(lignes), len(REGISTRE)))
    except Exception as exc:  # noqa: BLE001
        erreurs.append("registre superviseur illisible : %s" % exc)
    return ("%d exigences, %d interdits verifies" % (len(_EXIGENCES_LANCEUR),
                                                     len(_INTERDITS_LANCEUR)), erreurs)


# ------------------------------------------------------------------ C. provenance dYdX

def controle_provenance_dydx(racine: Path = RACINE) -> tuple[str, list[str]]:
    chemin = racine / "src" / "hl_observer" / "simulation" / "log_metrics.py"
    try:
        texte = chemin.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ("log_metrics.py illisible", ["module de metriques introuvable"])
    if re.search(r"^AUTORISER_DYDX_LEGACY\s*=\s*False", texte, re.MULTILINE):
        return ("le panneau Hyperliquid ne peut pas lire le moteur dYdX legacy", [])
    return ("verrou de provenance ABSENT",
            ["AUTORISER_DYDX_LEGACY=False manquant dans log_metrics.py : le panneau HL peut "
             "de nouveau afficher les chiffres d'un autre moteur (bug du 19/07, commit 7bd5b43)"])


# ------------------------------------------------------------------ D. chiffre rassurant UI

#: replis optimistes interdits dans l'UI : afficher « >=1 » (rentable) quand la vraie valeur
#: est indisponible. Un tiret honnete vaut mieux qu'un chiffre rassurant sorti de rien.
_MOTIF_PF_OPTIMISTE = re.compile(r"[\"']≥ ?1[\"']|[\"']>=1[\"']")


def controle_ui_sans_chiffre_rassurant(racine: Path = RACINE) -> tuple[str, list[str]]:
    erreurs: list[str] = []
    ui = racine / "src" / "hl_observer" / "ui"
    fichiers = list(ui.rglob("*.py")) if ui.exists() else []
    for p in fichiers:
        try:
            texte = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for i, ligne in enumerate(texte.splitlines(), 1):
            if _MOTIF_PF_OPTIMISTE.search(ligne) and _MARQUEUR_OK not in ligne:
                erreurs.append("%s:%d: repli optimiste ('>=1') — afficher '—' quand la mesure "
                               "manque, jamais un chiffre rassurant" % (p.name, i))
    return ("%d fichier(s) UI scannes" % len(fichiers), erreurs)


# ------------------------------------------------------------------ E. sante runtime (WARN)

def controle_sante_runtime(racine: Path = RACINE, *, maintenant: float | None = None,
                           ) -> tuple[str, list[str]]:
    """(resume, AVERTISSEMENTS — jamais bloquant : l'etat du runtime n'est pas la qualite du code).
    Donne a `resultat-audit.md` la photo operationnelle du moment : collecteurs, inputs, ledger."""
    warns: list[str] = []
    now = maintenant if maintenant is not None else time.time()
    try:
        import sys
        sys.path.insert(0, str(racine / "src"))
        from hl_observer.ops.superviseur_collecteurs import etat_collecteurs
        for e in etat_collecteurs(racine, maintenant=now):
            if e["mort"]:
                warns.append("collecteur %s MUET (age %s min, limite %.0f) -> "
                             "REANIMER-COLLECTEURS.cmd ou redemarrer le bot"
                             % (e["nom"], e["age_minutes"], e["limite_minutes"]))
    except Exception as exc:  # noqa: BLE001
        warns.append("etat collecteurs illisible : %s" % exc)
    try:
        import json
        p = racine / "runtime" / "data" / "carry_spot_inputs.json"
        age_min = (now - p.stat().st_mtime) / 60.0
        if age_min > 15.0:
            warns.append("carry_spot_inputs.json perime (%.0f min > 15) : le carry refuse tout "
                         "(INPUTS_SPOT_PERIMES_NO_TRADE) tant que le feeder n'ecrit pas" % age_min)
        led = racine / "runtime" / "data" / "carry_paper_ledger.jsonl"
        if led.exists():
            evts = [json.loads(l) for l in led.read_text(encoding="utf-8").splitlines() if l.strip()]
            pnl = sum(e.get("realized_net_pnl_usdc") or 0.0 for e in evts if e.get("kind") == "CLOSE")
            n = sum(1 for e in evts if e.get("kind") == "CLOSE")
            warns.append("info: ledger carry = %+.4f $ realises sur %d fermeture(s) "
                         "(reference pour verifier le dashboard)" % (pnl, n))
    except Exception as exc:  # noqa: BLE001
        warns.append("lecture runtime partielle : %s" % exc)
    return ("photo operationnelle au moment de l'audit (n'affecte jamais le verdict)", warns)
