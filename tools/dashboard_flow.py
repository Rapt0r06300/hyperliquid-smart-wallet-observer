"""TABLEAU DE BORD FIGÉ DE FLO (Flo 26/07, AF-P6). 12 panneaux, mots TRÈS simples, Rich Live + Layout +
Progress, rafraîchi 2 à 4 fois/seconde. Les workers publient leur progression (l'horloge seule ne suffit pas).
Navigation 1-7 / S / Ctrl+C (msvcrt, sans intercepter Ctrl+C). Toute valeur absente affiche
« PAS ENCORE CALCULABLE — <raison> » : aucun faux zéro, aucun nombre décoratif. 0 réseau, 0 ordre.
"""
from __future__ import annotations

PANNEAUX = [
    "1. HYPERSMART — LABORATOIRE CONTINU", "2. CE QUE LE LOGICIEL FAIT MAINTENANT", "3. TRAVAIL RÉALISÉ",
    "4. COMMENT EST CRÉÉE LA COMBINAISON ACTUELLE", "5. RÉSULTATS DES IDÉES", "6. MEILLEURES PÉPITES POSSIBLES",
    "7. POURQUOI LES IDÉES SONT REJETÉES", "8. OUTILS UTILISÉS", "9. SIMULATION PAPER", "10. DONNÉES EN DIRECT",
    "11. ÉTAT DE L'ORDINATEUR", "12. EST-CE LE BON MOMENT POUR CTRL+C ?",
]

NAV = {"1": "general", "2": "donnees", "3": "idees", "4": "pepites", "5": "simulation", "6": "rejets",
       "7": "systeme", "s": "snapshot", "S": "snapshot"}


def touche_vers_vue(ch: str):
    """Mappe une touche vers une vue (None si non gérée). Ctrl+C n'est JAMAIS mappé (géré par le signal)."""
    return NAV.get(ch)


def _v(etat: dict, chemin, defaut_raison="donnée pas encore produite"):
    """Rend la valeur si présente et non None, sinon 'PAS ENCORE CALCULABLE — raison'."""
    cur = etat
    for k in (chemin if isinstance(chemin, (list, tuple)) else [chemin]):
        if isinstance(cur, dict) and k in cur:
            cur = cur[k]
        else:
            cur = None
            break
    if cur is None:
        return "PAS ENCORE CALCULABLE — %s" % defaut_raison
    return cur


def construire_panneaux(etat: dict) -> dict:
    """Construit les 12 panneaux (listes de lignes en mots simples) depuis l'état du run."""
    tot = etat.get("totaux", {})
    fait = etat.get("ce_que_je_fais", {})
    sim = etat.get("simulation", {})
    live = etat.get("donnees_live", {})
    sysx = etat.get("systeme", {})
    outils = etat.get("outils", {})
    ctrlc = etat.get("ctrl_c", {})
    d = etat.get("duree", {})
    P = {}
    P[PANNEAUX[0]] = [
        "Tout va bien : %s" % _v(etat, "sante", "santé pas encore évaluée"),
        "Durée : %sj %sh %sm %ss" % (d.get("jours", 0), d.get("heures", 0), d.get("minutes", 0), d.get("secondes", 0)),
        "Démarré : %s" % _v(etat, "demarrage_iso"),
        "Cycles terminés : %s" % _v(etat, "cycles_termines"),
        "Dernière sauvegarde : %s" % _v(etat, "dernier_checkpoint"),
        "Le labo continue jusqu'au Ctrl+C.",
    ]
    P[PANNEAUX[1]] = [
        "JE SUIS EN TRAIN DE : %s" % _v(fait, "je_fais", "aucune tâche annoncée"),
        "JE LE FAIS PARCE QUE : %s" % _v(fait, "parce_que"),
        "J'UTILISE : %s" % _v(fait, "j_utilise"),
        "J'AI TERMINÉ : %s sur %s (%s%%) · vitesse %s · ETA %s" % (
            _v(fait, "fait"), _v(fait, "total"), _v(fait, "pourcentage"), _v(fait, "vitesse"), _v(fait, "eta")),
        "ENSUITE JE VAIS : %s" % _v(fait, "ensuite"),
    ]
    P[PANNEAUX[2]] = [
        "Idées trouvées : %s" % _v(tot, "idees_trouvees"),
        "Combinaisons préparées : %s · uniques : %s" % (_v(tot, "combinaisons_preparees"), _v(tot, "uniques")),
        "Réellement testées : %s · évitées (déjà vues) : %s" % (_v(tot, "testees"), _v(tot, "evitees")),
        "Tests rapides : %s · replays précis : %s" % (tot.get("fast_screen", 0), tot.get("exact_replays", 0)),
        "Placebos : %s · stress frais : %s · stress latence : %s" % (
            _v(tot, "placebos"), _v(tot, "stress_frais"), _v(tot, "stress_latence")),
        "Forward : %s · file restante : %s · vitesse : %s tests/min" % (
            tot.get("forward_events", 0), _v(tot, "file_restante"), _v(tot, "vitesse_tests_min")),
    ]
    comb = etat.get("combinaison", {})
    P[PANNEAUX[3]] = [
        "Idée : %s" % _v(comb, "idee"), "Crypto : %s" % _v(comb, "coin"),
        "Achat/Vente : %s" % _v(comb, "sens"), "Horizon : %s" % _v(comb, "horizon"),
        "Seuil : %s · Régime : %s" % (_v(comb, "seuil"), _v(comb, "regime")),
        "Type d'entrée : %s · Frais : %s · Latence : %s · Notionnel : %s" % (
            _v(comb, "type_entree"), _v(comb, "frais"), _v(comb, "latence"), _v(comb, "notionnel")),
    ]
    res = etat.get("resultats_idees", {})
    P[PANNEAUX[4]] = [
        "Rejetées : %s · Manque de données : %s" % (_v(res, "rejetees"), _v(res, "manque_donnees")),
        "Premier test réussi : %s · Pépites possibles : %s" % (_v(res, "premier_ok"), _v(res, "pepites_possibles")),
        "À confirmer : %s · Positives en simulation : %s" % (_v(res, "a_confirmer"), _v(res, "positives_sim")),
        "Meilleure piste : %s" % _v(res, "meilleure"),
    ]
    pepites = etat.get("pepites", [])
    P[PANNEAUX[5]] = (["Aucune pépite possible pour l'instant (honnête)."] if not pepites else
                     ["• %s | net %s bps | ROI %s%% | live %s | %s" % (
                         p.get("explication", p.get("candidate_id")), p.get("net"), p.get("roi"),
                         p.get("duree_live"), p.get("statut")) for p in pepites[:8]])
    P[PANNEAUX[6]] = [
        "Perte dès le départ : %s · Coûts : %s · Hasard : %s" % (
            _v(res, "rej_perte"), _v(res, "rej_couts"), _v(res, "rej_hasard")),
        "Peu d'exemples : %s · Concentration : %s · Drawdown : %s" % (
            _v(res, "rej_peu"), _v(res, "rej_concentration"), _v(res, "rej_drawdown")),
        "Dernière idée rejetée : %s (avant coûts %s / coûts %s / net %s)" % (
            _v(res, "derniere_rejetee"), _v(res, "avant_couts"), _v(res, "couts"), _v(res, "net")),
    ]
    P[PANNEAUX[7]] = [
        "Disponibles : %s · Réellement utilisés : %s · Actifs : %s" % (
            _v(outils, "disponibles"), _v(outils, "utilises"), _v(outils, "actifs")),
        "Terminés : %s · En attente : %s · Indisponibles : %s" % (
            _v(outils, "termines"), _v(outils, "en_attente"), _v(outils, "indisponibles")),
    ] + ["  - %s" % l for l in (outils.get("detail") or [])[:8]]
    P[PANNEAUX[8]] = [
        "Capital initial : %s $ · Cash : %s $ · Valeur actuelle : %s $" % (
            _v(sim, "capital"), _v(sim, "cash"), _v(sim, "equity")),
        "PnL réalisé : %s $ · PnL latent : %s $ · PnL net : %s $" % (
            _v(sim, "pnl_realise"), _v(sim, "pnl_latent"), _v(sim, "pnl_net")),
        "ROI total : %s%% · ROI déployé : %s%% · Drawdown : %s $" % (
            _v(sim, "roi_total"), _v(sim, "roi_deploye"), _v(sim, "drawdown")),
        "Positions : %s · Frais : %s · Spread : %s · Slippage : %s · Funding : %s" % (
            _v(sim, "positions"), _v(sim, "frais"), _v(sim, "spread"), _v(sim, "slippage"), _v(sim, "funding")),
        "(résultats uniquement sur les nouvelles données)",
    ]
    P[PANNEAUX[9]] = [
        "Carnet : %s · Trades : %s · BBO : %s · Funding/OI : %s" % (
            _v(live, "carnet"), _v(live, "trades"), _v(live, "bbo"), _v(live, "funding")),
        "État : %s · Âge dernier événement : %s · Débit : %s" % (
            _v(live, "etat"), _v(live, "age_dernier"), _v(live, "debit")),
        "Backlog : %s · Gaps : %s · Rotations : %s · Doublons : %s" % (
            _v(live, "backlog"), _v(live, "gaps"), _v(live, "rotations"), _v(live, "doublons")),
        "Collecteurs : %s · Reconnexions : %s · Fichiers en croissance : %s" % (
            _v(live, "collecteurs"), _v(live, "reconnexions"), _v(live, "fichiers_croissance")),
    ]
    P[PANNEAUX[10]] = [
        "CPU : %s%% · RAM : %s%% · Disque : %s%%" % (_v(sysx, "cpu"), _v(sysx, "ram"), _v(sysx, "disque")),
        "Workers : %s · Collecteurs : %s · Tâches bloquées : %s" % (
            _v(sysx, "workers"), _v(sysx, "collecteurs"), _v(sysx, "bloquees")),
        "Redémarrages : %s · Erreurs : %s" % (_v(sysx, "redemarrages"), _v(sysx, "erreurs")),
    ]
    feu = ctrlc.get("feu", "🔴")
    P[PANNEAUX[11]] = [
        "%s %s" % (feu, _v(ctrlc, "message", "évaluation pas encore prête")),
        "Ce qui est terminé : %s" % _v(ctrlc, "termine"),
        "Ce qui manque : %s" % _v(ctrlc, "manque"),
        "Tests importants en cours : %s" % _v(ctrlc, "tests_en_cours"),
        "Durée de suivi des pépites : %s" % _v(ctrlc, "duree_suivi"),
        "Qualité du rapport si arrêt maintenant : %s" % _v(ctrlc, "qualite_rapport"),
        "Prochaine étape importante : %s (ETA %s)" % (_v(ctrlc, "prochaine"), _v(ctrlc, "eta_prochaine")),
        "Cette indication informe seulement : Ctrl+C n'est jamais bloqué.",
    ]
    return P


def rendre_texte(etat: dict, *, vue: str = "tout") -> str:
    """Rend le dashboard en TEXTE (pour tests/terminaux sans Rich). `vue` = 'tout' ou une des vues NAV."""
    P = construire_panneaux(etat)
    if vue in (None, "tout"):
        blocs = list(P.items())
    else:
        idx = {"general": [0, 1], "donnees": [9], "idees": [2, 3, 4], "pepites": [5], "simulation": [8],
               "rejets": [6], "systeme": [10], "snapshot": list(range(12))}.get(vue, list(range(12)))
        titres = [PANNEAUX[i] for i in idx]
        blocs = [(t, P[t]) for t in titres]
    out = []
    for titre, lignes in blocs:
        out.append("┌─ %s" % titre)
        out += ["│  %s" % l for l in lignes]
    out.append("[1]général [2]données [3]idées [4]pépites [5]simulation [6]rejets [7]système [S]snapshot  Ctrl+C=rapport")
    return "\n".join(out)


def rendre_rich(etat: dict):
    """Construit un Layout Rich (12 panneaux). Renvoie un renderable ; utilisé par la boucle Live."""
    try:
        from rich.panel import Panel
        from rich.columns import Columns
    except Exception:  # noqa: BLE001
        return rendre_texte(etat)
    P = construire_panneaux(etat)
    panels = [Panel("\n".join(str(x) for x in lignes), title=titre, expand=True) for titre, lignes in P.items()]
    return Columns(panels, equal=True, expand=True)


def lire_touche_non_bloquante():
    """Lit une touche sans bloquer (Windows via msvcrt), sans intercepter Ctrl+C. None si rien/indispo."""
    try:
        import msvcrt  # type: ignore
    except Exception:  # noqa: BLE001
        return None
    if msvcrt.kbhit():
        try:
            return msvcrt.getwch()
        except Exception:  # noqa: BLE001
            return None
    return None


__all__ = ["PANNEAUX", "NAV", "touche_vers_vue", "construire_panneaux", "rendre_texte", "rendre_rich",
           "lire_touche_non_bloquante"]
