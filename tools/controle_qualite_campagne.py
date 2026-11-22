#!/usr/bin/env python3
"""Contrôle de qualité d'une campagne de collecte — il SIGNALE, il ne rassure pas.

POURQUOI. Une campagne de six jours peut se dégrader en silence : un collecteur qui meurt, un
marché qui n'arrive plus, une certification qui s'arrête, un disque qui se remplit. Rien n'explose,
et on ne s'en aperçoit qu'à la fin — six jours perdus.

RÈGLE DE CONCEPTION : **un contrôle qui affiche « OK » sans rien avoir mesuré est pire que pas de
contrôle**, parce qu'il endort. Ici, chaque ligne dit CE QUI A ÉTÉ MESURÉ et sur quelle preuve ;
quand une mesure est impossible, c'est dit, et c'est compté comme une anomalie, jamais comme un
succès (deny-by-default, comme la porte de promotion du labo).

CE QUI EST VÉRIFIÉ
1. Fraîcheur du journal de CHAQUE collecteur attendu, comparée à SA cadence (pas un seuil unique).
2. Les rubans vitaux grossissent-ils encore (fills des leaders, carnets L2) ?
3. La certification a-t-elle tourné récemment, et le coffre grossit-il ?
4. Espace disque, avec projection sur la fin de campagne.

PAPER / lecture seule : aucune requête réseau, aucun ordre, aucune écriture hors de son journal.

Code de sortie : 0 si aucune anomalie, 1 s'il y en a (exploitable par un superviseur).
"""
from __future__ import annotations

import argparse
import contextlib
import importlib.util
import json
import shutil
import sys
import time
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))
sys.path.insert(0, str(RACINE / "src"))
sys.path.insert(0, str(RACINE / "tools"))

#: Un journal est « frais » jusqu'à FACTEUR x sa cadence (jamais moins que le plancher).
FACTEUR_FRAICHEUR = 4.0
PLANCHER_FRAICHEUR_S = 600.0
#: En dessous : on alerte sur le disque.
DISQUE_MINIMAL_GO = 60.0
#: Rubans dont l'arrêt condamne la campagne (ce sont EUX que le labo lit).
RUBANS_VITAUX = ("vault_fills_live.jsonl", "copy_vault_l2_tape.jsonl")
#: La certification tourne toutes les 30 min ; au-delà de 3 cadences, elle est en panne.
CERTIFICATION_MAX_S = 5400.0


def _collecteurs_attendus() -> list[tuple[str, float, str]]:
    """(nom, cadence, script) pour chaque collecteur que la campagne est censée lancer."""
    spec = importlib.util.spec_from_file_location(
        "watch_eco", RACINE / "tools" / "watch_economic_collectors.py")
    watch = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(watch)
    from hl_observer.ops import collecteur_registry as registre

    # 16/11/2026 — MEME PIEGE QUE LE TEST DU LANCEUR, ET ICI IL PRODUISAIT UN FAUX « MORT ».
    # `copy-vault-checkpoints` vit dans COLLECTEURS_CAMPAGNE, pas dans REGISTRE. Avec REGISTRE
    # seul, son `script` valait "" : aucun processus ne pouvait correspondre, et le controle
    # declarait MORT le compagnon qui ecrivait a la seconde meme. La resolution reelle du lanceur
    # (`bounded_collection._registry`) lit REGISTRE + COLLECTEURS_CAMPAGNE : on lit la MEME chose.
    par_nom = {c["nom"]: c for c in (*registre.REGISTRE, *registre.COLLECTEURS_CAMPAGNE)}
    sortie = []
    for nom in watch.DEFAULT_NAMES:
        config = par_nom.get(nom) or {}
        sortie.append((nom, float(config.get("intervalle_s") or 0.0),
                       str(config.get("script") or "")))
    return sortie


def _scripts_vivants() -> set[str] | None:
    """Noms de scripts collecteurs actuellement en execution, ou None si on ne peut pas savoir.

    DISTINCTION VITALE. « Journal fige » tout seul ne dit pas ce qui se passe :
    * processus VIVANT  -> sortie bufferisee ou traitement long : genant, pas fatal ;
    * processus ABSENT  -> le collecteur est MORT : la campagne perd ce flux.
    Confondre les deux, c'est soit crier au loup (et se faire ignorer), soit dormir sur un flux
    mort. On ne DEVINE pas : si psutil manque, on rend None et le controle le dit.
    """
    try:
        import psutil
    except ImportError:
        return None
    vivants: set[str] = set()
    for proc in psutil.process_iter(["cmdline"]):
        try:
            morceaux = proc.info.get("cmdline") or []
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        for morceau in morceaux:
            texte = str(morceau)
            if "collecter_" in texte or "sceller_coffre_local" in texte:
                vivants.add(Path(texte).name)
    return vivants


def _rubans_par_script() -> dict[str, list[tuple[str, str]]]:
    """``script producteur -> [(dossier, fichier)]``, lu de la declaration du depot.

    On ne devine pas quel collecteur ecrit quoi : `couverture_donnees.FLUX` le declare deja, et
    c'est la meme source que la matrice de couverture. Si un flux change de producteur, ce
    controle suit automatiquement.
    """
    try:
        from hl_observer.datasets.couverture_donnees import FLUX
    except Exception:                      # noqa: BLE001 — un controle ne doit jamais planter
        return {}
    par_script: dict[str, list[tuple[str, str]]] = {}
    for flux in FLUX:
        producteur = Path(str(getattr(flux, "producteur", ""))).name
        fichier = str(getattr(flux, "fichier", ""))
        dossier = str(getattr(flux, "dossier", ""))
        if producteur and fichier and "*" not in fichier:
            par_script.setdefault(producteur, []).append((dossier, fichier))
    return par_script


def _age_des_rubans_produits(root: Path, script: str, maintenant: float) -> float | None:
    """Age du ruban le PLUS FRAIS que ce script est declare produire, ou ``None``."""
    nom = Path(str(script)).name
    if not nom:
        return None
    ages: list[float] = []
    for dossier, fichier in _rubans_par_script().get(nom, ()):
        for base in (root / dossier, root / "runtime" / "data", root / "runtime" / dossier):
            age = _age_s(base / fichier, maintenant)
            if age is not None:
                ages.append(age)
                break
    return min(ages) if ages else None


def _age_s(chemin: Path, maintenant: float) -> float | None:
    try:
        return maintenant - chemin.stat().st_mtime
    except OSError:
        return None


GRACE_DEMARRAGE_S = 600.0


def age_de_la_campagne_s(root: Path, maintenant: float) -> float | None:
    """Secondes ecoulees depuis l'emission du bail de la campagne en cours. Inconnu -> None."""
    # Le BAIL d'abord : il est ecrit AVANT le lancement des collecteurs. Le fichier d'etat, lui, n'est
    # ecrit qu'a la FIN du demarrage -- mesure reelle du 22/11/2026, 17:37 : ce controle a tourne
    # pendant que l'etat portait encore l'heure de la campagne precedente (4,7 h plus tot), donc sans
    # aucune grace, et il a de nouveau crie « ABSENT » au demarrage.
    donnees = root / "runtime" / "data"
    for fichier, chemin in (("economic_collection_lease.json", ("issued_at_ms",)),
                            ("economic_collection_pids.json", ("lease", "issued_at_ms"))):
        try:
            valeur = json.loads((donnees / fichier).read_text(encoding="utf-8"))
            for clef in chemin:
                valeur = valeur[clef]
            emis = float(valeur) / 1000.0
        except (OSError, ValueError, KeyError, TypeError):
            continue
        return maintenant - emis if maintenant >= emis else None
    return None


def controler(root: Path, *, maintenant: float | None = None) -> dict:
    maintenant = time.time() if maintenant is None else maintenant
    anomalies: list[str] = []
    mesures: list[str] = []
    # DELAI DE GRACE (22/11/2026) : lance a t+0, ce controle jugeait « ABSENT » des rubans que les
    # collecteurs n'avaient pas encore eu le temps de creer, et sortait en erreur a CHAQUE demarrage.
    # Une alerte qui sonne toujours n'est plus lue. Pendant les 10 premieres minutes d'une campagne
    # dont on CONNAIT l'heure de depart, l'absence de donnees est un etat normal, dit comme tel.
    # Heure de depart inconnue -> aucune grace (on juge comme avant).
    age_campagne = age_de_la_campagne_s(root, maintenant)
    en_demarrage = age_campagne is not None and age_campagne < GRACE_DEMARRAGE_S
    if en_demarrage:
        mesures.append(f"campagne demarree il y a {age_campagne:.0f} s : fraicheur des journaux et des "
                       f"rubans non jugee avant {GRACE_DEMARRAGE_S:.0f} s")

    # 1) fraîcheur par collecteur, comparée à SA cadence
    frais = figes = sans_journal = morts = 0
    vivants = _scripts_vivants()
    if vivants is None:
        mesures.append("liveness des processus : NON MESURABLE (psutil absent) — "
                       "un journal fige ne pourra pas etre distingue d'un collecteur mort")
    for nom, cadence, script in _collecteurs_attendus():
        journal = root / "runtime" / "logs" / f"economic-{nom}.log"
        age = _age_s(journal, maintenant)
        seuil = max(PLANCHER_FRAICHEUR_S, cadence * FACTEUR_FRAICHEUR)
        # Le BATTEMENT CANONIQUE prime sur le mtime du journal. Un journal n'est ecrit que sur
        # evenement : six collecteurs etaient annonces « figes depuis 1320 min » alors que leur
        # battement datait de la seconde. Le battement, lui, est ecrit pour dire « je vis ».
        age_battement = _age_s(
            root / "runtime" / "research_lab" / "heartbeats" / f"{nom}.json", maintenant)
        if age_battement is not None and age_battement <= seuil:
            frais += 1
            continue
        # Pas de battement canonique ? Alors on regarde ce que le collecteur PRODUIT. Le depot
        # declare deja quel script ecrit quel ruban (`couverture_donnees.FLUX`). Mesure du 16/11 :
        # `userfills-poll` etait annonce « fige depuis 5 588 min » alors que son ruban faisait
        # 1 051,8 Mo et venait d'etre ecrit a la seconde. Un journal n'est pas une preuve de vie ;
        # une donnee fraiche, si.
        age_ruban = _age_des_rubans_produits(root, script, maintenant)
        if age_ruban is not None and age_ruban <= seuil:
            frais += 1
            continue
        if en_demarrage:
            continue
        if age is None:
            sans_journal += 1
            anomalies.append(f"collecteur {nom} : AUCUN JOURNAL (jamais lance ?)")
        elif age > seuil:
            vivant = None if vivants is None else (Path(script).name in vivants)
            if vivant is False:
                morts += 1
                anomalies.append(f"collecteur {nom} : MORT — journal fige depuis {age / 60:.0f} min "
                                 f"ET aucun processus. Ce flux est PERDU tant qu'il ne repart pas.")
            else:
                figes += 1
                detail = "processus vivant" if vivant else "liveness inconnue"
                anomalies.append(f"collecteur {nom} : journal fige depuis {age / 60:.0f} min "
                                 f"({detail} ; cadence {cadence:.0f} s)")
        else:
            frais += 1
    mesures.append(f"collecteurs frais : {frais} ; journal fige mais vivant : {figes} ; "
                   f"MORTS : {morts} ; sans journal : {sans_journal}")

    # 2) les rubans vitaux grossissent-ils ?
    for nom in RUBANS_VITAUX:
        ruban = root / "runtime" / "data" / nom
        age = _age_s(ruban, maintenant)
        if en_demarrage and (age is None or age > PLANCHER_FRAICHEUR_S):
            continue
        if age is None:
            anomalies.append(f"ruban vital {nom} : ABSENT")
            continue
        taille = ruban.stat().st_size
        if age > PLANCHER_FRAICHEUR_S:
            anomalies.append(f"ruban vital {nom} : plus ecrit depuis {age / 60:.0f} min")
        else:
            mesures.append(f"ruban {nom} : {taille / 1e6:.1f} Mo, ecrit il y a {age:.0f} s")

    # 3) la certification tourne-t-elle ?
    journaux = sorted((root / "runtime" / "logs" / "coffre_certifie").glob("certif_*.log"),
                      key=lambda p: p.stat().st_mtime, reverse=True) \
        if (root / "runtime" / "logs" / "coffre_certifie").is_dir() else []
    supervise = root / "runtime" / "logs" / "economic-coffre-certificateur.log"
    ages = [a for a in (_age_s(j, maintenant) for j in journaux[:1]) if a is not None]
    age_sup = _age_s(supervise, maintenant)
    if age_sup is not None:
        ages.append(age_sup)
    if not ages:
        anomalies.append("certification : AUCUNE trace de passage (le labo ne verra rien)")
    elif min(ages) > CERTIFICATION_MAX_S:
        anomalies.append(f"certification : aucun passage depuis {min(ages) / 60:.0f} min "
                         f"(cadence attendue 30 min)")
    else:
        mesures.append(f"certification : dernier passage il y a {min(ages) / 60:.0f} min")

    coffre = root / "runtime" / "coffre_certifie"
    if not coffre.is_dir():
        anomalies.append("coffre certifie : dossier ABSENT (le labo n'a aucune source)")

    # 4) disque, avec projection
    try:
        libre_go = shutil.disk_usage(str(root)).free / 1e9
    except OSError:
        libre_go = None
    if libre_go is None:
        anomalies.append("disque : espace libre NON MESURABLE")
    elif libre_go < DISQUE_MINIMAL_GO:
        anomalies.append(f"disque : {libre_go:.0f} Go libres (seuil {DISQUE_MINIMAL_GO:.0f})")
    else:
        mesures.append(f"disque : {libre_go:.0f} Go libres")

    return {"anomalies": anomalies, "mesures": mesures,
            "collecteurs_frais": frais, "collecteurs_figes": figes, "collecteurs_morts": morts,
            "horodatage": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(maintenant))}


def main(argv: list[str] | None = None) -> int:
    for flux in (sys.stdout, sys.stderr):
        with contextlib.suppress(AttributeError, ValueError):
            flux.reconfigure(encoding="utf-8", errors="replace")
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--root", default=str(RACINE))
    p.add_argument("--json", action="store_true")
    p.add_argument("--une-fois", action="store_true",
                   help="accepte et ignore : ce controle est deja ponctuel (compatibilite registre)")
    args = p.parse_args(argv)

    rapport = controler(Path(args.root))
    if args.json:
        print(json.dumps(rapport, ensure_ascii=False, indent=1))
        return 1 if rapport["anomalies"] else 0

    print(f"CONTROLE QUALITE DE LA CAMPAGNE — {rapport['horodatage']}")
    print("=" * 66)
    for ligne in rapport["mesures"]:
        print(f"  mesure   {ligne}")
    if rapport["anomalies"]:
        print()
        print(f"  {len(rapport['anomalies'])} ANOMALIE(S) :")
        for ligne in rapport["anomalies"]:
            print(f"    !! {ligne}")
        print()
        print("  Ces anomalies sont a traiter MAINTENANT : une campagne qui se degrade en silence")
        print("  ne se rattrape pas apres coup.")
        return 1
    print()
    print("  Aucune anomalie sur les points ci-dessus (tous mesures, aucun suppose).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
