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

NAV = {"0": "compact", "c": "compact", "C": "compact",
       "1": "general", "2": "donnees", "3": "idees", "4": "pepites", "5": "simulation", "6": "rejets",
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
    """Rend le dashboard en TEXTE (pour tests/terminaux sans Rich). `vue` = 'compact' (défaut visuel), 'tout',
    ou une des vues NAV."""
    if vue == "compact":                                     # PF-6 : vue principale compacte (repli texte)
        out = ["┌─ HYPERSMART — RECHERCHE CONTINUE"]
        for label, valeur in construire_vue_compacte(etat):
            out.append("│  %-22s %s" % (label + " :", valeur))
        out.append("[1-7] détails · [S] snapshot · Ctrl+C = rapport final")
        return "\n".join(out)
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


def _premiers_resultats_absents(etat: dict) -> bool:
    """Vrai tant qu'AUCUN premier résultat n'existe (on affiche alors une seule ligne d'attente au lieu de
    dizaines de « PAS ENCORE CALCULABLE »)."""
    tot = etat.get("totaux", {})
    res = etat.get("resultats_idees", {})
    cles = [tot.get("idees_trouvees"), tot.get("testees"), tot.get("forward_events"),
            res.get("pepites_possibles"), (etat.get("simulation") or {}).get("equity")]
    return not any(bool(x) for x in cles)


def _barre(pct) -> str:
    """Barre de progression lisible, stable et assez précise pour les longs calculs."""
    try:
        p = max(0.0, min(100.0, float(pct)))
    except (TypeError, ValueError):
        return "…"
    largeur = 30
    n = int(round(p * largeur / 100.0))
    return "[%s%s] %7.3f%%" % ("#" * n, "·" * (largeur - n), p)


def _fmt_nombre(v) -> str:
    try:
        return f"{int(v):,}".replace(",", " ")
    except (TypeError, ValueError):
        return "…"


def _fmt_duree(secondes) -> str:
    try:
        s = max(0, int(float(secondes)))
    except (TypeError, ValueError):
        return "…"
    if s < 60:
        return "%ds" % s
    if s < 3600:
        return "%dm %02ds" % (s // 60, s % 60)
    return "%dh %02dm" % (s // 3600, (s % 3600) // 60)


def construire_vue_compacte(etat: dict) -> list:
    """VUE PRINCIPALE COMPACTE (PF-6) : tient sur un écran. Rend une liste de (label, valeur)."""
    d = etat.get("duree", {})
    fait = etat.get("ce_que_je_fais", {})
    tot = etat.get("totaux", {})
    res = etat.get("resultats_idees", {})
    sim = etat.get("simulation", {})
    live = etat.get("donnees_live", {})
    fin = etat.get("finalisation") or {}
    supervision = etat.get("supervision") or {}
    ressources = etat.get("resource_policy") or {}
    duree = "%sj %sh %sm %ss" % (d.get("jours", 0), d.get("heures", 0), d.get("minutes", 0), d.get("secondes", 0))
    etat_donnees = "%s · débit %s · collecteur %s · dernier événement %s" % (
        live.get("etat_collecteur") or etat.get("sante") or "démarrage…",
        live.get("debit", "…"),
        _fmt_duree((live.get("heartbeat_age_ms") or 0) / 1000.0),
        live.get("age_dernier", "…"),
    )
    prog = "%s · %s/%s · %s étape/s · ETA %s" % (
        _barre(fait.get("pourcentage")), fait.get("fait", "…"), fait.get("total", "…"),
        fait.get("vitesse", "…"), _fmt_duree(fait.get("eta")))
    eta_detail = "%s · confiance %s%% · débit projeté %s/s · compteur %s" % (
        fait.get("eta_source") or "projection initiale",
        fait.get("eta_confiance_pct", 0),
        fait.get("debit_projection", "…"),
        fait.get("eta_mode") or "global",
    )
    politique_ressources = (
        "%s permanent · jamais Idle · aucune pause · Salad %s · "
        "%s worker(s) · lot %s source(s) / %s Mio"
        % (
            ressources.get("priority") or "BELOW_NORMAL",
            "actif" if ressources.get("salad_active") else "inactif",
            ressources.get("max_workers", "…"),
            ressources.get("max_sources_per_bootstrap", "…"),
            ressources.get("max_bootstrap_megabytes", "…"),
        )
    )
    sous_fait = fait.get("sous_fait")
    sous_total = fait.get("sous_total")
    if sous_fait is not None and sous_total:
        progression_sous_phase = "%s/%s sous-étapes · %s" % (
            _fmt_nombre(sous_fait),
            _fmt_nombre(sous_total),
            fait.get("detail") or "calcul",
        )
    else:
        progression_sous_phase = "aucune sous-phase mesurable annoncée"
    traite = fait.get("traite")
    traite_total = fait.get("traite_total")
    if traite is not None and traite_total:
        pct_interne = 100.0 * float(traite) / max(1.0, float(traite_total))
        progression_interne = "%s · %s/%s %s · %s/s" % (
            _barre(pct_interne),
            _fmt_nombre(traite),
            _fmt_nombre(traite_total),
            fait.get("unite") or "éléments",
            fait.get("debit_interne") or "…",
        )
    else:
        progression_interne = "initialisation de la sous-tâche…"
    attente = _premiers_resultats_absents(etat)
    def _ou(v):
        return "En attente des premiers résultats…" if attente else (v if v not in (None, "") else "…")
    lignes = [
        ("État des données", etat_donnees),
        ("Durée", duree),
        ("Travail actuel", fait.get("je_fais", "…")),
        ("Détail exact", fait.get("detail") or "préparation de l'étape"),
        ("Pourquoi", fait.get("parce_que", "…")),
        ("Progression", prog),
        ("Projection ETA", eta_detail),
        ("Sous-phase", progression_sous_phase),
        ("Progression interne", progression_interne),
        ("Dernière activité", "compteur il y a %s · heartbeat il y a %s · calcul actif depuis %s" % (
            _fmt_duree(fait.get("age_compteur_s", fait.get("age_maj_s"))),
            _fmt_duree(fait.get("age_heartbeat_s")),
            _fmt_duree(fait.get("duree_progression_s")))),
        ("Supervision UI", "%s · image %s · rafraîchissement %sms" % (
            supervision.get("etat_ui", "DÉMARRAGE"),
            supervision.get("ui_tick", "…"),
            supervision.get("intervalle_ms", "…"),
        )),
        ("État moteur", "%s · dernière progression %s · erreurs UI %s" % (
            supervision.get("etat_moteur", "DÉMARRAGE"),
            _fmt_duree(supervision.get("age_progression_s")),
            supervision.get("erreurs_rendu", 0),
        )),
        ("Ressources", politique_ressources),
        ("Événements reçus", _ou(tot.get("events_utilises") or tot.get("forward_events"))),
        ("Combinaisons testées", _ou(tot.get("testees"))),
        ("Idées trouvées", _ou(tot.get("idees_trouvees"))),
        ("Pépites possibles", _ou(res.get("pepites_possibles"))),
        ("PnL / ROI paper", _ou(None if not sim else "%s $ · %s%%" % (sim.get("pnl_net", sim.get("pnl_realise", "…")), sim.get("roi_total", "…")))),
        ("Prochaine tâche", fait.get("ensuite", "…")),
        ("Ctrl+C", "= rapport final (arrêt propre)"),
    ]
    if fin:
        lignes[2:2] = [
            ("Finalisation", "%s · %s" % (_barre(fin.get("pourcentage")), fin.get("etape") or fin.get("statut"))),
            ("Rapport", fin.get("rapport") or "création du chemin en cours"),
        ]
    return lignes


def rendre_rich(etat: dict, *, vue: str = "compact"):
    """Console plein écran stable : progression, métriques, supervision et journal.

    La géométrie reste fixe entre deux rafraîchissements afin que le terminal ne
    saute pas pendant les calculs longs. Les vues détaillées 1-7 restent
    accessibles sans modifier le moteur.
    """
    try:
        from rich.layout import Layout
        from rich.panel import Panel
        from rich.table import Table
        from rich.text import Text
    except Exception:  # noqa: BLE001
        return rendre_texte(etat, vue=("tout" if vue != "compact" else "compact"))
    if vue and vue != "compact":                             # vues détaillées (12 panneaux) en arrière-plan
        from rich.columns import Columns
        P = construire_panneaux(etat)
        return Columns([Panel("\n".join(str(x) for x in l), title=t, expand=True) for t, l in P.items()],
                       equal=True, expand=True)

    rows = dict(construire_vue_compacte(etat))
    supervision = etat.get("supervision") or {}
    fait = etat.get("ce_que_je_fais") or {}
    layout = Layout(name="root")
    layout.split_column(
        Layout(name="header", size=3),
        Layout(name="progression", size=12),
        Layout(name="mesures", size=10),
        Layout(name="journal", size=8),
        Layout(name="footer", size=3),
    )

    header = Table.grid(expand=True)
    header.add_column(ratio=3)
    header.add_column(justify="right", ratio=2)
    header.add_row(
        Text("HYPERSMART · RECHERCHE CONTINUE", style="bold cyan"),
        Text(
            "%s · cycle %s · %s · %s" % (
                supervision.get("etat_ui", "DÉMARRAGE"),
                etat.get("cycle_actuel", "…"),
                etat.get("phase") or etat.get("etat") or "…",
                supervision.get("heure") or "…",
            ),
            style="bold green" if supervision.get("etat_ui") == "ACTIF" else "bold yellow",
        ),
    )
    layout["header"].update(Panel(header, border_style="cyan"))

    progress = Table.grid(padding=(0, 1), expand=True)
    progress.add_column(width=22, style="bold cyan", no_wrap=True)
    progress.add_column(ratio=1)
    progress.add_row("Travail actuel", Text(str(rows.get("Travail actuel", "…"))))
    progress.add_row("Détail exact", Text(str(rows.get("Détail exact", "…"))))
    progress.add_row("Pourquoi", Text(str(rows.get("Pourquoi", "…"))))
    progress.add_row("Progression globale", Text(str(rows.get("Progression", "…")), style="bold green"))
    progress.add_row("Projection ETA", Text(str(rows.get("Projection ETA", "…")), style="yellow"))
    progress.add_row("Sous-phase", Text(str(rows.get("Sous-phase", "…"))))
    progress.add_row("Boucle interne", Text(str(rows.get("Progression interne", "…")), style="green"))
    progress.add_row("Ensuite", Text(str(rows.get("Prochaine tâche", "…"))))
    layout["progression"].update(Panel(progress, title="Calcul en cours", border_style="blue"))

    layout["mesures"].split_row(Layout(name="direct"), Layout(name="health"))
    direct = Table.grid(padding=(0, 1), expand=True)
    direct.add_column(width=22, style="cyan", no_wrap=True)
    direct.add_column(ratio=1)
    for label in (
        "Événements reçus",
        "Combinaisons testées",
        "Idées trouvées",
        "Pépites possibles",
        "PnL / ROI paper",
    ):
        direct.add_row(label, Text(str(rows.get(label, "…"))))
    layout["direct"].update(Panel(direct, title="Résultats réels", border_style="green"))

    health = Table.grid(padding=(0, 1), expand=True)
    health.add_column(width=20, style="cyan", no_wrap=True)
    health.add_column(ratio=1)
    health.add_row("Données", Text(str(rows.get("État des données", "…"))))
    health.add_row("Moteur", Text(str(rows.get("État moteur", "…"))))
    health.add_row("Interface", Text(str(rows.get("Supervision UI", "…"))))
    health.add_row("Ressources", Text(str(rows.get("Ressources", "…"))))
    health.add_row("Activité", Text(str(rows.get("Dernière activité", "…"))))
    health.add_row("Durée", Text(str(rows.get("Durée", "…"))))
    layout["health"].update(Panel(health, title="Santé 24 h / 24", border_style="yellow"))

    journal_table = Table.grid(padding=(0, 1), expand=True)
    journal_table.add_column(width=10, style="dim cyan", no_wrap=True)
    journal_table.add_column(width=10, style="bold", no_wrap=True)
    journal_table.add_column(ratio=1)
    journal = list(supervision.get("journal") or [])[-5:]
    if journal:
        for item in journal:
            journal_table.add_row(
                str(item.get("heure") or "…"),
                str(item.get("niveau") or "INFO"),
                Text(str(item.get("message") or "…")),
            )
    else:
        journal_table.add_row("…", "ATTENTE", "Le moteur prépare sa première activité.")
    layout["journal"].update(Panel(journal_table, title="Journal des dernières actions", border_style="magenta"))

    footer = Table.grid(expand=True)
    footer.add_column(ratio=3)
    footer.add_column(justify="right", ratio=2)
    footer.add_row(
        Text("[1-7] détails  ·  [0] accueil  ·  [S] snapshot", style="cyan"),
        Text("Ctrl+C = arrêt propre + rapport final", style="bold yellow"),
    )
    layout["footer"].update(Panel(footer, border_style="cyan"))
    return layout


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


__all__ = ["PANNEAUX", "NAV", "touche_vers_vue", "construire_panneaux", "construire_vue_compacte",
           "rendre_texte", "rendre_rich", "lire_touche_non_bloquante"]
