"""ETA VIVANT : combien de temps encore collecter pour que le labo ait ce qu'il lui faut ?

CE QUI BLOQUE LE LABO, mesure et non suppose (22/11/2026). Sa porte n'est pas un volume
d'octets : c'est **le nombre de JOURNEES UTC distinctes et DENSES** de signaux evaluables.

* evaluable = un signal dont le carnet causal le plus recent le precede de moins de 30 s
  (`copy_vault_signal_alignment.MAX_BOOK_AGE_MS`) ;
* dense = la journee porte au moins `MIN_SIGNALS_PER_DAY` signaux evaluables ;
* requis = `diagnostic_signal.MINIMUM_SIGNAL_UTC_DAYS` journees denses DANS UNE tranche
  (`_bounds`, plancher absolu 3).

POURQUOI L'ETA N'EST PAS UNE DATE FIXE. Une journee UTC ne s'acquiert qu'une fois par jour
calendaire, et **seulement si le debit suffit a la rendre dense**. L'ETA depend donc de deux
choses qui bougent : les journees deja acquises, et le debit observe a l'instant. Si le debit
tombe, la journee en cours cesse de compter et l'ETA RECULE -- c'est le comportement voulu,
pas un defaut.

TROIS REFUS PLUTOT QU'UN CHIFFRE RASSURANT :

* debit nul -> `INFINI (collecte eteinte)`, jamais une duree ;
* corpus illisible -> `INCONNU` avec le motif, jamais zero ;
* journees deja suffisantes -> `ATTEINT`, et on le dit au lieu de proposer d'attendre.

LECTURE SEULE. Aucun reseau, aucun ordre, aucune ecriture dans les rubans. Le calcul lourd
(journees denses) est refait a intervalle long ; le debit, lui, se mesure a chaque
rafraichissement sur la CROISSANCE du ruban -- une operation en temps constant.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
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
    "runtime/data/vault_fills_live.jsonl",
    "runtime/labo_tranches_20261121/workspace/runtime/data/vault_fills_live.jsonl",
)


def trouver_ruban(racine) -> tuple[Path | None, list[str]]:
    """Le premier ruban existant, et la liste de ce qui a ete cherche."""
    cherches: list[str] = []
    for relatif in RUBANS_FILLS:
        cherches.append(relatif)
        candidat = Path(racine) / relatif
        if candidat.is_file():
            return candidat, cherches
    return None, cherches
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
    2. si le debit est nul ou inconnu -> `INFINI` / `INCONNU`, jamais une duree ;
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
                "motif": "debit non mesurable (ruban illisible ou mesure perimee)"}
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
        """`{debit_par_heure, lignes_par_minute, age_s, motif}` — `None` si inconnu."""
        if self.octets_par_ligne is None:
            self._mesurer_la_ligne_moyenne()
        try:
            taille = self.chemin.stat().st_size
        except OSError:
            self._dernier = None
            return {"debit_par_heure": None, "lignes_par_minute": None, "age_s": None,
                    "motif": "RUBAN_ILLISIBLE"}
        maintenant = time.time()
        if self._dernier is None:
            self._dernier = (maintenant, taille)
            return {"debit_par_heure": None, "lignes_par_minute": None, "age_s": 0.0,
                    "motif": "PREMIERE_MESURE"}
        t0, taille0 = self._dernier
        ecoule = maintenant - t0
        if ecoule <= 0:
            return {"debit_par_heure": None, "lignes_par_minute": None, "age_s": 0.0,
                    "motif": "INTERVALLE_NUL"}
        if ecoule > AGE_MAX_DEBIT_S:
            self._dernier = (maintenant, taille)
            return {"debit_par_heure": None, "lignes_par_minute": None,
                    "age_s": round(ecoule, 1), "motif": "MESURE_PERIMEE"}
        self._dernier = (maintenant, taille)
        if self.octets_par_ligne is None or self.octets_par_ligne <= 0:
            return {"debit_par_heure": None, "lignes_par_minute": None,
                    "age_s": round(ecoule, 1), "motif": "LIGNE_MOYENNE_INCONNUE"}
        lignes = max(0, taille - taille0) / self.octets_par_ligne
        par_minute = lignes / (ecoule / 60.0)
        return {"debit_par_heure": par_minute * 60.0, "lignes_par_minute": par_minute,
                "age_s": round(ecoule, 1), "motif": None}


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
    p.add_argument("--intervalle", type=float, default=5.0,
                   help="secondes entre deux rafraichissements de l'ETA")
    p.add_argument("--tours", type=int, default=0,
                   help="nombre de rafraichissements (0 = sans fin, q pour quitter)")
    p.add_argument("--sonde", default="runtime/reports/sonde_horloges_20261122.json",
                   help="rapport de la sonde des horloges : source des journees DENSES")
    p.add_argument("--requis", type=int, default=DS.MINIMUM_SIGNAL_UTC_DAYS)
    p.add_argument("--une-fois", action="store_true", help="une seule mesure, puis sortie")
    args = p.parse_args(argv)

    racine = Path(args.racine).resolve()
    flux = sys.stdout
    try:  # noqa: SIM105
        flux.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

    ruban, cherches = trouver_ruban(racine)
    debit = MesureDeDebit(ruban) if ruban else MesureDeDebit(racine / RUBANS_FILLS[0])
    chemin_sonde = racine / args.sonde
    sonde = _charger_etat_de_fond(chemin_sonde)
    denses_acquis = 0
    source_denses = "AUCUNE (aucune sonde lue : le compte des journees est INCONNU)"
    age_sonde_h = None
    if sonde:
        appariement = sonde.get("appariement") or {}
        denses_acquis = int(appariement.get("jours_DENSES") or 0)
        try:
            age_sonde_h = (time.time() - chemin_sonde.stat().st_mtime) / HEURE_S
        except OSError:
            age_sonde_h = None
        source_denses = str(args.sonde)

    tours = 0
    while True:
        tours += 1
        mesure = debit.lire()
        secondes_restantes = _secondes_restantes_aujourdhui()
        eta = calculer_eta(
            denses_acquis=denses_acquis, requis=int(args.requis),
            signaux_aujourdhui=0, seuil_par_jour=MIN_SIGNALS_PER_DAY,
            debit_par_heure=mesure["debit_par_heure"],
            aujourdhui_deja_dense=False,
            secondes_restantes_dans_la_journee=secondes_restantes)

        lignes = [
            "=" * 68,
            "  ETA DONNEES LABO — combien de temps encore collecter ?",
            "=" * 68,
            f"  journees UTC DENSES acquises : {denses_acquis} / {args.requis} requises",
            f"  seuil de densite             : {MIN_SIGNALS_PER_DAY} signaux evaluables/jour",
            f"  source des journees          : {source_denses}",
            ("  age de cette mesure          : "
             + (f"{age_sonde_h:.1f} h" if age_sonde_h is not None else "INCONNU")),
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
            f"  ETA                          : {duree_lisible(eta['heures'])}"
            f"   [{eta['statut']}]",
        ]
        if eta.get("motif"):
            lignes.append(f"  pourquoi                     : {eta['motif']}")
        if eta["statut"] in ("EN_COURS", "JOURNEE_EN_COURS_PERDUE"):
            lignes.append(
                f"  dont aujourd'hui             : "
                f"{duree_lisible(eta.get('heures_pour_finir_aujourdhui'))}"
                f"  puis {eta.get('journees_calendaires_ensuite')} journee(s) calendaire(s)")
        lignes.append("")
        lignes.append("  (l'ETA RECULE si le debit tombe : une journee trop pauvre ne compte pas)")
        if os.name == "nt":
            os.system("cls")      # noqa: S605 S607 - rafraichissement d'ecran, pas d'entree externe
        print("\n".join(lignes), flush=True)

        if args.une_fois or (args.tours and tours >= args.tours):
            return 0
        time.sleep(max(0.5, float(args.intervalle)))


if __name__ == "__main__":
    raise SystemExit(main())
