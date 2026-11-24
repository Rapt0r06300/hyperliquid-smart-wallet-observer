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
from datetime import datetime, timedelta, timezone
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
    # 24/11/2026 : le ruban WS (`vault_fills_live`) ne bouge presque pas (0,0 ligne/min affiché) alors que le POLL
    # REST grossit de ~2,3 Mo/min -- c'est lui la collecte (le WS rate 16,6 % des fills que le poll capte).
    "runtime/data/vault_fills_poll.jsonl",
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
        # Une horloge murale peut avoir une résolution trop grossière sous Windows
        # et rendre deux lectures immédiates indistinguables. Pour un débit, seule
        # la durée écoulée compte : elle doit être monotone et haute résolution.
        maintenant = time.monotonic()
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
    p.add_argument("--intervalle", type=float, default=5.0,
                   help="secondes entre deux rafraichissements de l'ETA")
    p.add_argument("--tours", type=int, default=0,
                   help="nombre de rafraichissements (0 = sans fin, q pour quitter)")
    p.add_argument("--sonde", default=None,
                   help="rapport horloges explicite ; par défaut le plus récent est relu")
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
    tours = 0
    besoins: list[dict] = []
    while True:
        tours += 1
        if tours == 1 or tours % 12 == 0:              # les études changent rarement : relues ~1 fois par minute
            besoins = besoins_du_labo(racine)
        denses_acquis, source_denses, age_sonde_h = lire_sonde_denses(racine, args.sonde)
        mesure = debit.lire()
        secondes_restantes = _secondes_restantes_aujourdhui()
        eta = calculer_eta(
            denses_acquis=denses_acquis, requis=int(args.requis),
            signaux_aujourdhui=0, seuil_par_jour=MIN_SIGNALS_PER_DAY,
            debit_par_heure=mesure["debit_par_heure"],
            aujourdhui_deja_dense=False,
            secondes_restantes_dans_la_journee=secondes_restantes)

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
        lignes = [
            "=" * 68,
            "  ETA DONNEES LABO — combien de temps encore collecter ?",
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
            f"  plancher du moteur           : {duree_lisible(eta['heures'])}"
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
        lignes.append("  (dates des etudes : jours REQUIS moins jours MESURES a la date de l'etude ; relancer")
        lignes.append("   LANCER_LAB_QUANT_COPY_VAULT.cmd copiabilite pour les remettre a jour)")
        if not args.une_fois:
            lignes.append("  q ou Ctrl+C pour quitter")
        if os.name == "nt":
            os.system("cls")      # noqa: S605 S607 - rafraichissement d'ecran, pas d'entree externe
        print("\n".join(lignes), flush=True)

        if args.une_fois or (args.tours and tours >= args.tours):
            return 0
        if _quitter_demande(max(0.5, float(args.intervalle))):
            return 0


if __name__ == "__main__":
    raise SystemExit(main())
