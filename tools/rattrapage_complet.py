#!/usr/bin/env python3
"""LE RATTRAPAGE COMPLET, EN UNE SEULE COMMANDE, VISIBLE, ET QUI NE SE FAIT PAS TUER.

CE QU'IL REMPLACE
-----------------
Le 15/11, le rattrapage se lancait a la main, passe par passe. Deux passes ont tourne EN PARALLELE
(funding profond + bougies journalieres) et **le systeme les a tuees toutes les deux pour manque de
memoire** apres avoir servi 2 coins sur 261. Il n'y avait ni ordre, ni budget commun, ni garde
memoire, ni etat partage : juste deux commandes lancees cote a cote en esperant que ca tienne.

CE QU'IL FAIT, ET POURQUOI DANS CET ORDRE
-----------------------------------------
1. il MESURE ce qui manque, tache par tache, depuis l'etat des collecteurs (aucune requete) ;
2. il CLASSE par jours-coins gagnes par seconde de requete — ce qui fait passer le pas journalier
   (une requete rend toute l'histoire d'un coin) devant le funding (20,8 jours par requete), et
   respecte la precedence : un funding sans prix en face ne mesure RIEN ;
3. il execute **UNE tache a la fois** (`rattrapage_plan.concurrence()` rend 1, toujours) ;
4. il surveille la memoire entre chaque ligne de sortie et **s'arrete proprement** si elle devient
   critique, au lieu d'attendre que l'OS le tue ;
5. il AFFICHE tout : le plan, l'ETA, une ligne par coin, le bilan. « Pas de cmd muet. »

CE QU'IL REFUSE
---------------
* **tourner deux fois en meme temps** : un verrou de PID. Deux rattrapages concurrents, c'est
  exactement la memoire qui a saute, et deux ecrivains sur le meme etat ;
* **inventer un avancement** : l'avancement se lit de l'etat ECRIT par les passes, jamais d'une
  estimation de ce qu'elles auraient du faire ;
* **continuer apres un arret memoire** : on rend la main, on le DIT, et la passe suivante reprend
  ou celle-ci s'est arretee (l'etat est sauve apres chaque page).

PAPER / LECTURE SEULE. Les seules requetes sont les endpoints publics `candleSnapshot` et
`fundingHistory`. Aucun ordre, aucune cle, aucune signature.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))
sys.path.insert(0, str(RACINE / "src"))
sys.path.insert(0, str(RACINE / "tools"))

ETAT_SORTIE = Path("runtime") / "data" / "rattrapage_etat.json"
VERROU = Path("runtime") / "data" / "rattrapage_complet.lock"
SCHEMA = "hypersmart.rattrapage_complet.v1"
#: Au-dela, un verrou est considere comme le reste d'un passage tue (le PC coupe les runs longs).
VERROU_PERIME_S = 6 * 3600.0


def _flux_utf8() -> None:
    for flux in (sys.stdout, sys.stderr):
        with contextlib.suppress(AttributeError, ValueError):
            flux.reconfigure(encoding="utf-8", errors="replace")


def _pid_vivant(pid: int) -> bool:
    """Delegue au verrou partage (voir ``hl_observer.ops.verrou_pid``)."""
    from hl_observer.ops import verrou_pid as VP
    return VP.pid_vivant(pid)


def prendre_le_verrou(root: Path) -> tuple[bool, str]:
    """``(obtenu, explication)``. Un verrou vivant interdit un second rattrapage.

    16/11 — le CORPS de ce verrou vit maintenant dans ``hl_observer.ops.verrou_pid``, parce que le
    scelleur du coffre a besoin du meme : depuis que ce passage scelle lui-meme a la fin, deux
    scellages pouvaient ecrire le meme registre. Un seul verrou, deux outils.
    """
    from hl_observer.ops import verrou_pid as VP
    return VP.prendre(root / VERROU, perime_s=VERROU_PERIME_S, quoi="un rattrapage")


def rendre_le_verrou(root: Path) -> None:
    from hl_observer.ops import verrou_pid as VP
    VP.rendre(root / VERROU)


def charger_etat_collecteurs(root: Path) -> dict[str, dict[str, Any]]:
    from backfill_candles_vaults import ETAT, SCHEMA_ETAT
    try:
        brut = json.loads((root / ETAT).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if brut.get("_schema") != SCHEMA_ETAT:
        return {}
    series = brut.get("intervalles")
    return series if isinstance(series, dict) else {}


def coins_du_livre(root: Path) -> list[str]:
    from backfill_candles_vaults import charger_univers, coins_suivis, filtrer_abonnables
    coins, _inconnus = filtrer_abonnables(coins_suivis(root), charger_univers(root))
    return list(coins)


def ecrire_avancement(root: Path, **champs: Any) -> None:
    """Etat lisible par le certificateur et l'ecran de suivi. Ecriture atomique, jamais bloquante."""
    chemin = root / ETAT_SORTIE
    chemin.parent.mkdir(parents=True, exist_ok=True)
    tmp = chemin.with_name(f"{chemin.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(json.dumps({"_schema": SCHEMA, "maj_ms": int(time.time() * 1000), **champs},
                                  ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, chemin)
    except OSError as exc:
        print(f"[rattrapage] avancement non ecrit ({exc})", flush=True)
    finally:
        with contextlib.suppress(OSError):
            tmp.unlink(missing_ok=True)


def commande_pour(tache_nom: str, serie: str, *, root: Path, budget_s: float,
                  profondeur_jours: float) -> list[str]:
    """La commande exacte d'une tache. Une seule source de verite pour ce qui est lance."""
    outil = str(RACINE / "tools" / "backfill_candles_vaults.py")
    base = [sys.executable, "-X", "utf8", outil, "--root", str(root)]
    if serie == "funding":
        return [*base, "--seulement-funding", "--budget-funding-s", f"{budget_s:.0f}",
                "--profondeur-jours", f"{profondeur_jours:.0f}"]
    return [*base, "--intervalles", serie, "--sans-funding", "--budget-s", f"{budget_s:.0f}"]


#: Respirations successives avant de renoncer a une tache sous pression memoire : 30 s, 1 min,
#: 2 min, 4 min, 8 min — 15,5 min de patience au total. Respirer coute du TEMPS (le budget du
#: passage), jamais une page, jamais un coin, jamais un jour de profondeur.
#:
#: 16/11/2026 — POURQUOI PLUS QU'UNE SEULE ATTENTE DE 30 s. L'ancienne regle etait : une respiration
#: de 30 s, et si la RAM est encore rouge, on tue la tache. A 20:20 la machine avait 2,96 Go libres
#: (9 %) a cause de charges EXTERIEURES ; 30 s n'y ont rien change, et la passe funding est morte
#: avec 17 458 jours-coins encore a creuser.
PATIENCE_MEMOIRE_S: tuple[float, ...] = (30.0, 60.0, 120.0, 240.0, 480.0)

#: Actions possibles sous pression. On ne « degrade » jamais la donnee : on ralentit, on attend,
#: ou on rend la main a la tache suivante — ce qui est deja ecrit reste ecrit.
#: Nombre de taches rendues D'AFFILEE pour la memoire avant d'arreter tout le passage. Une seule
#: tache lourde qui rend la main ne doit pas priver les suivantes, souvent bien plus legeres.
ARRETS_MEMOIRE_AVANT_ABANDON = 2

CONTINUER = "CONTINUER"
RESPIRER = "RESPIRER"
RENDRE_LA_MAIN = "RENDRE_LA_MAIN"


def decider_sous_pression(*, niveau: str, arbre_octets: int, dispo_octets: int,
                          total_octets: int, respirations_faites: int) -> dict[str, Any]:
    """Quoi faire quand la memoire se tend : continuer, respirer, ou rendre la main.

    DEUX REGLES, et la premiere est celle qui manquait.

    1. **Arreter notre tache ne sert a rien si ce n'est pas nous.** La passe funding ecrit chaque
       page sur le disque et ne garde qu'une page en memoire : mesure du 16/11, l'arbre de
       processus d'Alina tenait 0,02 Go sur 24,04 Go utilises. Le gouverneur a vu 2,96 Go libres
       et le rattrapage a tue sa propre tache la plus sage, liberant environ un millieme du
       probleme. Quand le coupable est EXTERIEUR, on continue a travailler : c'est la seule
       decision qui ne detruit rien.

    2. **On retrecit la puissance, jamais les donnees.** Respirer ne coute que du temps. Et
       pendant que le parent respire, le tuyau de sortie de l'enfant se remplit : l'enfant se
       bloque de lui-meme sur un `print`, ENTRE deux pages, apres avoir ecrit et sauve son etat.
       Le ralentissement est donc gratuit en integrite.

    Aucune action n'est jamais prise sur un processus tiers : Alina ne touche que ce qu'elle a
    lance. Si Salad ou le navigateur saturent la machine, c'est a l'operateur de trancher.
    """
    from hl_observer.ops import budget_ram as BR

    if str(niveau).upper() != BR.ROUGE:
        return {"action": CONTINUER, "attente_s": 0.0, "coupable": None,
                "raison": f"memoire {niveau} : rien a faire"}
    faute = BR.coupable_de_la_pression(arbre_octets=arbre_octets, dispo_octets=dispo_octets,
                                       total_octets=total_octets)
    reste = len(PATIENCE_MEMOIRE_S) - max(0, int(respirations_faites))
    if reste > 0:
        attente = PATIENCE_MEMOIRE_S[max(0, int(respirations_faites))]
        return {"action": RESPIRER, "attente_s": float(attente), **faute,
                "raison": (f"RAM rouge ({faute['utilisee_go']} Go utilises, dont "
                           f"{faute['arbre_go']} Go a nous) : respiration {int(respirations_faites) + 1}"
                           f"/{len(PATIENCE_MEMOIRE_S)} de {attente:.0f} s")}
    if faute["coupable"] == "NOUS":
        return {"action": RENDRE_LA_MAIN, "attente_s": 0.0, **faute,
                "raison": (f"RAM rouge et c'est NOUS ({faute['part_arbre']:.0%} de la memoire "
                           f"utilisee) : rendre la main libere vraiment quelque chose")}
    return {"action": CONTINUER, "attente_s": 0.0, **faute,
            "raison": (f"RAM rouge mais la pression est EXTERIEURE (notre arbre tient "
                       f"{faute['arbre_go']} Go sur {faute['utilisee_go']} Go utilises) : "
                       f"s'arreter ne libererait rien, on continue a allure reduite")}


def executer(commande: list[str], *, root: Path, surveiller_memoire=True,
             journal: Path | None = None) -> dict[str, Any]:
    """Lance UNE tache, relaie sa sortie ligne par ligne, et s'arrete si la memoire devient critique.

    S'arreter soi-meme plutot que se faire tuer n'est pas un detail : un processus tue par l'OS ne
    ferme pas son etat proprement, et c'est ce qui est arrive aux deux passes du 15/11. Ici l'etat
    est deja sauve apres chaque page, et l'arret est ANNONCE.
    """
    from hl_observer.ops import budget_ram as BR

    env = {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONUTF8": "1"}
    debut = time.time()
    lignes_vues = 0
    arret_memoire = None
    respirations = 0
    attentes_memoire_s = 0.0
    memoire_exterieure_toleree = 0
    consommateurs_dits = False
    sortie_journal = None
    if journal is not None:
        journal.parent.mkdir(parents=True, exist_ok=True)
        sortie_journal = journal.open("a", encoding="utf-8", errors="replace")
    # LE JOURNAL EST DEJA OUVERT QUAND ON LANCE LE PROCESSUS (20/11/2026). Son `close()` vit
    # dans le `finally` plus bas, mais celui-ci ne couvre PAS la creation du processus : si
    # `Popen` leve -- commande absente, ou machine saturee ou Windows ne parvient plus a CREER
    # un processus -- la fonction sortait en laissant le descripteur a la merci du ramasse-
    # miettes. Observe en vrai ce jour-la, pendant le certificateur :
    #
    #     rattrapage_complet.py:466: ResourceWarning: unclosed file <_io.TextIOWrapper name=5>
    #
    # Sous Windows un descripteur qui traine maintient un VERROU sur le journal, et la tache
    # suivante ne peut plus y ecrire. On ferme donc avant de propager, sans rien avaler.
    try:
        proc = subprocess.Popen(commande, cwd=str(root), env=env, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                                errors="replace", bufsize=1)
    except BaseException:
        if sortie_journal is not None:
            sortie_journal.close()
        raise
    try:
        for ligne in proc.stdout or ():
            texte = ligne.rstrip("\n")
            print(f"  {texte}", flush=True)
            if sortie_journal is not None:
                sortie_journal.write(texte + "\n")
                sortie_journal.flush()
            lignes_vues += 1
            if not surveiller_memoire or lignes_vues % 5:
                continue
            dispo = BR.memoire_disponible_octets()
            total = BR.memoire_totale_octets()
            niveau = BR.niveau_pression(dispo_octets=dispo, total_octets=total)
            if niveau != BR.ROUGE:
                if respirations and niveau == BR.VERT:
                    print("  [rattrapage] la memoire a respire : on repart a pleine allure.",
                          flush=True)
                    respirations = 0
                continue
            verdict = decider_sous_pression(
                niveau=niveau, arbre_octets=BR.memoire_de_l_arbre_octets(),
                dispo_octets=dispo, total_octets=total, respirations_faites=respirations)
            print(f"  [rattrapage] {verdict['raison']}", flush=True)
            if verdict["coupable"] == "EXTERIEUR" and not consommateurs_dits:
                consommateurs_dits = True
                gros = ", ".join(f"{c['nom']} {c['go']} Go" for c in BR.plus_gros_consommateurs(4))
                print(f"  [rattrapage] ce qui tient la RAM : {gros}", flush=True)
                print("  [rattrapage] Alina ne touche AUCUN de ces processus : elle n'agit que sur "
                      "ce qu'elle a lance. A vous de decider si l'un doit ceder.", flush=True)
            if verdict["action"] == RESPIRER:
                respirations += 1
                attentes_memoire_s += verdict["attente_s"]
                # Pendant cette attente, le tuyau de sortie de l'enfant se remplit : il se bloque
                # tout seul sur un `print`, ENTRE deux pages deja ecrites et deja sauvees.
                BR.attendre_que_ca_respire(limite_s=verdict["attente_s"])
                continue
            if verdict["action"] == RENDRE_LA_MAIN:
                arret_memoire = verdict["raison"]
                print("[rattrapage] ARRET VOLONTAIRE : c'est bien NOTRE arbre qui sature. "
                      "L'etat est sauve apres chaque page, la tache reprend au passage suivant.",
                      flush=True)
                proc.terminate()
                break
            # CONTINUER sous pression exterieure : on reste au travail, l'enfant est deja ralenti
            # par la lecture plus lente de sa sortie. Rien n'est degrade, seulement retarde.
            memoire_exterieure_toleree += 1
    finally:
        with contextlib.suppress(Exception):
            code = proc.wait(timeout=120)
        if proc.poll() is None:
            proc.kill()
            code = proc.wait()
        code = proc.returncode
        if sortie_journal is not None:
            sortie_journal.close()
    return {"code": code, "duree_s": time.time() - debut, "lignes": lignes_vues,
            "arret_memoire": arret_memoire,
            # Ce qu'a coute la pression memoire, en TEMPS et jamais en donnees.
            "respirations": respirations,
            "attentes_memoire_s": round(attentes_memoire_s, 1),
            "memoire_exterieure_toleree": memoire_exterieure_toleree}


def decider_scellement(faits: list[dict[str, Any]], *, sans_scellement: bool,
                       interrompu: bool = False) -> tuple[bool, str]:
    """``(on_scelle, pourquoi_pas)``. Decision isolee de main() pour etre verifiable seule."""
    if interrompu:
        # Celui qui vient d'appuyer sur Ctrl+C ne doit pas se retrouver a attendre un scellage de
        # plusieurs minutes. Les donnees sont sur le disque ; on DIT ou elles en sont.
        return False, ("Ctrl+C : scellage non lance. Les donnees ecrites sont sur le disque ; la "
                       "campagne les scelle dans les 30 min si elle tourne, sinon lance "
                       "« Certificateur Coffre Fort.cmd »")
    if sans_scellement:
        return False, "--sans-scellement : le certificateur scelle juste apres"
    if not any(x.get("servie") for x in faits):
        return False, "aucune tache servie : rien de neuf a sceller"
    return True, ""


def sceller_le_coffre(root: Path, *, journal: Path | None = None,
                     surveiller_memoire: bool = True) -> dict[str, Any]:
    """Faire ENTRER au coffre-fort ce que ce passage vient d'ecrire.

    POURQUOI C'EST ICI ET PAS AILLEURS. Le coffre certifie est le seul magasin que lisent le labo
    et le moteur : une donnee ecrite dans ``runtime/history`` et non scellee leur est INVISIBLE,
    quelle que soit sa taille. La campagne scelle bien toutes les 30 minutes (collecteur
    « coffre-certificateur »), mais seulement PENDANT QU'ELLE TOURNE. Un rattrapage lance
    collecteurs fermes — ou dont la fenetre se ferme en cours de route, comme le 15/11 a 21 h 32 —
    laissait donc ses milliers de jours-coins dehors, jusqu'a ce que quelqu'un relance la campagne.

    Le scellage est INCREMENTAL : il reprend au dernier saut de ligne complet et ne rescelle pas ce
    qui l'est deja. Le faire une fois de trop ne coute presque rien ; ne pas le faire coute toute
    la donnee du passage.
    """
    outil = str(RACINE / "tools" / "sceller_coffre_local.py")
    commande = [sys.executable, "-X", "utf8", outil, "--root", str(root)]
    return executer(commande, root=root, journal=journal,
                    surveiller_memoire=surveiller_memoire)


def afficher_plan(plan: list[dict[str, Any]], *, debit: float) -> None:
    from hl_observer.ops import rattrapage_plan as RP

    print()
    print("PLAN DE RATTRAPAGE — classe par jours-coins gagnes par seconde de requete")
    print("=" * 88)
    print(f"  {'tache':<18}{'manque (j-coins)':>18}{'requetes':>10}{'cout':>10}"
          f"{'rendement':>12}")
    for ligne in plan:
        heures = ligne["cout_s"] / 3600.0
        cout = f"{heures:.1f} h" if heures >= 1.0 else f"{ligne['cout_s'] / 60:.0f} min"
        print(f"  {ligne['nom']:<18}{ligne['manque_jours_coins']:>18,.0f}"
              f"{ligne['requetes']:>10,}{cout:>10}{ligne['rendement']:>12.2f}")
    print("-" * 88)
    print(f"  TOTAL : {RP.eta_heures(plan):.1f} h de requetes au debit de {debit:.0f} u/min")
    print(f"  (le debit monte tout seul jusqu'a 600 u/min tant que la venue l'accepte : "
          f"l'ETA reel peut etre {600 / max(1.0, debit):.0f}x plus court)")
    for ligne in plan:
        print(f"    - {ligne['nom']} : {ligne['pourquoi']}")
        if ligne["depend_de"]:
            print(f"      depend de {', '.join(ligne['depend_de'])} "
                  "(un funding sans prix en face ne mesure rien)")
    print()


def main(argv: list[str] | None = None) -> int:
    _flux_utf8()
    from hl_observer.ops import budget_ram as BR
    from hl_observer.ops import rattrapage_plan as RP

    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--root", default=str(RACINE))
    p.add_argument("--budget-s", type=float, default=3600.0,
                   help="budget TOTAL de ce passage, toutes taches confondues")
    p.add_argument("--profondeur-jours", type=float, default=1100.0,
                   help="profondeur de funding visee (limite sondee de l'endpoint ~1 095 j)")
    p.add_argument("--taches", default="",
                   help="limiter a ces taches (noms separes par des virgules)")
    p.add_argument("--plan", action="store_true",
                   help="AFFICHER le plan et s'arreter : aucune requete, aucune ecriture")
    p.add_argument("--sans-garde-memoire", action="store_true",
                   help="ne pas s'arreter sur une memoire critique (deconseille)")
    p.add_argument("--sans-scellement", action="store_true",
                   help="ne pas sceller au coffre a la fin (le certificateur scelle juste apres)")
    p.add_argument("--une-fois", action="store_true", default=True)
    a = p.parse_args(argv)
    root = Path(a.root)

    print("=" * 88)
    print("  RATTRAPAGE COMPLET DES DONNEES — PAPER / LECTURE SEULE")
    print(f"  {time.strftime('%Y-%m-%d %H:%M:%S')} | budget {a.budget_s / 60:.0f} min | "
          f"une tache a la fois ({RP.concurrence()})")
    print("=" * 88)
    print(f"  {BR.journal_memoire('memoire')}")

    coins = coins_du_livre(root)
    etat = charger_etat_collecteurs(root)
    if not coins:
        print("[rattrapage] aucun coin suivi (ni fills, ni liste de coins) : rien a rattraper.")
        return 2
    now_ms = int(time.time() * 1000)
    manques = RP.manques(coins=coins, etat=etat, now_ms=now_ms,
                         profondeur_funding_j=a.profondeur_jours)
    demandees = {x.strip() for x in a.taches.split(",") if x.strip()}
    if demandees:
        inconnues = demandees - set(RP.TACHES_PAR_NOM)
        if inconnues:
            print(f"[rattrapage] tache(s) inconnue(s) : {', '.join(sorted(inconnues))}")
            print(f"             connues : {', '.join(RP.TACHES_PAR_NOM)}")
            return 2
        manques = {k: v for k, v in manques.items() if k in demandees}

    plan = RP.ordonner(manques)
    print(f"  {len(coins)} coins suivis | {len(plan)} tache(s) a faire")
    afficher_plan(plan, debit=100.0)
    if not plan:
        print("[rattrapage] tout est a jour : aucune requete a faire.")
        ecrire_avancement(root, etat="A_JOUR", coins=len(coins), taches=[])
        return 0
    if a.plan:
        print("[rattrapage] --plan : rien n'a ete lance.")
        return 0

    obtenu, mot = prendre_le_verrou(root)
    if not obtenu:
        # Le mot « REFUS » faisait classer cette ligne NORMALE en panne par les detecteurs
        # d'erreurs (harnais des .cmd, rapport collecteurs). Deux rattrapages a la fois est un
        # ETAT attendu, pas un echec : on le nomme comme tel.
        print(f"[rattrapage] DEJA EN COURS : {mot}.")
        print("             Deux rattrapages a la fois, c'est la memoire qui saute et deux "
              "ecrivains sur le meme etat.")
        return 3
    if mot:
        print(f"[rattrapage] {mot}")

    reparti = RP.repartir_budget(plan, total_s=a.budget_s)
    journal = root / "runtime" / "logs" / "rattrapage" / f"rattrapage_{time.strftime('%Y%m%d_%H%M%S')}.log"
    faits: list[dict[str, Any]] = []
    arret = None
    memoire_consecutives = 0
    # 16/11/2026 — LE BUDGET NON CONSOMME DOIT COULER VERS LA SUITE.
    #
    # Mesure du passage de 18:14 : `funding-profond` avait 26 894 s, s'est arrete sur LIMITE_DEBIT
    # apres 2 400 s, et les 24 494 s restantes ont ete PERDUES — `bougies-4h`, `bougies-1h` et
    # `bougies-5m` ont affiche « budget epuise » alors que 6 h 48 de budget dormaient. La
    # repartition etait calculee une fois pour toutes, au depart.
    #
    # Desormais on recalcule apres CHAQUE tache, sur le temps reellement restant. Une tache qui
    # finit tot rend son budget ; une tache qui deborde le prend a la suivante, ce qui reste juste :
    # le plan est deja trie par rendement.
    debut_passage = time.time()
    try:
        rang = 0
        restantes = list(reparti)
        while restantes:
            ligne = restantes.pop(0)
            rang += 1
            ecoule = time.time() - debut_passage
            reste_total = max(0.0, float(a.budget_s) - ecoule)
            if ligne["sert"] and restantes is not None:
                # Re-partage du temps REELLEMENT restant entre cette tache et les suivantes.
                encore = RP.repartir_budget([ligne, *restantes], total_s=reste_total)
                if encore:
                    ligne = encore[0]
                    restantes = encore[1:]
            if not ligne["sert"]:
                print(f"[rattrapage] {rang}/{len(reparti)} {ligne['nom']} : NON SERVIE "
                      f"({ligne['note']})", flush=True)
                faits.append({**{k: ligne[k] for k in ("nom", "serie", "manque_jours_coins")},
                              "servie": False, "note": ligne["note"]})
                continue
            tache = RP.TACHES_PAR_NOM[ligne["nom"]]
            print()
            print(f"[rattrapage] {rang}/{len(reparti)} >>> {ligne['nom']} | "
                  f"budget {ligne['budget_s'] / 60:.0f} min | "
                  f"manque {ligne['manque_jours_coins']:,.0f} jours-coins | {ligne['note']}",
                  flush=True)
            ecrire_avancement(root, etat="EN_COURS", coins=len(coins), tache=ligne["nom"],
                              rang=rang, total=len(reparti),
                              taches=[{"nom": x["nom"], "budget_s": x["budget_s"]} for x in reparti])
            commande = commande_pour(ligne["nom"], tache.serie, root=root,
                                     budget_s=ligne["budget_s"],
                                     profondeur_jours=a.profondeur_jours)
            bilan = executer(commande, root=root, journal=journal,
                             surveiller_memoire=not a.sans_garde_memoire)
            faits.append({"nom": ligne["nom"], "serie": tache.serie, "servie": True,
                          "duree_s": bilan["duree_s"], "code": bilan["code"],
                          "arret_memoire": bilan["arret_memoire"]})
            print(f"[rattrapage] {ligne['nom']} termine en {bilan['duree_s'] / 60:.0f} min "
                  f"(code {bilan['code']})", flush=True)
            if bilan["arret_memoire"]:
                memoire_consecutives += 1
                # 16/11 — UNE TACHE RENDUE NE DOIT PAS EMPORTER LES SUIVANTES. Au passage de
                # 19:03, `funding-profond` a consomme 4 485 s avant de rendre la main sur la
                # memoire, et le `break` a prive `bougies-4h`, `-1h` et `-5m` de leur passage —
                # alors que `bougies-1d` n'avait pris qu'UNE seconde. Les taches suivantes sont
                # souvent plus legeres : on leur laisse leur chance.
                if memoire_consecutives >= ARRETS_MEMOIRE_AVANT_ABANDON:
                    arret = "MEMOIRE_CRITIQUE"
                    print(f"[rattrapage] {memoire_consecutives} taches d'affilee rendues pour la "
                          "memoire : on arrete ce passage. L'etat est sauve, tout reprend au "
                          "suivant.", flush=True)
                    break
                print(f"[rattrapage] {ligne['nom']} a rendu la main pour la memoire. On passe a la "
                      "tache suivante (souvent plus legere) : rien de ce qui est ecrit n'est "
                      "perdu.", flush=True)
            else:
                memoire_consecutives = 0
    except KeyboardInterrupt:
        # 16/11 — EXIGENCE DE FLORENT : « le rattrapage doit pouvoir etre ferme via Ctrl+C sans
        # perdre aucune donnee ». Sans ce bloc, Ctrl+C remontait une pile d'erreur et sautait
        # l'ecriture de l'avancement : le fichier restait sur « EN_COURS » pour toujours, c'est-a-dire
        # qu'il MENTAIT sur l'etat. Les donnees, elles, etaient deja sauves — ce qui manquait, c'etait
        # de le DIRE et de laisser un etat relisible.
        arret = "CTRL_C"
        print()
        print("[rattrapage] Ctrl+C recu — ARRET PROPRE. Rien de ce qui est ecrit n'est perdu :")
        print("             * chaque page est ecrite en LIGNES ENTIERES sur le ruban avant la suivante ;")
        print("             * l'etat d'avancement est sauve de facon ATOMIQUE apres chaque page ;")
        print("             * le passage suivant reprend exactement ou celui-ci s'arrete.")
    finally:
        rendre_le_verrou(root)

    # L'avancement final se lit de l'etat REELLEMENT ecrit par les passes, pas de ce qu'on
    # esperait qu'elles fassent.
    etat_apres = charger_etat_collecteurs(root)
    restant_brut = RP.manques(coins=coins, etat=etat_apres, now_ms=int(time.time() * 1000),
                              profondeur_funding_j=a.profondeur_jours)
    restant = {k: float((v or {}).get("jours_coins", 0.0)) for k, v in restant_brut.items()}
    avant = {k: float((v or {}).get("jours_coins", 0.0)) for k, v in manques.items()}
    gagnes = {k: max(0.0, avant.get(k, 0.0) - restant.get(k, 0.0)) for k in avant}
    print()
    print("BILAN DU RATTRAPAGE")
    print("=" * 88)
    for nom, gain in sorted(gagnes.items(), key=lambda kv: -kv[1]):
        if gain or nom in {x["nom"] for x in faits if x.get("servie")}:
            print(f"  {nom:<18} +{gain:>12,.0f} jours-coins | reste {restant.get(nom, 0.0):>12,.0f}")
    print(f"  {BR.journal_memoire('memoire')}")
    if arret:
        print(f"  ARRET : {arret} — le passage suivant reprendra ici.")
    # LE COFFRE EST LE MAGASIN PRINCIPAL : une donnee non scellee n'existe pas pour le labo
    # ni pour le moteur. On scelle donc ici, et pas « plus tard quand la campagne tournera ».
    scellement: dict[str, Any] = {"fait": False, "note": ""}
    on_scelle, pourquoi_pas = decider_scellement(faits, sans_scellement=a.sans_scellement,
                                                 interrompu=(arret == "CTRL_C"))
    if not on_scelle:
        scellement["note"] = pourquoi_pas
    else:
        print()
        print("SCELLEMENT AU COFFRE-FORT (le magasin que lit le labo)")
        print("=" * 88)
        bilan_coffre = sceller_le_coffre(root, journal=journal,
                                         surveiller_memoire=not a.sans_garde_memoire)
        scellement = {"fait": bilan_coffre["code"] == 0, "code": bilan_coffre["code"],
                      "duree_s": bilan_coffre["duree_s"],
                      "arret_memoire": bilan_coffre["arret_memoire"],
                      "note": ""}
        if bilan_coffre["code"] == 0:
            print(f"[rattrapage] coffre a jour en {bilan_coffre['duree_s'] / 60:.0f} min : "
                  "le labo et le moteur voient ces donnees.")
        else:
            scellement["note"] = (f"le scellage a rendu le code {bilan_coffre['code']} : ces "
                                  "donnees restent HORS du coffre, donc invisibles pour le labo")
            print(f"[rattrapage] ATTENTION — {scellement['note']}.")
            print("             Relancer « Certificateur Coffre Fort.cmd » les fera entrer.")
    if scellement["note"] and not scellement["fait"]:
        print(f"  coffre : {scellement['note']}")
    ecrire_avancement(root, etat=(arret or "FINI"), coins=len(coins), taches=faits,
                      gagnes_jours_coins=gagnes, restant_jours_coins=restant,
                      scellement=scellement, journal=str(journal))
    print(f"  journal : {journal}")
    return 130 if arret == "CTRL_C" else 0


if __name__ == "__main__":
    raise SystemExit(main())
