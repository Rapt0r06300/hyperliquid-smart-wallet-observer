"""Contrôles supplémentaires issus des incidents runtime réels.

Lecture seule : unités, interrupteurs du lanceur, provenance dYdX, UI honnête et santé runtime.
Le contrôle collecteurs suit désormais l'architecture canonique actuelle : LANCER_HYPERSMART.cmd
appelle le superviseur avec le profil HARVEST. Les anciennes lignes `start boucle_collecteur.cmd`
placées après `exit /b` sont du legacy mort et ne doivent plus être comparées au registre complet.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
_MARQUEUR_OK = "audit:unite-ok"


def trouver_affectations_24h_suspectes(source: str, nom_fichier: str = "?") -> list[str]:
    suspects: list[str] = []
    for i, ligne in enumerate(source.splitlines(), 1):
        l = ligne.strip()
        if _MARQUEUR_OK in l or l.startswith("#"):
            continue
        m = re.match(r"^([A-Za-z_][\w\.\[\]'\" ]*_24h[\w]*\s*=|.*\bgain_net_24h_bps\s*=)\s*(.+)$", l)
        if not m:
            continue
        droite = m.group(2)
        if "horizon" not in droite:
            continue
        if re.search(r"/\s*(jours|days|nb_jours|jours_horizon)", droite):
            continue
        suspects.append("%s:%d: %s" % (nom_fichier, i, l[:140]))
    return suspects


def controle_unites_24h(racine: Path = RACINE) -> tuple[str, list[str]]:
    erreurs: list[str] = []
    fichiers = list((racine / "src").rglob("*.py"))
    for p in fichiers:
        try:
            texte = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if "_24h" in texte and "horizon" in texte:
            erreurs += trouver_affectations_24h_suspectes(texte, str(p.relative_to(racine)))
    return "%d fichiers scannes, %d affectation(s) suspecte(s)" % (len(fichiers), len(erreurs)), erreurs


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


def _bloc_demarrer_collecteurs(texte: str) -> str:
    lignes = texte.splitlines()
    debut = next((i for i, l in enumerate(lignes) if l.strip().lower() == ":demarrer_collecteurs"), None)
    if debut is None:
        return ""
    fin = len(lignes)
    for i in range(debut + 1, len(lignes)):
        s = lignes[i].strip()
        if s.startswith(":") and not s.startswith("::"):
            fin = i
            break
    return "\n".join(lignes[debut:fin])


def controle_interrupteurs_lanceur(racine: Path = RACINE) -> tuple[str, list[str]]:
    erreurs: list[str] = []
    chemin = racine / "LANCER_HYPERSMART.cmd"
    try:
        texte = chemin.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return "LANCER_HYPERSMART.cmd illisible", ["fichier lanceur absent ou illisible"]

    for motif, msg in _EXIGENCES_LANCEUR:
        if not re.search(motif, texte):
            erreurs.append("EXIGENCE absente du lanceur : %s (motif %r)" % (msg, motif))
    for motif, msg in _INTERDITS_LANCEUR:
        if re.search(motif, texte):
            erreurs.append("VALEUR INTERDITE dans le lanceur : %s" % msg)

    bloc = _bloc_demarrer_collecteurs(texte)
    canonique = "superviseur_collecteurs demarrer-tous harvest"
    if canonique not in bloc:
        erreurs.append("CABlAGE collecteurs absent : le lanceur doit appeler `%s` dans :demarrer_collecteurs" % canonique)

    # Aucun `start ... boucle_collecteur.cmd` ne doit être atteignable AVANT le premier exit /b.
    # Le legacy conservé après la sortie ne participe plus au runtime actif.
    if bloc:
        low = bloc.lower()
        pos_exit = low.find("exit /b")
        actif = bloc if pos_exit < 0 else bloc[:pos_exit]
        manuels = [l.strip() for l in actif.splitlines()
                   if l.strip().lower().startswith("start ") and "boucle_collecteur.cmd" in l.lower()]
        if manuels:
            erreurs.append("collecteur(s) manuel(s) encore atteignable(s) hors superviseur : %s" % "; ".join(manuels[:3]))

    try:
        import sys
        chemin_src = str(racine / "src")
        if chemin_src not in sys.path:
            sys.path.insert(0, chemin_src)
        from hl_observer.ops.superviseur_collecteurs import (
            COLLECTEURS_CORE,
            REGISTRE,
            collecteurs_pour_profil,
        )
        registre = {c["nom"] for c in REGISTRE}
        harvest = {c["nom"] for c in collecteurs_pour_profil("harvest")}
        if not harvest:
            erreurs.append("profil HARVEST vide : aucune collecte ne serait demarree")
        inconnus = harvest - registre
        if inconnus:
            erreurs.append("profil HARVEST reference des collecteurs hors REGISTRE : %s" % sorted(inconnus))
        manquants_core = set(COLLECTEURS_CORE) - harvest
        if manquants_core:
            erreurs.append("profil HARVEST incomplet : CORE manquant %s" % sorted(manquants_core))
    except Exception as exc:  # noqa: BLE001
        erreurs.append("registre superviseur illisible : %s" % exc)

    return "%d exigences, %d interdits + cablage HARVEST verifies" % (
        len(_EXIGENCES_LANCEUR), len(_INTERDITS_LANCEUR)
    ), erreurs


def controle_provenance_dydx(racine: Path = RACINE) -> tuple[str, list[str]]:
    chemin = racine / "src" / "hl_observer" / "simulation" / "log_metrics.py"
    try:
        texte = chemin.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return "log_metrics.py illisible", ["module de metriques introuvable"]
    if re.search(r"^AUTORISER_DYDX_LEGACY\s*=\s*False", texte, re.MULTILINE):
        return "le panneau Hyperliquid ne peut pas lire le moteur dYdX legacy", []
    return "verrou de provenance ABSENT", [
        "AUTORISER_DYDX_LEGACY=False manquant dans log_metrics.py : le panneau HL peut de nouveau afficher les chiffres d'un autre moteur (bug du 19/07, commit 7bd5b43)"
    ]


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
                erreurs.append("%s:%d: repli optimiste ('>=1') — afficher '—' quand la mesure manque, jamais un chiffre rassurant" % (p.name, i))
    return "%d fichier(s) UI scannes" % len(fichiers), erreurs


def controle_sante_runtime(racine: Path = RACINE, *, maintenant: float | None = None) -> tuple[str, list[str]]:
    warns: list[str] = []
    now = maintenant if maintenant is not None else time.time()
    try:
        import sys
        chemin_src = str(racine / "src")
        if chemin_src not in sys.path:
            sys.path.insert(0, chemin_src)
        from hl_observer.ops.superviseur_collecteurs import etat_collecteurs
        for e in etat_collecteurs(racine, maintenant=now):
            if e["mort"]:
                warns.append("collecteur %s MUET (age %s min, limite %.0f) -> REANIMER-COLLECTEURS.cmd ou redemarrer le bot"
                             % (e["nom"], e["age_minutes"], e["limite_minutes"]))
    except Exception as exc:  # noqa: BLE001
        warns.append("etat collecteurs illisible : %s" % exc)

    p = racine / "runtime" / "data" / "carry_spot_inputs.json"
    try:
        age_min = (now - p.stat().st_mtime) / 60.0
        if age_min > 15.0:
            warns.append("carry_spot_inputs.json perime (%.0f min > 15) : le carry refuse tout (INPUTS_SPOT_PERIMES_NO_TRADE) tant que le feeder n'ecrit pas" % age_min)
    except FileNotFoundError:
        warns.append("carry_spot_inputs.json absent : etat carry indisponible")
    except OSError as exc:
        warns.append("carry_spot_inputs.json illisible : %s" % exc)

    led = racine / "runtime" / "data" / "carry_paper_ledger.jsonl"
    try:
        if led.exists():
            evts = [json.loads(l) for l in led.read_text(encoding="utf-8").splitlines() if l.strip()]
            pnl = sum(e.get("realized_net_pnl_usdc") or 0.0 for e in evts if e.get("kind") == "CLOSE")
            n = sum(1 for e in evts if e.get("kind") == "CLOSE")
            warns.append("info: ledger carry = %+.4f $ realises sur %d fermeture(s) (reference pour verifier le dashboard)" % (pnl, n))
        else:
            warns.append("info: ledger carry = indisponible (fichier absent, aucun PnL invente)")
    except Exception as exc:  # noqa: BLE001
        warns.append("info: ledger carry = illisible (%s)" % exc)
    return "photo operationnelle au moment de l'audit (n'affecte jamais le verdict)", warns
