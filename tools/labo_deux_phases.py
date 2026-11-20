"""Enchaine les DEUX PHASES du labo : preparer tranche par tranche, explorer une seule fois.

    python tools/labo_deux_phases.py . --plan runtime/reports/plan_tranches.json
    python tools/labo_deux_phases.py . --phase 1      # preparer seulement
    python tools/labo_deux_phases.py . --phase 2      # explorer un corpus deja prepare

POURQUOI DEUX PHASES. Le corpus causal exploitable fait six journees, soit une cinquantaine de
gigaoctets : on ne peut pas le charger d'un coup. Le decouper en tranches tient en memoire, mais
une tranche de quatre heures est trop courte pour un decoupage TRAIN/OOS : le labo rend
`TEMPORAL_SPLIT_INVALID_AFTER_PURGE` et n'essaie AUCUN candidat. Assez petit pour tenir = trop
petit pour chercher. L'impasse se leve en separant ce qui se decoupe de ce qui ne se decoupe pas.

  * **Phase 1**, une tranche a la fois : reconstruire les cycles du leader, en tirer les
    metaordres, et ne garder des carnets que ceux a portee causale d'un signal -- un carnet hors de
    cette fenetre ne sera JAMAIS lu par l'alignement, donc le transporter coute de la memoire pour
    rien. C'est ce tri qui fait passer d'une cinquantaine de gigaoctets a quelques-uns.
  * **Phase 2**, une seule fois : relire les tranches preparees, fusionner, et laisser le labo
    aligner, decouper TRAIN/OOS et explorer sur l'ENSEMBLE -- ou le decoupage a enfin un sens.

CE QUE CE LANCEUR NE FAIT PAS. Il ne juge rien et ne calcule aucun PnL : la phase 1 transporte et
compte, la phase 2 delegue tout verdict au labo. Un conducteur qui agregerait des verdicts de
tranches ferait une moyenne de moyennes, et c'est exactement ce que cette architecture evite.

LA MEMOIRE EST SURVEILLEE. Entre deux tranches, la phase 1 regarde la memoire libre et s'arrete
proprement plutot que de faire tomber la machine -- les collecteurs tournent a cote, et une
tranche non preparee se rattrape, un collecteur interrompu non.
"""

from __future__ import annotations

import argparse
import gc
import json
import sys
from pathlib import Path
from typing import Any

RACINE = Path(__file__).resolve().parents[1]
# LES DEUX chemins : `src` pour `hl_observer`, et la RACINE parce que le labo importe
# `tools.copy_vault_continuity`. N'ajouter que `src` donne un
# « ModuleNotFoundError: No module named 'tools' » au premier import du labo.
for _chemin in (RACINE / "src", RACINE):
    if str(_chemin) not in sys.path:
        sys.path.insert(0, str(_chemin))

from hl_observer.backtesting.copy_vault_coffre_vers_labo import (  # noqa: E402
    ACTIONS_COPIEES_PAR_LA_POLITIQUE,
    carnets_du_coffre,
    copiable_par_la_politique,
    fills_du_coffre,
    positions_du_coffre,
)
from hl_observer.backtesting.copy_vault_position_derivee import (  # noqa: E402
    fusionner_positions,
    positions_depuis_les_fills,
)
from hl_observer.backtesting.copy_vault_labo_deux_phases import (  # noqa: E402
    MANIFESTE,
    preparer_tranche,
)

#: En dessous, la phase 1 s'arrete entre deux tranches plutot que d'etouffer la machine.
#: Une tranche non preparee se rattrape au prochain lancement ; un collecteur tue, non.
RAM_LIBRE_MINIMALE_GO = 2.5


def _memoire_libre_go() -> float | None:
    try:
        import psutil
    except ImportError:
        return None
    return psutil.virtual_memory().available / 1e9


def _tranches_du_plan(chemin: Path) -> list[tuple[int, int]]:
    plan = json.loads(chemin.read_text(encoding="utf-8"))
    brut = plan.get("tranches") or plan.get("plan") or []
    tranches: list[tuple[int, int]] = []
    for item in brut:
        if isinstance(item, dict):
            debut = item.get("debut_ms", item.get("depuis_ms"))
            fin = item.get("fin_ms", item.get("jusqu_a_ms"))
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            debut, fin = item[0], item[1]
        else:
            continue
        if debut is None or fin is None:
            continue
        tranches.append((int(debut), int(fin)))
    return tranches


def _nombre(valeur: Any) -> float | None:
    try:
        return float(valeur)
    except (TypeError, ValueError):
        return None


def phase_1(
    workspace: Path, tranches: list[tuple[int, int]], sortie: Path, *, reprendre: bool = True,
    min_notionnel: float | None = None,
) -> dict[str, Any]:
    """Prepare chaque tranche sur disque. Reprend ou elle s'est arretee."""
    from hl_observer.backtesting import copy_vault_executable as cv
    from hl_observer.backtesting.copy_vault_local_lab import _load_pipeline

    pipeline = _load_pipeline()   # garde pour le repli si le coffre manque
    sortie.mkdir(parents=True, exist_ok=True)
    faits: list[dict[str, Any]] = []
    sautees = 0
    arret: str | None = None

    for index, (debut, fin) in enumerate(tranches, start=1):
        nom = f"t{index:03d}_{debut}_{fin}"
        dossier = sortie / nom
        if reprendre and (dossier / MANIFESTE).exists():
            sautees += 1
            continue

        libre = _memoire_libre_go()
        if libre is not None and libre < RAM_LIBRE_MINIMALE_GO:
            # On s'arrete AVANT de charger, pas pendant : la collecte tourne a cote.
            arret = f"RAM_INSUFFISANTE ({libre:.1f} Go libres < {RAM_LIBRE_MINIMALE_GO})"
            print(f"   [ARRET] {arret} — {len(tranches) - index + 1} tranche(s) restante(s)")
            break

        print(f"   [{index}/{len(tranches)}] {nom} — reconstruction", flush=True)
        # LES FILLS VIENNENT DU COFFRE. Le pipeline lit `runtime/data/vault_fills_live.jsonl`, qui
        # ne retient que la source `LIVE_WS` (demarree le 17/11 19:10) : 2 journees. Le coffre
        # porte `fills_forward` -- 21,6 M de lignes sur 23 journees -- avec en plus `LIVE_POLL`,
        # une collecte par interrogation active depuis le 13/11 et tout aussi causale. Mesure du
        # 18/11/2026 : 30 minutes du coffre rendent 6 876 metaordres causaux, soit 3,6 fois ce que
        # six journees du ruban local donnaient. Il ne manquait pas de donnees, mais un chemin.
        # LA POSITION DU LEADER AVANT CHAQUE FILL, lue et non supposee. Sans elle, la distinction
        # entre une ouverture et un renforcement est indecidable pour 99,6 % des fills -- et la
        # politique gelee ne copie QUE les renforcements. C'etait la cause racine du refus unanime.
        positions, positions_audit = positions_du_coffre(workspace, debut_ms=debut, fin_ms=fin)
        if positions_audit.get("status") == "LU_DEPUIS_LE_COFFRE":
            print(f"        positions : {positions_audit['observations_gardees']} observation(s) "
                  f"sur {positions_audit['couples_vault_coin']} couple(s) leader/coin", flush=True)
        # LA QUEUE DE DISTRIBUTION, QUI MANQUAIT (19/11/2026). La famille "position" ne couvre
        # que 179 coins sur les 1 648 qui portent des fills : 6 194 061 fills etaient jetes
        # faute de position connue, soit 44 % des lignes lues, et toujours les MEMES coins --
        # un biais de selection, pas seulement un trou. "fills_backfill" porte start_position
        # sur 81,3 % de ses lignes et comble cette queue.
        #
        # ETAT, JAMAIS SIGNAL : ces fills ne sont connus qu apres coup (chaque ligne porte
        # "causal_forward_eligible: False"), donc ils ne deviennent JAMAIS des evenements
        # a copier -- FAMILLES_DE_FILLS reste ("fills_forward",). Ils ne repondent qu a la
        # question « que detenait le leader avant SON fill », dont la reponse ne depend pas du
        # moment ou nous l avons apprise. La causalite reste imposee par position_avant.
        derivees, audit_derivees = positions_depuis_les_fills(
            workspace, debut_ms=debut, fin_ms=fin)
        if audit_derivees.get("observations_gardees"):
            avant_fusion = len(positions)
            positions = fusionner_positions(positions, derivees)
            print(f"        positions derivees : {audit_derivees['observations_gardees']} "
                  f"observation(s) sur {audit_derivees['couples_vault_coin']} couple(s) "
                  f"-> {avant_fusion} puis {len(positions)} couple(s) apres fusion", flush=True)
        entrees, fills_audit = fills_du_coffre(
            workspace, debut_ms=debut, fin_ms=fin, positions=positions or None)
        if fills_audit.get("status") == "COFFRE_ABSENT":
            print(f"        [REPLI] coffre absent -> pipeline local ({fills_audit['chemin']})")
            entrees, _audit = pipeline.charger_entrees_alpha_notional_fixe_avec_audit(
                workspace, fenetre=(debut, fin))
        else:
            print(f"        fills : {fills_audit['lignes_lues']} lue(s) -> "
                  f"{fills_audit['entrees_rendues']} entree(s) "
                  f"({fills_audit['ecartes_libelle_inconnu']} libelle inconnu, "
                  f"{fills_audit['ecartes_champ_manquant']} champ manquant, "
                  f"{fills_audit.get('ecartes_position_inconnue', 0)} position inconnue, "
                  f"{fills_audit.get('doublons_de_hash', 0)} doublon(s) dont "
                  f"{fills_audit.get('doublons_plus_informatifs', 0)} corrige(s))", flush=True)
            print(f"        actions : {fills_audit.get('actions')}", flush=True)
        metaordres, _meta_audit = cv.cluster_metaorders(entrees)
        del entrees
        gc.collect()
        # D'ABORD, NE GARDER QUE CE QUE LA POLITIQUE SAIT COPIER. Voir
        # `ACTIONS_COPIEES_PAR_LA_POLITIQUE` : elle ne copie que les RENFORCEMENTS, soit 0,3 % des
        # fills. Ce filtre-la est economiquement fonde -- il n'ecarte aucun candidat possible --
        # alors qu'un seuil de notionnel en ecarte, et pas ceux qu'on croit : il garde surtout de
        # gros fills isoles, qui sont des OUVERTURES, donc exactement ce que la politique refuse.
        # Mesure du 19/11/2026 : le corpus filtre a 20 000 USD rendait 765 signaux, dont 765
        # refuses en `NON_ADD_REJECTED`, donc zero candidat et zero trade.
        avant_action = len(metaordres)
        metaordres = [o for o in metaordres if copiable_par_la_politique(o)]
        print(f"        copiables par la politique "
              f"({'/'.join(ACTIONS_COPIEES_PAR_LA_POLITIQUE)}) : {len(metaordres)} "
              f"sur {avant_action}", flush=True)
        if min_notionnel:
            # LE SEUIL EN PHASE 1, parce que c'est lui qui decide quels signaux auront besoin de
            # carnets. Chaque signal retenu ouvre une fenetre de ~1 h (reference, entree, sortie) :
            # avec 89 509 signaux par tranche, les fenetres se recouvrent et couvrent tout le
            # temps, donc 98,3 % des carnets sont conserves et l'economie de la phase 1 dispar
            # ait. Mesure du 19/11/2026 : >=100 000 USD laisse 8 027 signaux sur les six journees.
            avant = len(metaordres)
            metaordres = [
                o for o in metaordres
                if (lambda v: v is not None and v >= min_notionnel)(
                    _nombre(o.get("leader_notional_usd")))
            ]
            print(f"        notionnel >= {min_notionnel:.0f} USD : {len(metaordres)} signal(aux) "
                  f"retenu(s) sur {avant}", flush=True)
        # LES CARNETS VIENNENT DU COFFRE. `load_observed_books` lit `runtime/data/*.jsonl`, qui
        # ne commence qu'au 17/11 18:35 ; le coffre porte `bbo` et `book_l2` depuis le 26/10.
        # Branchee sur les rubans locaux, la phase 1 preparait du vide pour toute tranche
        # anterieure -- en rendant honnetement « 0/0 », ce qui se lit comme « pas de carnets »
        # alors que la cause etait « pas regarde au bon endroit ».
        instants: dict[str, list[int]] = {}
        for ordre in metaordres:
            instants.setdefault(str(ordre["coin"]), []).append(int(ordre["signal_ts_ms"]))
        carnets, carnets_audit = carnets_du_coffre(
            workspace, coins=sorted(instants), debut_ms=debut, fin_ms=fin,
            instants_par_coin=instants)
        if carnets_audit.get("status") == "COFFRE_ABSENT":
            # Repli explicite, jamais silencieux : on DIT d'ou viennent les carnets.
            print(f"        [REPLI] coffre absent -> rubans locaux ({carnets_audit['chemin']})")
            carnets, _books_audit = cv.load_observed_books(
                workspace, coins=sorted(instants), depuis_ms=debut, as_of_ms=fin)
        else:
            print(f"        coffre : {carnets_audit['lignes_lues']} ligne(s) lue(s), "
                  f"{carnets_audit['carnets_gardes']} carnet(s) retenu(s) "
                  f"sur {carnets_audit['coins_avec_carnets']} coin(s)", flush=True)

        manifeste = preparer_tranche(
            metaordres=metaordres, carnets=carnets, sortie=dossier,
            tranche=(debut, fin), identite=nom)
        audit = manifeste["audit_carnets"]
        # L'ALLEGEMENT REEL SE MESURE SUR LES LIGNES LUES AU COFFRE, pas sur `carnets_vus` :
        # `carnets_utiles` ne voit que des carnets DEJA filtres en flux, donc elle en ecarte
        # ~0 % et afficher ce taux laisserait croire que le tri ne sert a rien. Mesure du
        # 18/11/2026 sur t001 : 1 820 054 lignes lues au coffre -> 23 046 retenues, soit 98,7 %
        # ecartees. C'est ce chiffre-la qui dit si la phase 1 gagne quelque chose.
        lues = int(carnets_audit.get("lignes_lues") or 0)
        retenues = int(carnets_audit.get("carnets_gardes") or audit["carnets_gardes"])
        manifeste["audit_coffre"] = dict(carnets_audit)
        taux = f" ({1 - retenues / lues:.1%} ecartees)" if lues else ""
        # DIRE POURQUOI ELLES SONT ECARTEES (20/11/2026). « 99,1 % ecartees » sans motif ne
        # permet pas de distinguer une SELECTION saine -- un carnet ne sert que s il repond a
        # une ancre de signal -- d une PERTE silencieuse. Le rejet le plus massif n etait meme
        # pas compte. On affiche desormais les trois motifs, du plus gros au plus petit.
        motifs = " ; ".join(
            f"{libelle}={carnets_audit[cle]:,}".replace(",", " ")
            for cle, libelle in (
                ("ecartes_sans_coin_ou_horloge", "sans coin ni horloge"),
                ("ecartes_champs_manquants", "champs bid/ask/capacity manquants"),
                ("ecartes_aucun_signal_assez_proche", "aucun signal assez proche"),
                ("ecartes_sans_identite_de_connexion", "sans identite de connexion"),
                ("ecartes_trop_denses", "budget d ancre plein"),
                ("ecartes_coin_sans_signal", "coin sans signal"),
                ("non_explique", "NON EXPLIQUE (anomalie)"),
            ) if carnets_audit.get(cle)
        )
        print(
            f"        {manifeste['metaordres']} metaordres | "
            f"{retenues} carnet(s) retenu(s) sur {lues} lue(s){taux}",
            flush=True,
        )
        if motifs:
            print(f"        motifs du rejet : {motifs}", flush=True)
        faits.append(manifeste)
        del metaordres, carnets
        gc.collect()

    # Le denominateur honnete est le nombre de lignes LUES au coffre : c'est ce que la phase 1 a
    # traverse. `carnets_vus` ne compte que ce qui avait deja passe le filtre en flux.
    lues = sum(int(m.get("audit_coffre", {}).get("lignes_lues") or 0) for m in faits)
    gardes = sum(m["audit_carnets"]["carnets_gardes"] for m in faits)
    return {
        "tranches_du_plan": len(tranches),
        "tranches_preparees": len(faits),
        "tranches_deja_faites": sautees,
        "metaordres": sum(m["metaordres"] for m in faits),
        "lignes_lues_au_coffre": lues,
        "carnets_gardes": gardes,
        "allegement": (1 - gardes / lues) if lues else None,
        "arret": arret,
    }


def phase_2(
    workspace: Path, corpus: Path, *, max_trials: int, continu: bool = False
) -> dict[str, Any]:
    """Explore UNE FOIS sur le corpus fusionne. Tout verdict appartient au labo."""
    from hl_observer.backtesting.copy_vault_local_lab import run_local_campaign

    return run_local_campaign(
        workspace,
        progress=lambda message: print(f"   {message}", flush=True),
        corpus_prepare=corpus,
        max_trials=max_trials,
        # `BOUNDED_TRAIN_SEARCH_BATCH_COMPLETE` veut dire « ce LOT est fini », pas « la recherche
        # est finie » : sans le mode continu, on s'arrete apres `max_trials` essais sans jamais
        # rendre de verdict economique.
        continuous=continu,
    )


def main(argv: list[str] | None = None) -> int:
    parseur = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parseur.add_argument("workspace", type=Path)
    parseur.add_argument("--plan", type=Path, default=None,
                         help="plan de tranches (defaut: runtime/reports/plan_tranches.json)")
    parseur.add_argument("--sortie", type=Path, default=None,
                         help="ou vivent les tranches preparees")
    parseur.add_argument("--phase", choices=("1", "2", "tout"), default="tout")
    parseur.add_argument("--max-tranches", type=int, default=None)
    parseur.add_argument("--max-trials", type=int, default=128)
    parseur.add_argument("--continu", action="store_true",
                         help="poursuit la recherche jusqu'a un verdict, lot apres lot")
    parseur.add_argument("--min-notionnel", type=float, default=None,
                         help="notionnel minimum du leader, applique DES la phase 1")
    parseur.add_argument("--sans-reprise", action="store_true",
                         help="refait les tranches deja preparees")
    args = parseur.parse_args(argv)

    workspace = args.workspace.resolve()
    sortie = (args.sortie or workspace / "runtime/labo_phase1").resolve()
    plan = (args.plan or workspace / "runtime/reports/plan_tranches.json").resolve()

    if args.phase in ("1", "tout"):
        if not plan.exists():
            print(f"[REFUS] plan absent : {plan}")
            print("        produire d'abord : tools/conduire_labo_par_tranches.py "
                  ". --depuis-le-coffre --sortie <plan>")
            return 2
        tranches = _tranches_du_plan(plan)
        if args.max_tranches:
            tranches = tranches[: args.max_tranches]
        if not tranches:
            print(f"[REFUS] aucune tranche lisible dans {plan}")
            return 2
        print(f"=== PHASE 1 : preparer {len(tranches)} tranche(s) -> {sortie} ===")
        bilan = phase_1(workspace, tranches, sortie, reprendre=not args.sans_reprise,
                        min_notionnel=args.min_notionnel)
        allegement = bilan["allegement"]
        print(f"=== PHASE 1 terminee : {bilan['tranches_preparees']} preparee(s), "
              f"{bilan['tranches_deja_faites']} deja faite(s) ===")
        print(f"    {bilan['metaordres']} metaordres | {bilan['carnets_gardes']} carnets "
              f"retenus sur {bilan['lignes_lues_au_coffre']} lignes lues au coffre"
              + (f" ({allegement:.1%} ecartees)" if allegement is not None else ""))
        if bilan["arret"]:
            print(f"    [INCOMPLET] {bilan['arret']} — relancer pour continuer")
            if args.phase == "tout":
                print("    phase 2 NON lancee : un corpus incomplet donnerait un resultat "
                      "mesure sur moins de donnees que prevu, sans le dire.")
                return 3

    if args.phase in ("2", "tout"):
        print(f"=== PHASE 2 : explorer le corpus fusionne ({sortie}) ===")
        resultat = phase_2(workspace, sortie, max_trials=args.max_trials,
                           continu=args.continu)
        print(f"    statut            : {resultat.get('status')}")
        print(f"    raison            : {resultat.get('reason')}")
        print(f"    candidats essayes : {resultat.get('candidates_tested')}")
        for cle in ("daily_net_pnl_usd", "net_pnl_usd", "economically_proven"):
            if cle in resultat:
                print(f"    {cle:<18}: {resultat[cle]}")
        if resultat.get("candidates_tested", 0) == 0:
            print("    [ATTENTION] aucun candidat essaye : le resultat n'est pas un PnL, "
                  "c'est un refus. Lire la raison ci-dessus.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
