"""ETA VIVANT : combien de temps encore collecter pour que le labo ait ce qu'il lui faut ?

CE QUI BLOQUE LE LABO, mesure et non suppose (22/11/2026). Sa porte n'est pas un volume
d'octets : c'est **le nombre de JOURNEES UTC distinctes et DENSES** de signaux evaluables.

* evaluable = un signal dont le carnet causal le plus recent le precede de moins de 30 s
  (`copy_vault_signal_alignment.MAX_BOOK_AGE_MS`) ;
* dense = la journee porte au moins `MIN_SIGNALS_PER_DAY` signaux evaluables ;
* requis = `diagnostic_signal.MINIMUM_SIGNAL_UTC_DAYS` journees denses DANS UNE tranche
  (`_bounds`, plancher absolu 3).

LE DÉBIT GLOBAL DES FICHIERS N'EST PAS UN DÉBIT DE SIGNAUX. La jauge de collecte mesure
les écritures de tous les fichiers locaux, mais elle ne prouve pas combien de signaux ont
un carnet L2 causal. Sans compteur frais de ces signaux évaluables, l'ETA moteur reste
INCONNU. La date des études reste une estimation distincte, calculée à partir des jours
indépendants encore requis par la dernière étude.

TROIS REFUS PLUTOT QU'UN CHIFFRE RASSURANT :

* debit nul -> `INFINI (collecte eteinte)`, jamais une duree ;
* corpus illisible -> `INCONNU` avec le motif, jamais zero ;
* journees deja suffisantes -> `ATTEINT`, et on le dit au lieu de proposer d'attendre.

LECTURE SEULE. Aucun reseau, aucun ordre, aucune ecriture dans les rubans. Le débit global
des fichiers est mesuré à chaque rafraîchissement sur leur croissance; le compte des jours
denses provient de la dernière sonde et son âge est affiché.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
REPOSITORY_CANONIQUE = "Rapt0r06300/hyperliquid-smart-wallet-observer"
if str(RACINE / "src") not in sys.path:
    sys.path.insert(0, str(RACINE / "src"))
if str(RACINE / "tools") not in sys.path:
    sys.path.insert(0, str(RACINE / "tools"))

from hl_observer.backtesting import diagnostic_signal as DS  # noqa: E402
from hl_observer.backtesting.copy_vault_signal_alignment import (  # noqa: E402
    MIN_SIGNALS_PER_DAY,
)

#: Le ruban de fills vit a la racine OU dans le workspace du labo selon la campagne.
#: On cherche, et on DIT lequel a servi : un "ruban illisible" doit nommer ce qu'il a
#: cherche, sinon on croit a une collecte morte alors qu'on regardait au mauvais endroit
#: (mesure du 22/11/2026, premier essai de cet outil).
RUBANS_FILLS = (
    # 24/11/2026 : le ruban WS (`vault_fills_live`) ne bouge presque pas (0,0 ligne/min affiché) alors que le POLL
    # REST grossit de ~2,3 Mo/min -- c'est lui la collecte (le WS rate 16,6 % des fills que le poll capte).
    "runtime/data/vault_fills_poll.jsonl",
    "runtime/data/vault_fills_live.jsonl",
    "runtime/labo_tranches_20261121/workspace/runtime/data/vault_fills_live.jsonl",
)

JOURNAL_COLLECTEURS = Path("runtime/logs/economic-collector-watchdog.jsonl")
AGE_MAX_JOURNAL_COLLECTEURS_S = 120
TAILLE_MAX_LECTURE_JOURNAL_COLLECTEURS = 64 * 1024


def lire_suivi_collecteurs(
    racine: Path,
    *,
    maintenant_ms: int | None = None,
    age_max_s: int = AGE_MAX_JOURNAL_COLLECTEURS_S,
) -> dict:
    """Lit le dernier relevé du watchdog, sans démarrer ni piloter les collecteurs.

    La présence d'un PID ne prouve pas la qualité des données : l'état des processus,
    le protocole causal et les gaps restent des champs séparés. Un journal absent,
    tronqué, trop ancien ou non PAPER/READ-ONLY donne un état INCONNU.
    """
    chemin = Path(racine) / JOURNAL_COLLECTEURS

    def inconnu(motif: str) -> dict:
        return {"code": "INCONNU", "motif": motif}

    try:
        with chemin.open("rb") as fichier:
            fichier.seek(0, os.SEEK_END)
            taille = fichier.tell()
            if taille <= 0:
                return inconnu("journal vide")
            debut = max(0, taille - TAILLE_MAX_LECTURE_JOURNAL_COLLECTEURS)
            fichier.seek(debut)
            contenu = fichier.read()
    except OSError:
        return inconnu("journal absent ou illisible")

    if debut:
        separateur = contenu.find(b"\n")
        if separateur < 0:
            return inconnu("dernière ligne trop longue")
        contenu = contenu[separateur + 1 :]
    if not contenu.endswith(b"\n"):
        return inconnu("dernière écriture incomplète")
    ligne = contenu.rstrip(b"\r\n").rsplit(b"\n", 1)[-1]
    if not ligne or len(ligne) > TAILLE_MAX_LECTURE_JOURNAL_COLLECTEURS:
        return inconnu("dernière ligne vide ou trop longue")
    try:
        releve = json.loads(ligne.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return inconnu("dernière ligne JSON invalide")
    if not isinstance(releve, dict):
        return inconnu("format du relevé invalide")
    if releve.get("paper_read_only") is not True or releve.get("real_execution") is not False:
        return inconnu("contrat PAPER/READ-ONLY non confirmé")

    ts_ms = releve.get("ts_ms")
    if type(ts_ms) is not int or ts_ms <= 0:
        return inconnu("horodatage du relevé invalide")
    now_ms = int(time.time() * 1000) if maintenant_ms is None else maintenant_ms
    if type(now_ms) is not int or now_ms < ts_ms:
        return inconnu("horloge incohérente")
    age_s = (now_ms - ts_ms) / 1000.0

    statut_source = releve.get("status")
    if statut_source == "WATCH_PASS_ERROR":
        return {
            "code": "ERREUR",
            "motif": str(releve.get("error") or "échec du cycle watchdog")[:160],
            "age_s": age_s,
        }
    demandes = releve.get("requested")
    actifs_source = releve.get("active")
    manquants_source = releve.get("missing")
    if not all(isinstance(valeur, list) for valeur in (demandes, actifs_source, manquants_source)):
        return inconnu("inventaire des collecteurs invalide")
    if any(not isinstance(nom, str) or not nom for nom in demandes + actifs_source + manquants_source):
        return inconnu("nom de collecteur invalide")
    if (
        len(set(demandes)) != len(demandes)
        or len(set(actifs_source)) != len(actifs_source)
        or len(set(manquants_source)) != len(manquants_source)
    ):
        return inconnu("noms de collecteurs dupliqués")
    demandes_set = set(demandes)
    actifs_set = set(actifs_source)
    manquants_set = set(manquants_source)
    attendus_manquants = demandes_set - actifs_set
    if not demandes or manquants_set != attendus_manquants:
        return inconnu("inventaire actif/manquant incohérent")

    actifs = len(demandes_set & actifs_set)
    gaps = releve.get("causal_evidence_reported_gaps")
    nouveaux_gaps = releve.get("causal_evidence_gaps_since_start")
    gaps = gaps if type(gaps) is int and gaps >= 0 else None
    nouveaux_gaps = nouveaux_gaps if type(nouveaux_gaps) is int and nouveaux_gaps >= 0 else None
    protocole = releve.get("causal_protocol_status")
    bail = releve.get("lease_renewal")
    details = releve.get("causal_evidence_detail")
    if not isinstance(details, dict):
        details = None

    if age_s > max(0, int(age_max_s)):
        code = "PERIME"
    elif statut_source == "ACTIVE" and actifs == len(demandes) and bail == "OK":
        code = "ACTIF"
    elif statut_source == "STARTING":
        code = "DEMARRAGE"
    elif statut_source in {"DEGRADED", "WATCH_PASS_ERROR"} or actifs < len(demandes) or bail != "OK":
        code = "DEGRADE"
    else:
        return inconnu("statut watchdog non reconnu")

    return {
        "code": code,
        "statut_source": statut_source,
        "actifs": actifs,
        "demandes": len(demandes),
        "manquants": len(attendus_manquants),
        "age_s": age_s,
        "gaps_causaux": gaps,
        "nouveaux_gaps": nouveaux_gaps,
        "detail": details,
        "protocole": str(protocole or "INCONNU"),
        "bail": str(bail or "INCONNU"),
    }


def _lignes_suivi_collecteurs(suivi: dict | None) -> list[str]:
    """Formate la santé process sans confondre présence et preuve de continuité."""
    if not isinstance(suivi, dict):
        return ["| COLLECTEURS        : INCONNU — aucun relevé du superviseur"]
    code = suivi.get("code")
    age_s = suivi.get("age_s")
    age_txt = (
        f"{age_s:.0f} s" if isinstance(age_s, (int, float)) and age_s < 60
        else f"{age_s / 60:.1f} min" if isinstance(age_s, (int, float))
        else "âge inconnu"
    )
    if code == "ACTIF":
        etat = f"{suivi.get('actifs', 0)}/{suivi.get('demandes', 0)} actifs, relevé {age_txt}"
    elif code == "PERIME":
        etat = f"dernier relevé périmé ({age_txt})"
    elif code == "ERREUR":
        etat = f"ERREUR superviseur — {suivi.get('motif') or 'cycle non confirmé'}"
    elif code in {"DEGRADE", "DEMARRAGE"}:
        etat = (
            f"{suivi.get('actifs', 0)}/{suivi.get('demandes', 0)} actifs, "
            f"{suivi.get('manquants', 0)} manquants ({code.lower()})"
        )
    else:
        etat = f"INCONNU — {suivi.get('motif') or 'état non vérifiable'}"

    gaps = suivi.get("gaps_causaux")
    if type(gaps) is int:
        etat += f" | écarts signalés: {gaps:,}".replace(",", " ")
        nouveaux = suivi.get("nouveaux_gaps")
        if type(nouveaux) is int:
            etat += f" (+{nouveaux} depuis lancement du suivi)"
    protocole = suivi.get("protocole")
    if protocole and protocole != "OK":
        etat += f" | protocole: {protocole}"
    bail = suivi.get("bail")
    if bail and bail != "OK":
        etat += f" | bail: {bail}"
    return [f"| COLLECTEURS : {etat}"]


def _lignes_detail_suivi_collecteurs(suivi: dict | None) -> list[str]:
    """N'affiche le détail que si le heartbeat porte le nouveau contrat de reçu."""
    detail = suivi.get("detail") if isinstance(suivi, dict) else None
    if not isinstance(detail, dict) or detail.get("coverage_receipt_status") not in {
        "PROVEN", "UNMEASURABLE"
    }:
        return []
    champs = (
        ("checkpoint_expirations", "expirés"),
        ("invalid_rejected", "rejets invalides"),
        ("input_rotations", "rotations"),
        ("writer_outages", "interruptions écrivain"),
        ("checkpoint_queue_rejections", "débords file"),
    )
    morceaux = [
        f"{etiquette} {detail[cle]}"
        for cle, etiquette in champs
        if type(detail.get(cle)) is int and detail[cle] > 0
    ]
    contenu = "; ".join(morceaux) if morceaux else "aucun incident signalé"
    return [f"| DÉTAIL PREUVE     : {detail['coverage_receipt_status']} | {contenu}"]


def trouver_ruban(racine) -> tuple[Path | None, list[str]]:
    """Le premier ruban existant, et la liste de ce qui a ete cherche."""
    cherches: list[str] = []
    for relatif in RUBANS_FILLS:
        cherches.append(relatif)
        candidat = Path(racine) / relatif
        if candidat.is_file():
            return candidat, cherches
    return None, cherches


def trouver_sonde(racine: Path, sonde: str | None = None) -> Path | None:
    """Retourne la sonde demandee, ou le rapport horloges le plus recent.

    Le lanceur reste compatible avec ``--sonde`` pour rejouer un rapport précis. Sans
    ce paramètre, un nom daté codé en dur finissait par figer l'ETA sur une mesure
    ancienne ; le dernier rapport disponible est donc choisi à chaque rafraîchissement.
    """
    if sonde:
        candidate = Path(sonde)
        if not candidate.is_absolute():
            candidate = racine / candidate
        return candidate if candidate.is_file() else None
    dossier = racine / "runtime" / "reports"
    candidats = [p for p in dossier.glob("sonde_horloges_*.json") if p.is_file()]
    if not candidats:
        return None
    return max(candidats, key=lambda p: (p.stat().st_mtime_ns, p.name))


def lire_sonde_denses(racine: Path, sonde: str | None = None) -> tuple[int, str, float | None]:
    """Lit le nombre de journées denses et l'âge du rapport courant."""
    chemin = trouver_sonde(racine, sonde)
    if chemin is None:
        return 0, "AUCUNE (aucune sonde lue : le compte des journees est INCONNU)", None
    charge = _charger_etat_de_fond(chemin)
    age_h: float | None
    try:
        age_h = (time.time() - chemin.stat().st_mtime) / HEURE_S
    except OSError:
        age_h = None
    appariement = charge.get("appariement") if isinstance(charge, dict) else None
    brut = appariement.get("jours_DENSES") if isinstance(appariement, dict) else None
    denses = brut if type(brut) is int and brut >= 0 else 0
    try:
        source = str(chemin.relative_to(racine))
    except ValueError:
        source = str(chemin)
    return denses, source, age_h
JOUR_MS = DS.JOUR_MS
HEURE_S = 3600.0

#: Au-dela de cet age, une mesure de debit ne decrit plus l'instant present : on la refuse
#: plutot que de l'extrapoler. Un ETA calcule sur un debit perime est un mensonge lent.
AGE_MAX_DEBIT_S = 300.0


def jours_denses(timestamps, *, seuil_par_jour: int = MIN_SIGNALS_PER_DAY) -> dict:
    """Journees UTC DENSES parmi des horodatages de signaux evaluables.

    Meme regle que le labo : une journee sous le seuil n'entre pas dans la base de la
    decoupe temporelle, donc elle ne compte pas pour la porte.
    """
    par_jour: dict[int, int] = {}
    for ts in timestamps or ():
        if type(ts) is int and ts > 0:
            par_jour[ts // JOUR_MS] = par_jour.get(ts // JOUR_MS, 0) + 1
    denses = sorted(j for j, n in par_jour.items() if n >= int(seuil_par_jour))
    return {
        "denses": denses,
        "nombre_denses": len(denses),
        "par_jour": par_jour,
        "seuil_par_jour": int(seuil_par_jour),
    }


def calculer_eta(
    *,
    denses_acquis: int,
    requis: int,
    signaux_aujourdhui: int,
    seuil_par_jour: int,
    debit_par_heure: float | None,
    aujourdhui_deja_dense: bool,
    secondes_restantes_dans_la_journee: float,
) -> dict:
    """L'ETA, en heures, ou un REFUS motive. Fonction PURE, donc testable.

    Le raisonnement, dans l'ordre :

    1. si les journees denses suffisent deja -> `ATTEINT` ;
    2. si le debit de signaux evaluables est nul ou inconnu -> `INFINI` / `INCONNU` ;
    3. sinon : il faut d'abord rendre la journee EN COURS dense (ce qui depend du debit),
       puis attendre une journee calendaire par journee manquante. Le plancher calendaire
       domine : aucun debit ne fait apparaitre deux journees UTC le meme jour.
    """
    manquantes = max(0, int(requis) - int(denses_acquis))
    if manquantes == 0:
        return {"statut": "ATTEINT", "heures": 0.0, "manquantes": 0,
                "motif": "les journees denses requises sont deja acquises"}
    if debit_par_heure is None:
        return {"statut": "INCONNU", "heures": None, "manquantes": manquantes,
                "motif": (
                    "débit de signaux évaluables non mesuré; le débit global des fichiers "
                    "ne permet pas de le déduire"
                )}
    if debit_par_heure <= 0:
        return {"statut": "INFINI", "heures": None, "manquantes": manquantes,
                "motif": "debit nul : la collecte est eteinte ou ne produit rien"}

    # Etape 1 : finir la journee en cours.
    if aujourdhui_deja_dense:
        heures_aujourdhui = 0.0
        jours_pleins = manquantes - 1
    else:
        restant = max(0, int(seuil_par_jour) - int(signaux_aujourdhui))
        heures_aujourdhui = restant / float(debit_par_heure)
        # Si le debit ne permet PAS d'atteindre le seuil avant minuit, la journee en cours
        # ne comptera pas : on la perd, et il faudra une journee de plus.
        if heures_aujourdhui * HEURE_S > max(0.0, secondes_restantes_dans_la_journee):
            heures_aujourdhui = max(0.0, secondes_restantes_dans_la_journee) / HEURE_S
            jours_pleins = manquantes
            statut = "JOURNEE_EN_COURS_PERDUE"
        else:
            jours_pleins = manquantes - 1
            statut = "EN_COURS"
    if aujourdhui_deja_dense:
        statut = "EN_COURS"

    heures = heures_aujourdhui + max(0, jours_pleins) * 24.0
    return {"statut": statut, "heures": round(heures, 2), "manquantes": manquantes,
            "heures_pour_finir_aujourdhui": round(heures_aujourdhui, 2),
            "journees_calendaires_ensuite": max(0, jours_pleins),
            "motif": None}


def duree_lisible(heures: float | None) -> str:
    """`None` -> `?`. Sinon `3 j 04 h 12 min`, pour un ETA qu'on lit d'un coup d'oeil."""
    if heures is None:
        return "?"
    total_min = int(round(heures * 60))
    jours, reste = divmod(total_min, 24 * 60)
    h, minutes = divmod(reste, 60)
    if jours:
        return f"{jours} j {h:02d} h {minutes:02d} min"
    if h:
        return f"{h} h {minutes:02d} min"
    return f"{minutes} min"


def duree_lisible_precise(secondes: float | int | None) -> str:
    """Formate une durée dynamique sans perdre les secondes.

    ``None`` et les valeurs non finies restent explicitement inconnues : l'ETA ne
    doit jamais transformer une absence de mesure en faux compte à rebours.
    """
    if secondes is None:
        return "INCONNU"
    try:
        valeur = float(secondes)
    except (TypeError, ValueError):
        return "INCONNU"
    if not math.isfinite(valeur):
        return "INCONNU"
    total = max(0, int(round(valeur)))
    jours, reste = divmod(total, 24 * 60 * 60)
    heures, reste = divmod(reste, 60 * 60)
    minutes, secondes_entieres = divmod(reste, 60)
    return f"{jours} j {heures:02d} h {minutes:02d} min {secondes_entieres:02d} s"


def pourcentage_progression(part: int | float | None, total: int | float | None) -> float | None:
    """Pourcentage mesuré, ou ``None`` quand le dénominateur n'est pas prouvé."""
    if part is None or total is None or float(total) <= 0:
        return None
    return round(max(0.0, min(100.0, float(part) * 100.0 / float(total))), 1)


def barre_progression(pourcent: float | None, *, largeur: int = 24) -> str:
    """Barre ASCII portable pour les consoles Windows et les sorties CI."""
    if pourcent is None:
        return "?" * max(1, int(largeur))
    remplie = round(max(0.0, min(100.0, pourcent)) * max(1, int(largeur)) / 100.0)
    return "#" * remplie + "." * (max(1, int(largeur)) - remplie)


def _eta_moteur_affiche(eta: dict, age_sonde_h: float | None) -> str:
    """N'affiche une durée que si le calcul possède une mesure admissible et fraîche."""
    if age_sonde_h is None:
        return "INCONNU — aucune sonde de densité"
    if age_sonde_h > AGE_MAX_SONDE_H:
        return f"INCONNU — sonde périmée depuis {age_sonde_h:.1f} h"
    statut = eta.get("statut")
    if statut == "ATTEINT":
        return "ATTEINT"
    if statut in {"EN_COURS", "JOURNEE_EN_COURS_PERDUE"} and isinstance(
        eta.get("heures"), (int, float)
    ):
        return duree_lisible(float(eta["heures"]))
    if statut == "INFINI":
        return "INFINI — débit causal nul"
    return "INCONNU — pas de débit de signaux évaluables"


def etat_flux(ruban: Path | None, mesure: dict, *, maintenant: float | None = None) -> dict:
    """État lisible du flux sans prétendre prouver l'état des processus.

    ``ACTIF`` signifie qu'une croissance a été mesurée entre deux rafraîchissements.
    Un fichier présent mais immobile devient ``EN_ATTENTE`` ou ``SANS_NOUVELLE`` : on
    ne le transforme jamais silencieusement en collecte arrêtée.
    """
    if ruban is None:
        return {"code": "INCONNU", "detail": "ruban absent", "age_s": None}
    try:
        age_s = max(0.0, (time.time() if maintenant is None else float(maintenant)) - ruban.stat().st_mtime)
    except OSError:
        return {"code": "INCONNU", "detail": "ruban illisible", "age_s": None}
    lignes_min = mesure.get("lignes_par_minute")
    if isinstance(lignes_min, (int, float)) and lignes_min > 0:
        return {"code": "ACTIF", "detail": "croissance mesurée", "age_s": round(age_s, 1)}
    if mesure.get("motif") == "PREMIERE_MESURE":
        return {"code": "EN_ATTENTE", "detail": "première mesure; attente du prochain rafraîchissement", "age_s": round(age_s, 1)}
    if age_s <= AGE_MAX_DEBIT_S:
        return {"code": "EN_ATTENTE", "detail": "aucune nouvelle ligne sur ce cycle", "age_s": round(age_s, 1)}
    return {"code": "SANS_NOUVELLE", "detail": "ruban présent mais inchangé", "age_s": round(age_s, 1)}


def progression_etude(besoins: list[dict]) -> dict:
    """Résumé du prochain stade chiffré, recalculé depuis l'instant présent."""
    candidats = [
        b for b in besoins
        if b.get("statut") == "MORE_DATA"
        and isinstance(b.get("mesures"), int)
        and isinstance(b.get("requis"), int)
        and b["requis"] > 0
    ]
    if not candidats:
        return {
            "pourcent": None,
            "texte": "INCONNU (aucune étude chiffrée en attente)",
            "eta_live": "INCONNU",
        }
    cible = min(candidats, key=lambda b: (b["restants"] if b.get("restants") is not None else 10**9, b["hypothese"]))
    pct = pourcentage_progression(cible["mesures"], cible["requis"])
    nom = str(cible["hypothese"]).replace("copy_vault_", "")
    restants = cible.get("restants")
    maintenant = datetime.now(timezone.utc)
    date_cible = cible.get("date_estimee")
    if isinstance(date_cible, datetime):
        if date_cible.tzinfo is None:
            date_cible = date_cible.replace(tzinfo=timezone.utc)
        eta_live_secondes = max(0.0, (date_cible - maintenant).total_seconds())
        eta_live = (
            f">= {duree_lisible_precise(eta_live_secondes)}, vers le "
            f"{date_cible.strftime('%d/%m %H:%M:%S')} UTC"
            if eta_live_secondes > 0
            else "À RÉÉVALUER (échéance dépassée)"
        )
    elif isinstance(restants, int):
        # Fallback uniquement pour les appels/tests qui fournissent un besoin sans date.
        date_cible = maintenant + timedelta(days=restants)
        eta_live_secondes = restants * 24 * 60 * 60
        eta_live = f">= {duree_lisible_precise(eta_live_secondes)}, vers le {date_cible.strftime('%d/%m %H:%M:%S')} UTC"
    else:
        eta_live = "INCONNU (besoin non chiffré)"
        eta_live_secondes = None
    return {
        "pourcent": pct,
        "texte": f"{cible['mesures']}/{cible['requis']} jours ({pct:.1f} %) — {nom}",
        "eta_live": eta_live,
        "eta_live_secondes": eta_live_secondes,
    }


def besoins_live(besoins: list[dict], maintenant: datetime | None = None) -> list[str]:
    """Construit une ligne temps réel pour chaque besoin connu du laboratoire.

    Le résumé ne choisit plus silencieusement un seul type de donnée : chaque étude
    apparaît avec son statut, son avancement et son ETA. Les besoins non chiffrés ou
    périmés restent lisibles comme tels.
    """
    maintenant = maintenant or datetime.now(timezone.utc)
    if not besoins:
        return ["| BESOINS LIVE         : INCONNU (aucune étude lue)"]
    lignes: list[str] = []
    for index, besoin in enumerate(besoins, start=1):
        nom = str(besoin.get("hypothese") or "hypothèse inconnue").replace("copy_vault_", "")
        genre = str(besoin.get("etude") or "base")
        identifiant = f"{nom} [{genre}]"
        statut = str(besoin.get("statut") or "INCONNU")
        mesures = besoin.get("mesures")
        requis = besoin.get("requis")
        restants = besoin.get("restants")
        if statut == "MORE_DATA" and isinstance(mesures, int) and isinstance(requis, int) and requis > 0:
            pct = pourcentage_progression(mesures, requis)
            if isinstance(restants, int) and restants >= 0:
                eta_secondes = restants * 24 * 60 * 60
                eta = duree_lisible_precise(eta_secondes)
                date_live = maintenant + timedelta(seconds=eta_secondes)
                detail = f"{mesures}/{requis} j ({pct:.1f} %) | reste >= {eta} | vers {date_live.strftime('%d/%m %H:%M:%S')} UTC"
            else:
                detail = f"{mesures}/{requis} j ({pct:.1f} %) | ETA INCONNU (besoin non chiffré)"
        elif statut == "MORE_DATA":
            detail = "MORE_DATA | avancement INCONNU | ETA INCONNU"
        else:
            detail = f"{statut} | ETA non applicable"
        lignes.append(f"| {index:02d}. {identifiant} : {detail}")
    return lignes


def lire_sources_alinasync(racine: Path) -> dict:
    """Lit les reçus locaux AlinaSync sans rescanner ni télécharger le corpus.

    Un fichier téléchargé n'est pas une donnée utilisable par le labo par sa seule
    présence. Cette vue ne compte donc que les compteurs inscrits dans les reçus
    SAFE/RESTORE cohérents et garde séparés : restauration, décompression et source
    GitHub. Elle est relue au rythme lent des études, pas à chaque rafraîchissement
    du débit, afin de ne pas relire un rapport de plusieurs dizaines de mégaoctets.
    """
    dossier = Path(racine) / "runtime" / "recovery" / "full"
    resultat: dict = {
        "restore_status": "INCONNU",
        "restore_issue": "REPORT_ABSENT",
        "safe_shards": None,
        "safe_bytes": None,
        "release_assets": None,
        "repository": None,
        "catalog_sha256": None,
        "current_catalog_sha256": None,
        "selection_scope": None,
        "families": [],
        "unpack_status": "INCONNU",
        "unpack_mode": "INCONNU",
        "unpack_certified": False,
        "unpack_physical_jsonl_available": False,
        "unpack_streamable_gzip_available": False,
        "unpack_read_mode": None,
        "certified_shards": None,
        "reported_certified_shards": None,
        "unpacked_shards": None,
        "reported_unpacked_shards": None,
        "unpack_issue": "REPORT_ABSENT",
        "sync_status": "INCONNU",
        "sync_report_status": None,
        "coffre_status": "INCONNU",
        "coffre_couverture_pct": None,
        "coffre_fichiers": None,
        "coffre_genere_ms": None,
    }

    def charger(nom: str) -> dict | None:
        chemin = dossier / nom
        try:
            if chemin.is_symlink() or not chemin.is_file():
                return None
            charge = json.loads(chemin.read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeDecodeError):
            return None
        return charge if isinstance(charge, dict) else None

    index_path = Path(racine) / "catalog" / "DATA_INDEX.json"
    try:
        if (
            not index_path.parent.is_symlink()
            and not index_path.is_symlink()
            and index_path.is_file()
        ):
            digest = hashlib.sha256()
            with index_path.open("rb") as handle:
                for block in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(block)
            resultat["current_catalog_sha256"] = digest.hexdigest()
    except OSError:
        resultat["current_catalog_sha256"] = None

    restore = charger("RESTORE_REPORT.json")
    if restore is not None:
        resultat["restore_status"] = str(restore.get("status") or "INCONNU")
        resultat["repository"] = restore.get("repository")
        resultat["selection_scope"] = restore.get("selection_scope")
        resultat["source_inventory_sha256"] = restore.get("source_inventory_sha256")
        classification = restore.get("classification")
        verification = restore.get("catalog_verification")
        if not isinstance(classification, dict) or not isinstance(verification, dict):
            resultat["restore_issue"] = "RESTORE_CONTRACT_INCONSISTENT"
        elif resultat["current_catalog_sha256"] is None:
            resultat["restore_issue"] = "CURRENT_CATALOG_UNAVAILABLE"
        elif verification.get("source_index_sha256") != resultat["current_catalog_sha256"]:
            resultat["restore_issue"] = "CATALOG_SHA_MISMATCH"
        else:
            expected_shards = classification.get("expected_usable_shards")
            shards = classification.get("usable_shards")
            expected_bytes = classification.get("expected_usable_bytes")
            octets = classification.get("usable_bytes")
            safe_catalog_shards = verification.get("safe_catalog_shards")
            inventory_sha = resultat["source_inventory_sha256"]
            inventory_valid = (
                isinstance(inventory_sha, str)
                and len(inventory_sha) == 64
                and all(char in "0123456789abcdef" for char in inventory_sha)
            )
            exact_parity = (
                type(expected_shards) is int and expected_shards >= 0
                and type(shards) is int and shards == expected_shards
                and type(expected_bytes) is int and expected_bytes >= 0
                and type(octets) is int and octets == expected_bytes
                and type(safe_catalog_shards) is int
                and safe_catalog_shards == expected_shards
                and classification.get("materialization_complete") is True
                and classification.get("failures") in ([], None)
            )
            restore_valid = (
                restore.get("status") == "REPLAY_READY_COMPLETE"
                and restore.get("repository") == REPOSITORY_CANONIQUE
                and inventory_valid
                and exact_parity
            )
            resultat["restore_issue"] = (
                None if restore_valid else "RESTORE_CONTRACT_INCONSISTENT"
            )
            if restore_valid:
                resultat["safe_shards"] = shards
                resultat["safe_bytes"] = octets
                assets = verification.get("required_release_assets")
                if type(assets) is int and assets >= 0:
                    resultat["release_assets"] = assets
                resultat["catalog_sha256"] = verification["source_index_sha256"]
                resultat["selection_scope"] = (
                    verification.get("selection_scope")
                    or resultat["selection_scope"]
                )
                families = verification.get("selection_families")
                if isinstance(families, list):
                    resultat["families"] = [str(f) for f in families if str(f).strip()]

    unpack = charger("UNPACK_REPORT.json")
    if unpack is not None:
        resultat["unpack_status"] = str(unpack.get("status") or "INCONNU")
        resultat["unpack_mode"] = str(unpack.get("mode") or "INCONNU")
        resultat["unpack_physical_jsonl_available"] = (
            unpack.get("physical_jsonl_available") is True
        )
        resultat["unpack_streamable_gzip_available"] = (
            unpack.get("streamable_gzip_available") is True
        )
        resultat["unpack_read_mode"] = unpack.get("replay_read_mode")
        unpack_sha = unpack.get("catalog_index_sha256")
        catalog_bound = (
            isinstance(resultat["catalog_sha256"], str)
            and unpack_sha == resultat["catalog_sha256"]
            and unpack_sha == resultat["current_catalog_sha256"]
            and resultat["restore_issue"] is None
        )
        physical = (
            unpack.get("status") == "SAFE_UNPACK_COMPLETE"
            and resultat["unpack_mode"] == "FULL_JSONL"
            and resultat["unpack_physical_jsonl_available"]
            and resultat["unpack_read_mode"] == "JSONL"
        )
        seal_only = (
            unpack.get("status") == "SAFE_SEAL_CERTIFICATION_COMPLETE"
            and resultat["unpack_mode"] == "SEAL_ONLY"
            and not resultat["unpack_physical_jsonl_available"]
            and resultat["unpack_streamable_gzip_available"]
            and resultat["unpack_read_mode"] == "GZIP_STREAM"
        )
        resultat["unpack_certified"] = catalog_bound and (physical or seal_only)
        resultat["unpack_verified"] = catalog_bound and physical
        if not catalog_bound:
            resultat["unpack_issue"] = (
                resultat["restore_issue"] or "CATALOG_SHA_MISMATCH"
            )
        elif not (physical or seal_only):
            resultat["unpack_issue"] = "UNPACK_CONTRACT_INCONSISTENT"
        else:
            resultat["unpack_issue"] = None

        certified = unpack.get("certified_shards")
        if type(certified) is int and certified >= 0:
            resultat["reported_certified_shards"] = certified
            if resultat["unpack_certified"]:
                resultat["certified_shards"] = certified
        unpacked = unpack.get("unpacked_shards")
        if type(unpacked) is int and unpacked >= 0:
            resultat["reported_unpacked_shards"] = unpacked
            if resultat["unpack_verified"]:
                resultat["unpacked_shards"] = unpacked

    sync = charger("SYNC_REPORT.json")
    if sync is not None:
        resultat["sync_status"] = str(sync.get("status") or "INCONNU")
        resultat["sync_report_status"] = sync.get("restore_report_status")

    couverture_path = Path(racine) / "runtime" / "coffre_certifie" / "COUVERTURE_PROJET.json"
    try:
        if not couverture_path.is_symlink() and couverture_path.is_file():
            couverture = json.loads(couverture_path.read_text(encoding="utf-8"))
            if isinstance(couverture, dict):
                pct = couverture.get("couverture_pct")
                fichiers = couverture.get("fichiers_de_donnees")
                genere_ms = couverture.get("genere_ms")
                if isinstance(pct, (int, float)) and math.isfinite(float(pct)):
                    resultat["coffre_couverture_pct"] = float(pct)
                if type(fichiers) is int and fichiers >= 0:
                    resultat["coffre_fichiers"] = fichiers
                if type(genere_ms) is int and genere_ms > 0:
                    resultat["coffre_genere_ms"] = genere_ms
                resultat["coffre_status"] = (
                    "CERTIFIÉ 100 %"
                    if couverture.get("cent_pour_cent") is True
                    else "PARTIEL / À COMPLÉTER"
                )
    except (OSError, ValueError, UnicodeDecodeError):
        resultat["coffre_status"] = "INCONNU"

    resultat["restore_verified"] = (
        resultat["restore_status"] == "REPLAY_READY_COMPLETE"
        and resultat["restore_issue"] is None
        and resultat["repository"] == REPOSITORY_CANONIQUE
        and isinstance(resultat["safe_shards"], int)
        and isinstance(resultat["safe_bytes"], int)
        and isinstance(resultat["catalog_sha256"], str)
        and resultat["catalog_sha256"] == resultat["current_catalog_sha256"]
    )
    resultat["github_release_bound"] = (
        resultat["restore_verified"]
        and isinstance(resultat["release_assets"], int)
        and isinstance(resultat["catalog_sha256"], str)
        and resultat["catalog_sha256"] == resultat["current_catalog_sha256"]
    )
    return resultat


def _octets_lisibles(octets: int | None) -> str:
    if not isinstance(octets, int) or octets < 0:
        return "INCONNU"
    valeur = float(octets)
    for unite in ("o", "Ko", "Mo", "Go", "To"):
        if valeur < 1024.0 or unite == "To":
            return f"{valeur:.1f} {unite}"
        valeur /= 1024.0
    return "INCONNU"


def _description_deballage(sources: dict) -> str:
    """Ne confond pas un certificat en flux avec des JSONL matérialisés."""
    if (
        sources.get("unpack_verified")
        and isinstance(sources.get("unpacked_shards"), int)
    ):
        return f"{sources['unpacked_shards']:,} JSONL déballés selon le reçu"
    if (
        sources.get("unpack_certified")
        and isinstance(sources.get("certified_shards"), int)
    ):
        return (
            f"{sources['certified_shards']:,} shards certifiés en flux "
            "(JSONL non décompressés; lecture GZIP)"
        )
    if sources.get("unpack_issue") == "CATALOG_SHA_MISMATCH":
        cause = "rapport de déballage lié à un autre catalogue"
    else:
        cause = "contrat du rapport incomplet ou incohérent"
    annonce = sources.get("reported_unpacked_shards")
    if isinstance(annonce, int):
        return (
            f"{annonce:,} annoncés par le reçu, non vérifiés et non comptés "
            f"({cause})"
        )
    if sources.get("unpack_issue") == "CATALOG_SHA_MISMATCH":
        return f"INCONNU ({cause})"
    return "INCONNU (preuve de déballage incomplète ou incohérente)"


def _description_deballage_courte(sources: dict) -> str:
    """Version opérateur compacte; les détails du reçu restent dans --detail."""
    if sources.get("unpack_verified") and isinstance(sources.get("unpacked_shards"), int):
        return f"{sources['unpacked_shards']:,} JSONL physiques selon le reçu"
    if sources.get("unpack_certified") and isinstance(sources.get("certified_shards"), int):
        return f"{sources['certified_shards']:,} vérifiés en flux; pas décompressés"
    annonce = sources.get("reported_unpacked_shards")
    if isinstance(annonce, int):
        return f"{annonce:,} annoncés; NON VÉRIFIÉS (reçu incomplet)"
    return "INCONNU (preuve incomplète)"


def _statut_deballage_affiche(sources: dict) -> str:
    """Affiche le contrat prouvé, pas le statut historique potentiellement trompeur."""
    if sources.get("unpack_verified"):
        return "JSONL PHYSIQUES VÉRIFIÉS"
    if sources.get("unpack_certified"):
        return "CERTIFIÉ EN FLUX GZIP"
    issue = sources.get("unpack_issue")
    if issue == "REPORT_ABSENT":
        return "REÇU ABSENT"
    if issue == "CATALOG_SHA_MISMATCH":
        return "REÇU D'UN AUTRE CATALOGUE"
    status = str(sources.get("unpack_status") or "INCONNU")
    if status == "INCONNU":
        return "INCONNU"
    return f"REÇU NON VÉRIFIÉ (déclaré {status})"


def lignes_sources_live(sources: dict | None) -> list[str]:
    """Explique ce qui vient des collecteurs et ce qui vient d'AlinaSync."""
    if not isinstance(sources, dict):
        return ["| SOURCES SAFE        : INCONNU (reçus AlinaSync non lus)"]
    restore = sources.get("restore_status", "INCONNU")
    safe = (
        f"{sources['safe_shards']:,} shards / {_octets_lisibles(sources['safe_bytes'])}"
        if sources.get("restore_verified") else "INCONNU (restauration non certifiée)"
    )
    unpack = _description_deballage(sources)
    unpack_status = _statut_deballage_affiche(sources)
    github = (
        f"preuve locale liée à {sources['repository']} / {sources['release_assets']:,} assets"
        if sources.get("github_release_bound") else "INCONNU (aucune preuve Release complète)"
    )
    familles = ", ".join(sources.get("families") or ()) or "INCONNU"
    coffre_pct = sources.get("coffre_couverture_pct")
    coffre = (
        f"{sources['coffre_status']} | couverture {coffre_pct:.3f} % | "
        f"{sources['coffre_fichiers']:,} fichiers"
        if isinstance(coffre_pct, (int, float)) and isinstance(sources.get("coffre_fichiers"), int)
        else sources.get("coffre_status", "INCONNU")
    )
    regle_comptage = (
        "le reçu SAFE déclare ces shards restaurés; ils ne deviennent des jours denses qu'après replay validé."
        if sources.get("restore_verified")
        else "aucun shard SAFE certifié par le reçu; aucune progression dense n'est ajoutée."
    )
    return [
        f"| ALINASYNC RESTORE   : {restore} | SAFE utilisable : {safe}",
        f"| ALINASYNC DÉBALLAGE : {unpack_status} | {unpack}",
        f"| ALINASYNC JOURNAL   : {sources.get('sync_status', 'INCONNU')}"
        f" (dernier journal, non prioritaire sur RESTORE_REPORT)",
        f"| GITHUB / RELEASE     : {github}",
        f"| FAMILLES SAFE LUES  : {familles}",
        f"| COFFRE CERTIFIÉ      : {coffre}",
        f"| RÈGLE DE COMPTAGE   : {regle_comptage}",
    ]


def lignes_dashboard_simple(
    *,
    tours: int,
    mesure: dict,
    etat: dict,
    denses_acquis: int,
    requis: int,
    age_sonde_h: float | None,
    eta: dict,
    besoins: list[dict],
    sources: dict | None,
    intervalle_s: float,
    suivi_collecteurs: dict | None = None,
    source_denses: str | None = None,
) -> list[str]:
    """Vue opérateur courte : une personne doit comprendre l'essentiel en 5 secondes."""
    etude = progression_etude(besoins)
    clair = {
        "ACTIF": (
            f"EN DIRECT — {mesure.get('active_sources', 0)}/"
            f"{mesure.get('source_count', 0)} fichiers de données grossissent "
            f"(pas {mesure.get('source_count', 0)} collecteurs)"
        ),
        "EN_ATTENTE": "EN ATTENTE — aucune nouvelle écriture mesurée sur ce cycle",
        "SANS_NOUVELLE": "SANS NOUVELLE — aucun fichier observé n'a grossi récemment",
        "INCONNU": "INCONNU — les fichiers ne sont pas vérifiables",
    }.get(etat.get("code"), "INCONNU — état non reconnu")
    debit = (
        f"{mesure['lignes_par_minute']:.1f} lignes/min"
        if mesure.get("lignes_par_minute") is not None
        else f"INCONNU ({mesure.get('motif') or 'première mesure'})"
    )
    moteur = _eta_moteur_affiche(eta, age_sonde_h)
    eta_secondes = etude.get("eta_live_secondes")
    if isinstance(eta_secondes, (int, float)) and eta_secondes > 0:
        prochaine = (
            f"collecter encore {duree_lisible_precise(eta_secondes)} — "
            f"{etude['texte'].split(' — ', 1)[0]}"
        )
    elif eta_secondes == 0:
        prochaine = "échéance dépassée — relancer l'étude pour recalculer"
    else:
        prochaine = "aucune étape chiffrée disponible"
    eta_etude = etude["eta_live"]
    raison_restore = {
        "CATALOG_SHA_MISMATCH": "reçu d'un ancien catalogue",
        "CURRENT_CATALOG_UNAVAILABLE": "catalogue local illisible",
        "RESTORE_CONTRACT_INCONSISTENT": "reçu incomplet ou incohérent",
    }.get(
        sources.get("restore_issue") if isinstance(sources, dict) else None,
        "restauration SAFE non certifiée",
    )
    if sources and sources.get("restore_verified"):
        safe = f"{sources['safe_shards']:,} shards / {_octets_lisibles(sources['safe_bytes'])}"
    else:
        safe = f"INCONNU — {raison_restore}"
    unpacked = (
        _description_deballage_courte(sources)
        if isinstance(sources, dict)
        else "INCONNU (reçu AlinaSync absent)"
    )
    release = (
        f"{sources['release_assets']:,} fichiers dans le reçu"
        if sources and sources.get("github_release_bound") and isinstance(sources.get("release_assets"), int)
        else "INCONNU"
    )
    coffre_pct = sources.get("coffre_couverture_pct") if sources else None
    coffre_genere_ms = sources.get("coffre_genere_ms") if sources else None
    if type(coffre_genere_ms) is int and coffre_genere_ms > 0:
        age_coffre_s = time.time() - coffre_genere_ms / 1000.0
        if age_coffre_s >= 0:
            age_coffre = f"MAJ {duree_lisible(age_coffre_s / 3600.0)}"
        elif age_coffre_s >= -300:
            age_coffre = "MAJ \u00e0 l'instant"
        else:
            age_coffre = "date future"
    else:
        age_coffre = "MAJ inconnue"
    if isinstance(coffre_pct, (int, float)):
        fichiers_coffre = sources.get("coffre_fichiers")
        fichiers_txt = (
            f" | {fichiers_coffre:,} fichiers"
            if type(fichiers_coffre) is int and fichiers_coffre >= 0
            else ""
        )
        coffre = (
            f"{coffre_pct:.3f} %{fichiers_txt} | "
            f"{sources.get('coffre_status', 'INCONNU')} | {age_coffre}"
        )
    else:
        coffre = f"INCONNU | {age_coffre}"
    sonde_age = "inconnue" if age_sonde_h is None else f"{age_sonde_h:.1f} h"
    sonde_source = Path(source_denses).name if source_denses else "INCONNUE"
    return [
        "+" + "=" * 76 + "+",
        f"| COPY-VAULT — SUIVI EN DIRECT | cycle {tours} | {time.strftime('%H:%M:%S')} |",
        "+" + "-" * 76 + "+",
        f"| ÉTAT              : {clair}",
        f"| DÉBIT FICHIERS    : {debit} (tous observés) | mise à jour {max(0.5, float(intervalle_s)):.1f} s",
        f"| PROCHAINE ÉTAPE   : {prochaine}",
        f"| TEMPS MINIMUM     : {eta_etude} (si chaque journée reste dense)",
        f"| ETA MOTEUR        : {moteur} | ancienne mesure: {denses_acquis}/{requis} jours",
        f"| SAFE RESTAURÉ     : {safe}",
        f"| EXTRACTION        : {unpacked}",
        f"| GITHUB            : {release}",
        f"| COFFRE            : {coffre}",
        *_lignes_suivi_collecteurs(suivi_collecteurs),
        f"| SONDE DENSITÉ    : âge {sonde_age} | rapport {sonde_source} | écran {max(0.5, float(intervalle_s)):.1f} s",
        "| AIDE              : un fichier téléchargé ne compte pas avant replay; q=quitter; --detail=diag",
        "+" + "=" * 76 + "+",
    ]


def lignes_resume(
    *,
    tours: int,
    ruban: Path | None,
    mesure: dict,
    etat: dict,
    denses_acquis: int,
    requis: int,
    age_sonde_h: float | None,
    eta: dict,
    besoins: list[dict],
    sources: dict | None = None,
    intervalle_s: float = 5.0,
    suivi_collecteurs: dict | None = None,
    source_denses: str | None = None,
) -> list[str]:
    """Bloc opérateur court placé avant le détail scientifique historique."""
    sonde_fiable = age_sonde_h is not None and age_sonde_h <= AGE_MAX_SONDE_H
    moteur_pct = pourcentage_progression(denses_acquis, requis) if sonde_fiable else None
    etude = progression_etude(besoins)
    etat_clair = {
        "ACTIF": (
            f"Collecte active : {mesure.get('active_sources', 0)}/"
            f"{mesure.get('source_count', 0)} fichiers ont grandi."
        ),
        "EN_ATTENTE": "En attente : pas encore assez de recul pour mesurer le débit.",
        "SANS_NOUVELLE": "Aucun fichier observé n'a grandi récemment ; cela ne prouve pas un arrêt.",
        "INCONNU": "État inconnu : le ruban n'est pas vérifiable.",
    }.get(etat["code"], "État non reconnu : aucune conclusion.")
    debit = (
        f"{mesure['lignes_par_minute']:.1f} lignes/min"
        if mesure.get("lignes_par_minute") is not None
        else f"INCONNU ({mesure.get('motif') or 'mesure en cours'})"
    )
    eta_txt = _eta_moteur_affiche(eta, age_sonde_h)
    sonde_txt = "inconnue" if age_sonde_h is None else f"{age_sonde_h:.1f} h"
    sonde_source = Path(source_denses).name if source_denses else "INCONNUE"
    progression_txt = (
        f"{moteur_pct:.1f} %"
        if moteur_pct is not None
        else f"INCONNUE (dernière valeur {denses_acquis}/{requis}, sonde périmée)"
    )
    return [
        "+" + "=" * 72 + "+",
        f"| ETA COLLECTE COPY-VAULT | {'EN DIRECT' if etat['code'] == 'ACTIF' else etat['code']:<10} | cycle {tours:<4} | {time.strftime('%H:%M:%S')} |",
        "+" + "-" * 72 + "+",
        f"| PROGRESSION MOTEUR  : [{barre_progression(moteur_pct)}] {progression_txt} ({denses_acquis}/{requis} dernières journées)",
        f"| EN CLAIR            : {etat_clair}",
        f"| PROCHAIN STADE      : {etude['texte']}",
        f"| ETA MINIMUM ACTUEL  : {etude['eta_live']} (si chaque journée reste dense)",
        *besoins_live(besoins),
        *lignes_sources_live(sources),
        f"| DÉBIT FICHIERS      : {debit} (tous les fichiers) | ETA moteur : {eta_txt}",
        f"| ACTIVITÉ FICHIERS   : {mesure.get('active_sources', 0)}/{mesure.get('source_count', 0)} actifs | "
        f"{mesure.get('recent_sources', 0)}/{mesure.get('source_count', 0)} récents",
        *_lignes_suivi_collecteurs(suivi_collecteurs),
        *_lignes_detail_suivi_collecteurs(suivi_collecteurs),
        f"| À SAVOIR            : {mesure.get('source_count', 0)} fichiers observés, pas {mesure.get('source_count', 0)} collecteurs",
        f"| ÉTAT DU RUBAN       : {etat['detail']} | dernière écriture : {etat.get('age_s', '?')} s",
        f"| SONDE DENSITÉ       : âge {sonde_txt} | rapport : {sonde_source} | écran {max(0.5, float(intervalle_s)):.1f} s",
        "+" + "=" * 72 + "+",
        "  Lecture seule : le résumé indique des observations, il ne démarre ni n'arrête rien.",
        "",
    ]


class MesureDeDebit:
    """Debit du ruban de fills, mesure sur sa CROISSANCE -- en temps constant.

    On ne relit pas 8 Go a chaque rafraichissement : on regarde de combien d'octets le
    fichier a grandi, et on convertit avec la taille moyenne d'une ligne, mesuree UNE fois
    sur la queue du fichier. Si cette moyenne est inconnue, le debit est `None` (inconnu)
    et jamais zero : un zero ferait croire a une collecte morte.
    """

    def __init__(self, chemin: Path, *, echantillon_octets: int = 262_144) -> None:
        self.chemin = Path(chemin)
        self.echantillon_octets = int(echantillon_octets)
        self.octets_par_ligne: float | None = None
        self._dernier: tuple[float, int] | None = None

    def _mesurer_la_ligne_moyenne(self) -> None:
        try:
            taille = self.chemin.stat().st_size
            with self.chemin.open("rb") as flux:
                if taille > self.echantillon_octets:
                    flux.seek(taille - self.echantillon_octets)
                    flux.readline()           # la premiere ligne lue est tronquee
                donnees = flux.read()
        except OSError:
            return
        lignes = donnees.count(b"\n")
        if lignes >= 10:
            self.octets_par_ligne = len(donnees) / lignes

    def lire(self) -> dict:
        """Mesure le débit sans relire le ruban.

        Le résumé opérateur réutilise aussi ``taille_octets`` et
        ``octets_par_minute`` pour montrer que l'écran observe bien une croissance
        réelle, pas seulement une horloge qui tourne.
        """
        if self.octets_par_ligne is None:
            self._mesurer_la_ligne_moyenne()
        try:
            taille = self.chemin.stat().st_size
        except OSError:
            self._dernier = None
            return {"debit_par_heure": None, "lignes_par_minute": None,
                    "octets_par_minute": None, "taille_octets": None, "age_s": None,
                    "motif": "RUBAN_ILLISIBLE"}
        # Une horloge murale peut avoir une résolution trop grossière sous Windows
        # et rendre deux lectures immédiates indistinguables. Pour un débit, seule
        # la durée écoulée compte : elle doit être monotone et haute résolution.
        maintenant = time.monotonic()
        if self._dernier is None:
            self._dernier = (maintenant, taille)
            return {"debit_par_heure": None, "lignes_par_minute": None,
                    "octets_par_minute": None, "taille_octets": taille, "age_s": 0.0,
                    "motif": "PREMIERE_MESURE"}
        t0, taille0 = self._dernier
        ecoule = maintenant - t0
        if ecoule <= 0:
            return {"debit_par_heure": None, "lignes_par_minute": None,
                    "octets_par_minute": None, "taille_octets": taille, "age_s": 0.0,
                    "motif": "INTERVALLE_NUL"}
        if ecoule > AGE_MAX_DEBIT_S:
            self._dernier = (maintenant, taille)
            return {"debit_par_heure": None, "lignes_par_minute": None,
                    "octets_par_minute": None, "taille_octets": taille,
                    "age_s": round(ecoule, 1), "motif": "MESURE_PERIMEE"}
        self._dernier = (maintenant, taille)
        if self.octets_par_ligne is None or self.octets_par_ligne <= 0:
            return {"debit_par_heure": None, "lignes_par_minute": None,
                    "octets_par_minute": None, "taille_octets": taille,
                    "age_s": round(ecoule, 1), "motif": "LIGNE_MOYENNE_INCONNUE"}
        lignes = max(0, taille - taille0) / self.octets_par_ligne
        par_minute = lignes / (ecoule / 60.0)
        octets_par_minute = max(0, taille - taille0) / (ecoule / 60.0)
        return {"debit_par_heure": par_minute * 60.0, "lignes_par_minute": par_minute,
                "octets_par_minute": octets_par_minute, "taille_octets": taille,
                "age_s": round(ecoule, 1), "motif": None}


FLUX_DATA_EXTENSIONS = (".jsonl", ".ndjson", ".csv", ".json")
FLUX_DATA_SUFFIXES_IGNORES = (".lock", ".part", ".partial", ".idx.json")


def trouver_flux_de_donnees(racine: Path) -> list[Path]:
    """Découvre les flux locaux sans ouvrir ni modifier leurs données.

    Les collecteurs écrivent plusieurs rubans en parallèle. L'ancien ETA choisissait
    ``vault_fills_poll`` puis pouvait afficher 0 alors que L2, trades ou checkpoints
    avançaient. On observe tous les fichiers de données directement sous
    ``runtime/data`` et les rubans live connus, sans compter les archives SAFE ni les
    rapports du labo comme du débit de collecte.
    """
    vus: dict[str, Path] = {}
    dossier = Path(racine) / "runtime" / "data"
    try:
        candidats = list(dossier.iterdir()) if dossier.is_dir() else []
    except OSError:
        candidats = []
    for chemin in candidats:
        try:
            if not chemin.is_file() or chemin.is_symlink():
                continue
            nom = chemin.name.lower()
            if nom.endswith(FLUX_DATA_SUFFIXES_IGNORES):
                continue
            if chemin.suffix.lower() not in FLUX_DATA_EXTENSIONS:
                continue
            vus[str(chemin.resolve()).lower()] = chemin
        except OSError:
            continue
    for relatif in RUBANS_FILLS:
        chemin = Path(racine) / relatif
        try:
            if chemin.is_file() and not chemin.is_symlink():
                vus[str(chemin.resolve()).lower()] = chemin
        except OSError:
            continue
    return sorted(vus.values(), key=lambda chemin: str(chemin).lower())


def etat_flux_global(mesure: dict, *, maintenant: float | None = None) -> dict:
    """Résume l'activité de tous les rubans sans déduire un état de processus."""
    total = int(mesure.get("source_count") or 0)
    actifs = int(mesure.get("active_sources") or 0)
    recents = int(mesure.get("recent_sources") or 0)
    if total == 0:
        return {"code": "INCONNU", "detail": "aucun flux de données trouvé", "age_s": None}
    if actifs:
        return {
            "code": "ACTIF",
            "detail": f"{actifs}/{total} fichiers de données en croissance; {recents}/{total} modifiés récemment",
            "age_s": mesure.get("age_s"),
        }
    if recents:
        return {
            "code": "EN_ATTENTE",
            "detail": f"{recents}/{total} fichiers récents, aucune croissance mesurée sur ce cycle",
            "age_s": mesure.get("age_s"),
        }
    return {
        "code": "SANS_NOUVELLE",
        "detail": f"aucune croissance récente sur {total} fichiers de données observés",
        "age_s": mesure.get("age_s"),
    }


class MesureMultiFlux:
    """Mesure le débit opérationnel de tous les rubans locaux en parallèle."""

    def __init__(self, racine: Path) -> None:
        self.racine = Path(racine)
        self._mesures: dict[Path, MesureDeDebit] = {}

    def lire(self) -> dict:
        chemins = trouver_flux_de_donnees(self.racine)
        lignes_total = 0.0
        octets_total = 0.0
        actifs: list[Path] = []
        actifs_detail: list[tuple[Path, float]] = []
        recents = 0
        ages: list[float] = []
        mesures: list[tuple[Path, dict]] = []
        for chemin in chemins:
            mesure = self._mesures.setdefault(chemin, MesureDeDebit(chemin)).lire()
            mesures.append((chemin, mesure))
            lignes = mesure.get("lignes_par_minute")
            octets = mesure.get("octets_par_minute")
            if isinstance(lignes, (int, float)) and lignes > 0:
                lignes_total += float(lignes)
            if isinstance(octets, (int, float)) and octets > 0:
                octets_total += float(octets)
            croissance = (
                (isinstance(lignes, (int, float)) and lignes > 0)
                or (isinstance(octets, (int, float)) and octets > 0)
            )
            if croissance:
                actifs.append(chemin)
                actifs_detail.append((chemin, float(octets or 0.0)))
            try:
                age = max(0.0, time.time() - chemin.stat().st_mtime)
            except OSError:
                continue
            ages.append(age)
            if age <= AGE_MAX_DEBIT_S:
                recents += 1
        actifs_detail.sort(key=lambda item: item[1], reverse=True)
        principaux = [str(path.relative_to(self.racine)).replace(chr(92), "/") for path, _ in actifs_detail[:8]]
        derniere = min(ages) if ages else None
        premiere_mesure = bool(mesures) and all(
            mesure.get("motif") == "PREMIERE_MESURE" for _, mesure in mesures
        )
        motif = None
        if not chemins:
            motif = "AUCUN_FLUX"
        elif not actifs:
            motif = "AUCUNE_CROISSANCE"
        elif all(m.get("motif") == "PREMIERE_MESURE" for _, m in mesures):
            motif = "PREMIERE_MESURE"
        return {
            "debit_par_heure": None if premiere_mesure else (lignes_total * 60.0 if lignes_total > 0 else 0.0),
            "lignes_par_minute": None if premiere_mesure else lignes_total,
            "octets_par_minute": None if premiere_mesure else (octets_total if octets_total > 0 else 0.0),
            "taille_octets": sum(int(m.get("taille_octets") or 0) for _, m in mesures),
            "age_s": round(derniere, 1) if derniere is not None else None,
            "motif": "PREMIERE_MESURE" if premiere_mesure else motif,
            "source_count": len(chemins),
            "active_sources": len(actifs),
            "recent_sources": recents,
            "active_source_paths": principaux,
        }


#: Au-delà, la sonde des journées denses ne décrit plus le corpus : on l'affiche PÉRIMÉE au lieu de la croire.
AGE_MAX_SONDE_H = 24.0
ETUDES = Path("runtime") / "reports" / "copy_vault_quant_lab" / "copiabilite"


def _date_du_passage(nom: str) -> datetime | None:
    try:
        return datetime.strptime(nom[:15], "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def besoins_du_labo(racine: Path) -> list[dict]:
    """Ce que les ÉTUDES du labo disent leur manquer, hypothèse par hypothèse (le passage le plus récent fait foi).

    24/11/2026 -- POURQUOI. L'ETA affichait « 0 min, ATTEINT (7/6 journées) » pendant que le labo répondait
    « MORE_DATA : 8 jours hors échantillon, il en faut 20 ». Le seuil de 6 journées est le plancher de découpage du
    moteur, pas le besoin des études. Ici, les jours MESURÉS et REQUIS sont lus dans ``resultat.json`` de chaque
    étude ; rien n'est supposé : une hypothèse dont le besoin n'est pas chiffré en jours le dit.
    """
    import re

    dernier: dict[str, dict] = {}
    dossier = Path(racine) / ETUDES
    for resultat in sorted(dossier.glob("*/resultat.json")) if dossier.is_dir() else ():
        quand = _date_du_passage(resultat.parent.name)
        if quand is None:
            continue
        try:
            verdicts = (json.loads(resultat.read_text(encoding="utf-8")).get("report") or {}).get("verdicts")
        except (OSError, ValueError, AttributeError):
            continue
        for v in verdicts if isinstance(verdicts, list) else ():
            if not isinstance(v, dict) or not v.get("hypothesis"):
                continue
            raison = str(v.get("reason") or "")
            m = re.search(r"(\d+)\s+jour", raison)
            requis = v.get("required_independent_days")
            if type(requis) is not int:
                r = re.search(r"<\s*(\d+)\s+requis", raison) or re.search(r"au moins\s+(\d+)", raison)
                requis = int(r.group(1)) if r else None
            mesures = int(m.group(1)) if m else None
            restants = max(0, requis - mesures) if requis is not None and mesures is not None else None
            # une même hypothèse est mesurée par PLUSIEURS études (base, positions, rétrospectif) : chacune garde sa
            # ligne, sinon la dernière lue efface les jours mesurés par les autres
            genre = resultat.parent.name.split("Z-", 1)[1] if "Z-" in resultat.parent.name else "base"
            dernier[f"{v['hypothesis']}|{genre}"] = {
                "hypothese": v["hypothesis"], "etude": genre, "statut": str(v.get("status") or "?"), "mesures": mesures,
                "requis": requis, "restants": restants, "passage": resultat.parent.name, "date": quand,
                "date_estimee": (quand + timedelta(days=restants)) if restants is not None else None,
                "raison": raison,
            }
    return sorted(dernier.values(), key=lambda b: (b["restants"] is None, b["restants"] or 0, b["hypothese"]))


def echeance_passee(b: dict, maintenant: datetime | None = None) -> bool:
    """La date estimée est déjà derrière nous : l'étude n'a pas été relancée, son compte de jours est périmé."""
    maintenant = maintenant or datetime.now(timezone.utc)
    return b.get("date_estimee") is not None and b["date_estimee"] < maintenant


def lignes_besoins(besoins: list[dict], maintenant: datetime | None = None) -> list[str]:
    if not besoins:
        return ["  aucune etude du labo lue (" + str(ETUDES) + ") : besoin INCONNU, jamais suppose atteint"]
    lignes = []
    for b in besoins:
        nom = b["hypothese"].replace("copy_vault_", "") + ("" if b.get("etude", "base") == "base" else f" [{b['etude']}]")
        quand = b["date"].strftime("%d/%m")
        if b["statut"] != "MORE_DATA":
            lignes.append(f"  {nom:<44} tranchee : {b['statut']}  (etude du {quand})")
        elif b["restants"] is None:
            lignes.append(f"  {nom:<44} besoin non chiffre en jours  (etude du {quand})")
        elif echeance_passee(b, maintenant):
            lignes.append(f"  {nom:<44} {b['mesures']:>3} / {b['requis']:<3} jours au {quand} -> echeance "
                          f"{b['date_estimee'].strftime('%d/%m')} PASSEE : relancer l'etude pour recompter")
        else:
            lignes.append(f"  {nom:<44} {b['mesures']:>3} / {b['requis']:<3} jours -> encore {b['restants']:>3} j"
                          f"  vers le {b['date_estimee'].strftime('%d/%m')}  (etude du {quand})")
    return lignes


def _quitter_demande(secondes: float) -> bool:
    """Attend ``secondes`` ; vrai si « q » a été tapé (console Windows). Le texte annonçait « q pour quitter »
    sans jamais lire le clavier : seul Ctrl+C marchait."""
    fin = time.monotonic() + secondes
    try:
        import msvcrt
        console = bool(sys.stdin) and sys.stdin.isatty()
    except (ImportError, ValueError, AttributeError):
        console = False
    if not console:                                   # pas de clavier (sortie redirigée, tests) : simple attente
        time.sleep(secondes)
        return False
    while time.monotonic() < fin:
        try:
            if msvcrt.kbhit() and msvcrt.getwch().lower() == "q":
                return True
        except OSError:
            pass
        time.sleep(0.1)
    return False


def _secondes_restantes_aujourdhui(maintenant_ms: int | None = None) -> float:
    ms = int(time.time() * 1000) if maintenant_ms is None else int(maintenant_ms)
    return max(0.0, (JOUR_MS - (ms % JOUR_MS)) / 1000.0)


def _charger_etat_de_fond(chemin: Path) -> dict | None:
    try:
        charge = json.loads(Path(chemin).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return charge if isinstance(charge, dict) else None


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--racine", default=".")
    p.add_argument("--intervalle", type=float, default=2.0,
                   help="secondes entre deux rafraichissements de l'ETA")
    p.add_argument("--tours", type=int, default=0,
                   help="nombre de rafraichissements (0 = sans fin, q pour quitter)")
    p.add_argument("--sonde", default=None,
                   help="rapport horloges explicite ; par défaut le plus récent est relu")
    p.add_argument("--requis", type=int, default=DS.MINIMUM_SIGNAL_UTC_DAYS)
    p.add_argument("--une-fois", action="store_true", help="une seule mesure, puis sortie")
    p.add_argument(
        "--detail",
        action="store_true",
        help="affiche le diagnostic complet ; par défaut, l'écran reste volontairement synthétique",
    )
    args = p.parse_args(argv)

    racine = Path(args.racine).resolve()
    flux = sys.stdout
    try:  # noqa: SIM105
        flux.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

    ruban, cherches = trouver_ruban(racine)
    debit = MesureMultiFlux(racine)
    tours = 0
    besoins: list[dict] = []
    sources: dict | None = None
    while True:
        tours += 1
        if tours == 1 or tours % 12 == 0:              # études et reçus lourds : relus ~1 fois par minute
            besoins = besoins_du_labo(racine)
            sources = lire_sources_alinasync(racine)
        denses_acquis, source_denses, age_sonde_h = lire_sonde_denses(racine, args.sonde)
        mesure = debit.lire()
        suivi_collecteurs = lire_suivi_collecteurs(racine)
        secondes_restantes = _secondes_restantes_aujourdhui()
        eta = calculer_eta(
            denses_acquis=denses_acquis, requis=int(args.requis),
            signaux_aujourdhui=0, seuil_par_jour=MIN_SIGNALS_PER_DAY,
            # ``MesureMultiFlux`` mesure la croissance cumulée des fichiers
            # (fills, L2, chandelles, snapshots, etc.), pas des signaux causaux
            # exécutables. Ne jamais convertir ce débit général en ETA de densité.
            debit_par_heure=None,
            aujourdhui_deja_dense=False,
            secondes_restantes_dans_la_journee=secondes_restantes)
        etat = etat_flux_global(mesure)
        eta_detail = eta if age_sonde_h is not None and age_sonde_h <= AGE_MAX_SONDE_H else {
            **eta,
            "statut": "INCONNU",
            "heures": None,
            "motif": "sonde de densité périmée",
        }

        if args.detail or args.une_fois:
            en_attente = [b for b in besoins if b["statut"] == "MORE_DATA" and b["restants"] is not None
                          and not echeance_passee(b)]
            if en_attente:
                prochaine, derniere = en_attente[0], max(en_attente, key=lambda b: b["restants"])
                tete = [
                    f"  ETA LABO (etudes)            : prochaine hypothese tranchable vers le "
                    f"{prochaine['date_estimee'].strftime('%d/%m')} ({prochaine['hypothese'].replace('copy_vault_', '')}),",
                    f"                                 toutes vers le {derniere['date_estimee'].strftime('%d/%m')}"
                    f" -- si chaque journee reste dense",
                ]
            elif besoins:
                tete = ["  ETA LABO (etudes)            : aucune hypothese chiffree en jours n'attend de donnees"]
            else:
                tete = ["  ETA LABO (etudes)            : INCONNU (aucune etude lue)"]
            lignes = lignes_resume(
                tours=tours,
                ruban=ruban,
                mesure=mesure,
                etat=etat,
                denses_acquis=denses_acquis,
                requis=int(args.requis),
                age_sonde_h=age_sonde_h,
                eta=eta,
                besoins=besoins,
                sources=sources,
                intervalle_s=args.intervalle,
                suivi_collecteurs=suivi_collecteurs,
                source_denses=source_denses,
            ) + [
                "=" * 68,
                "  DETAIL ETA DONNEES LABO — pourquoi cette estimation ?",
                "=" * 68,
                *tete,
                "",
                "  CE QUE LES ETUDES DU LABO DISENT LEUR MANQUER (passage le plus recent) :",
                *lignes_besoins(besoins),
                "",
                "  PLANCHER DU MOTEUR (decoupage TRAIN/TEST, pas le besoin des etudes) :",
                f"  journees UTC DENSES acquises : {denses_acquis} / {args.requis} requises",
                f"  seuil de densite             : {MIN_SIGNALS_PER_DAY} signaux evaluables/jour",
                f"  source des journees          : {source_denses}",
                ("  age de cette mesure          : "
                 + (f"{age_sonde_h:.1f} h" if age_sonde_h is not None else "INCONNU")
                 + ("  -- PERIMEE (tools/sonde_horloges_carnets.py la refait)"
                    if age_sonde_h is not None and age_sonde_h > AGE_MAX_SONDE_H else "")),
                "  ATTENTION                    : borne HAUTE — la sonde lit les rubans par",
                "                                 regex, hors des filtres du labo (dedup,",
                "                                 certification, une_seule_connexion_par_coin).",
                ("  ruban de debit               : "
                 + (str(ruban.relative_to(racine)) if ruban
                    else "INTROUVABLE parmi " + ", ".join(cherches))),
                "",
                ("  debit observe                : "
                 + (f"{mesure['lignes_par_minute']:.1f} lignes/min"
                    if mesure["lignes_par_minute"] is not None
                    else f"INCONNU ({mesure['motif']})")),
                f"  mesure sur                   : {mesure['age_s']} s",
                "",
                f"  plancher du moteur           : {duree_lisible(eta_detail['heures'])}"
                f"   [{eta_detail['statut']}]",
            ]
            if eta_detail.get("motif"):
                lignes.append(f"  pourquoi                     : {eta_detail['motif']}")
            if eta_detail["statut"] in ("EN_COURS", "JOURNEE_EN_COURS_PERDUE"):
                lignes.append(
                    f"  dont aujourd'hui             : "
                    f"{duree_lisible(eta_detail.get('heures_pour_finir_aujourdhui'))}"
                    f"  puis {eta_detail.get('journees_calendaires_ensuite')} journee(s) calendaire(s)")
            lignes.append("")
            lignes.append("  (l'ETA RECULE si le debit tombe : une journee trop pauvre ne compte pas)")
            lignes.append("  (dates des etudes : jours REQUIS moins jours MESURES a la date de l'etude ; relancer")
            lignes.append("   LANCER_LAB_QUANT_COPY_VAULT.cmd copiabilite pour les remettre a jour)")
            if not args.une_fois:
                lignes.append("  q ou Ctrl+C pour quitter")
        else:
            lignes = lignes_dashboard_simple(
                tours=tours,
                mesure=mesure,
                etat=etat,
                denses_acquis=denses_acquis,
                requis=int(args.requis),
                age_sonde_h=age_sonde_h,
                eta=eta_detail,
                besoins=besoins,
                sources=sources,
                intervalle_s=args.intervalle,
                suivi_collecteurs=suivi_collecteurs,
                source_denses=source_denses,
            )
        if os.name == "nt" and getattr(sys.stdout, "isatty", lambda: False)():
            os.system("cls")      # noqa: S605 S607 - rafraichissement d'ecran, pas d'entree externe
        print("\n".join(lignes), flush=True)

        if args.une_fois or (args.tours and tours >= args.tours):
            return 0
        if _quitter_demande(max(0.5, float(args.intervalle))):
            return 0


if __name__ == "__main__":
    raise SystemExit(main())
