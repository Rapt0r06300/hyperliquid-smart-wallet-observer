"""LES PIERRES TOMBALES DE `risk/` — T3b (2026-07-12).

POURQUOI CE FICHIER EXISTE
--------------------------
L'audit de cablage (T3) a montre que **21 garde-fous de `risk/` avaient des tests verts et
n'etaient appeles par AUCUN chemin de production**. La suite etait verte. Le kill-switch etait
"teste". Et rien ne l'appelait.

La regle posee par Flo est sans ambiguite :

    « Pour chacun : BRANCHER (avec un test qui prouve l'appel) ou ENTERRER. Rien dans l'entre-deux. »

Ce module EST l'enterrement. Il ne se contente pas de documenter : le test
`tests/test_risk_guards_no_limbo.py` lit ce registre et **echoue** si :

  * un module de `risk/` n'est NI atteignable depuis la production NI dans ce registre
    -> c'est un LIMBE : personne ne sait s'il compte. Interdit.
  * un module ENTERRE redevient importe par du code de production
    -> resurrection accidentelle. Interdit sans decision explicite.

Autrement dit : on ne peut plus AJOUTER un garde-fou de risque sans decider, par ecrit, s'il
a le pouvoir ou s'il est mort. Le 22e ne pourra plus se cacher.

CE QUE « ENTERRE » VEUT DIRE (et ne veut pas dire)
-------------------------------------------------
Le fichier reste sur le disque, sous git, recuperable. « Enterre » veut dire :
**aucun chemin de production ne doit l'appeler, et c'est desormais une regle testee.**
Le code n'est pas efface a la hache (CLAUDE.md : « ne rien supprimer brutalement ») ; il est
declare mort, et la resurrection accidentelle est bloquee.

LA GRILLE DE DECISION (appliquee aux 21, sans exception)
--------------------------------------------------------
Un garde-fou est BRANCHE seulement si les TROIS conditions tiennent :

  1. il protege d'une panne **structurellement possible sur le chemin paper vivant**
     (pas d'un risque d'execution reelle, qui ne peut PAS survenir : il n'y a aucun ordre) ;
  2. **aucun garde-fou vivant ne couvre deja** la meme chose (pas de doublon) ;
  3. le point de decision vivant peut **vraiment l'alimenter** (pas un garde-fou affame).

Sinon : ENTERRE, avec la raison ecrite ici.

Le troisieme critere est le plus important, et le plus ignore : un garde-fou nourri de `None`
ne protege de rien, il rassure. C'est pire que son absence.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Tombe:
    module: str          # nom court, ex. "kill_switch"
    motif: str           # DOUBLON | IMPOSSIBLE_EN_PAPER | AFFAME | STRATEGIE_PAS_GARDE_FOU
                         # | REALISME_PAS_GARDE_FOU
    remplace_par: str    # ce qui fait le travail a sa place, EN VIE (ou la tache qui le porte)
    preuve: str          # ou verifier, en une ligne
    paquet: str = "risk"  # "risk" | "paper_trading" | "exits" -- T3c a etendu l'invariant


# --- ENTERRES ---------------------------------------------------------------------------
#
# 19 modules. Chaque ligne est une decision, pas une opinion.

TOMBES: tuple[Tombe, ...] = (
    # ---- la pile V9, remplacee par la pile V26 (qui, elle, est VIVANTE) ----
    Tombe("kill_switch", "DOUBLON",
          "risk.portfolio_drawdown_kill_switch (vivant) + graded_halt RED + le controle inline "
          "de risk_engine_v3 sur le flag de settings",
          "IMPROVE-23 le disait 'teste' : il l'etait. Personne ne l'appelait."),
    Tombe("circuit_breaker", "DOUBLON",
          "risk.graded_halt (machine a etats GREEN/AMBER/RED, appelee par v26_entry_vetos "
          "et v26_exit_pipeline)",
          "docstring de circuit_breaker : 'S7 — V9'. graded_halt est le successeur V26."),
    Tombe("trade_circuit_breaker", "DOUBLON",
          "risk.graded_halt + risk.protections_v26 (REASON_DD, drawdown fenetre)",
          "3e implementation du meme concept (avec risk.circuit_breaker et copying.circuit_breaker)."),
    Tombe("loss_halts", "DOUBLON",
          "risk.graded_halt + risk.protections_v26 + risk.equity_hard_stop_loss (tous vivants)",
          "docstring : 'S7 — V9'. Les halts cumulatifs sont dans protections_v26."),
    Tombe("entry_guard", "DOUBLON",
          "signals.v26_entry_vetos.apply_v26_entry_vetos (LE chemin de veto d'entree vivant)",
          "entry_guard se decrit lui-meme comme un 'S7 wiring helper' qui COMPOSE "
          "circuit_breaker + exec_gates : ses trois dependances sont mortes."),
    Tombe("exec_gates", "DOUBLON",
          "signals.v26_entry_vetos (fraicheur, liquidite, edge) + risk.microstructure_guard",
          "exec_gates : 'STALE_THRESHOLD_SEC = 5' — la fraicheur est deja gardee, en vie."),

    # ---- doublons de garde-fous vivants ----
    Tombe("correlated_exposure", "DOUBLON",
          "risk.portfolio_correlation (BRANCHE par T3b — meme concept, API de refus deja prete)",
          "Deux modules morts faisaient la meme chose. On en garde UN, et on le branche."),
    Tombe("portfolio_risk", "DOUBLON",
          "risk.directional_exposure (caps NET + par coin, vivant depuis le 11/07)",
          "gross_net_exposure/exposure_within_caps = doublon. Son `data_anomaly` (saut de prix) "
          "est une BONNE idee mais AFFAMEE : le point de decision n'a pas de couple "
          "(prix precedent, prix nouveau). Le manque est le FLUX, pas le garde-fou -> tache dediee."),
    Tombe("position_sizing", "DOUBLON",
          "risk.adaptive_sizing / risk.kelly_sizer / risk.proportional_paper_sizer (vivants)",
          "clamp_paper_size() est un one-liner deja fait ailleurs."),
    Tombe("sizing_v2", "DOUBLON",
          "risk.adaptive_sizing + risk.kelly_leader_book ; son cap de correlation est repris "
          "par portfolio_correlation (BRANCHE)",
          "R10 — 'sizing ∝ edge x confiance + cap correle' : les deux moities existent en vie."),
    Tombe("trade_floor", "DOUBLON",
          "HYPERSMART_MIN_PAPER_NOTIONAL_USDT (fusion_persistent_adapter:871) + le plancher "
          "d'edge net (EXPECTED_NET_EDGE_TOO_SMALL_AFTER_COSTS)",
          "notionnel minimum ET edge de breakeven : les deux sont deja appliques, en vie."),
    Tombe("slippage_model", "DOUBLON",
          "les couts LIVE issus du carnet L2 reel (live_costs_for, P2-2)",
          "DANGER SI RESSUSCITE : un slippage CONSTANT est exactement le bug que P2-2 a corrige. "
          "Le rebrancher serait une REGRESSION, pas une protection."),
    Tombe("latency_model", "DOUBLON",
          "edge.signal_decay.decay_edge + les gates de fraicheur du signal (vivants)",
          "Voir aussi Z1 (zone morte) : la courbe edge/horizon est PLATE, 500 ms = -3,74 bps. "
          "Penaliser la latence ne rapporte rien : ce n'est pas la que le PnL se perd."),
    Tombe("atr_trailing_stop", "DOUBLON",
          "paper_trading.sltp_runtime (trailing vivant, appele par ui/routes.py:2398)",
          "sltp_runtime EST le moteur de sortie vivant. atr_trailing_stop est un 2e trailing."),
    Tombe("market_manipulation_flags", "DOUBLON",
          "risk.microstructure_guard (spoofing / OBI, appele par ui/routes.py:1981) + "
          "risk.abnormal_spread_detector",
          "La qualite de marche a l'entree est deja gardee, sur le VRAI carnet."),

    # ---- impossibles en paper : il n'existe AUCUN ordre reel ----
    Tombe("duplicate_order_guard", "IMPOSSIBLE_EN_PAPER",
          "rien — et c'est correct : aucun ordre reel n'est jamais emis",
          "Garde-fou de deduplication d'ID d'ordre broker. Il n'y a pas de broker."),
    Tombe("partial_fill_pair_guard", "IMPOSSIBLE_EN_PAPER",
          "funding.funding_carry_economics (verrou FUNDING_LEG_UNHEDGED_PRICE_RISK_DOMINATES, "
          "vivant depuis le 11/07) — le risque de jambe NUE est deja verrouille, autrement",
          "Aucune jambe reelle n'est envoyee. Si Q2 (arbitrage a jambes reelles) aboutit un jour, "
          "cette tombe devra etre reouverte EXPLICITEMENT."),
    Tombe("reconciliation_guard", "IMPOSSIBLE_EN_PAPER",
          "IMPROVE-19 (reconciliation PnL sur le ledger, vivante)",
          "Le module est un stub d'UNE ligne : reconciliation_ok(is_uncertain). "
          "Il n'y a aucun etat broker a reconcilier."),

    # ---- ce n'est pas un garde-fou, c'est une strategie ----
    Tombe("scale_out", "STRATEGIE_PAS_GARDE_FOU",
          "paper_trading.sltp_runtime pour le TP/SL ; l'idee de sortie par paliers vit dans "
          "la tache H-179 (table ROI par paliers)",
          "Prise de profit partielle = choix de strategie. Un garde-fou REFUSE ; il n'optimise pas."),

    # ---- LES 4 QUE JE N'AVAIS MEME PAS VUS -------------------------------------------------
    # Mon inventaire disait « 21 ». Il en manquait 4 : mon grep etait tronque (head_limit).
    # C'est le test `test_aucun_garde_fou_de_risk_ne_reste_dans_l_entre_deux` qui les a
    # trouves, pas moi. C'est precisement pour ca qu'un INVARIANT vaut mieux qu'un inventaire :
    # un inventaire se fait une fois et se trompe ; un invariant tient a chaque execution.
    Tombe("advanced_risk_manager", "DOUBLON",
          "la pile V26 vivante : risk.graded_halt (halt PnL) + risk.protections_v26 + "
          "risk.adaptive_filter (regime) + risk.microstructure_guard",
          "Manager composite d'epoque V9 (VolatilityRegime, RiskVeto, DailyPnLState...). "
          "Chacune de ses couches a un successeur V26, en vie et appele."),
    Tombe("liquidity_guard", "DOUBLON",
          "risk.microstructure_guard (profondeur du VRAI carnet) + le veto de liquidite V26",
          "liquidity_ok(depth, min_depth) : un one-liner. La liquidite est gardee sur le carnet reel."),
    Tombe("slippage_guard", "DOUBLON",
          "les couts LIVE issus du carnet L2 (live_costs_for, P2-2)",
          "slippage_ok(est_bps, max_bps) : un one-liner qui compare a un slippage ESTIME. "
          "Le slippage est desormais MESURE sur le carnet, pas estime."),
    # 🚩 REECRITE le 13/07 (#130). L'ancien texte citait de la PROSE : « signal_age,
    # CURRENT_MID_REQUIRED ». Des noms de CHAMPS et de constantes -- rien qu'une machine puisse
    # verifier. Or une tombe qui cite un remplacant invérifiable ne vaut pas mieux qu'une tombe
    # qui ne cite personne : dans les deux cas, on ne peut pas prouver que le travail est fait.
    # On cite donc desormais les MODULES qui REFUSENT vraiment un signal perime.
    Tombe("stale_data_guard", "DOUBLON",
          "risk.exec_gates (STALE_THRESHOLD) + signals.v26_entry_vetos + "
          "signals.fill_admission (R_STALE_SIGNAL) + signals.copy_decision (STALE_SIGNAL)",
          "data_fresh(age_ms, max_ms) : un one-liner. La fraicheur est LE gate le plus applique "
          "du projet ; ce module n'y participait pas."),

    # ======================================================================================
    # T3c (2026-07-12) — LE CHEMIN DES SORTIES : `paper_trading/` et `exits/`
    #
    # C'est le chemin ou 30 % de la perte de -64 $ a ete faite (structure de sortie).
    # Le moteur de sortie VIVANT est `paper_trading/sltp_runtime`, appele par
    # ui/routes.py:2398 (via vol_adjusted_barriers) et ui/status_routes.py:416.
    # Tout ce qui suit est un CONCURRENT mort de ce moteur, ou un modele de realisme.
    # ======================================================================================

    # ---- les concurrents morts du moteur de sortie vivant ----
    Tombe("take_profit_stop_loss_local", "DOUBLON",
          "paper_trading.sltp_runtime (LE moteur de sortie vivant)",
          "evaluate_take_profit_stop_loss() : un 2e TP/SL. Un seul doit avoir le pouvoir.",
          paquet="paper_trading"),
    Tombe("trailing_stop_local", "DOUBLON",
          "paper_trading.sltp_runtime (trailing vivant : HYPERSMART_SLTP_TRAILING_BPS=45)",
          "update_trailing_stop() : un 2e trailing. Doublon de risk.atr_trailing_stop, deja enterre.",
          paquet="paper_trading"),
    Tombe("exit_engine", "DOUBLON",
          "paper_trading.sltp_runtime + paper_trading.v26_exit_pipeline (vivants)",
          "Importe UNIQUEMENT par copying.viral_bot_engine et integration.leader_pipeline -- "
          "MORTS tous les deux. Un moteur de sortie appele par deux morts est mort.",
          paquet="exits"),
    Tombe("exit_policy", "DOUBLON",
          "paper_trading.sltp_runtime (TP/SL/trailing/timeout, tout en un, vivant)",
          "Compose exits.time_stop + exits.trailing_stop : la meme politique, en double.",
          paquet="exits"),
    Tombe("exit_policy_runtime", "DOUBLON",
          "paper_trading.sltp_runtime + v26_exit_pipeline",
          "Le runtime de la politique morte ci-dessus. Mort par construction.",
          paquet="exits"),

    # ---- doublons de l'etat vivant ----
    Tombe("position_tracking", "DOUBLON",
          "l'etat vivant : state.simulation_virtual_positions + paper_trading.paper_engine",
          "PaperPositionTracker (taille + prix moyen par coin/side) : le runtime tient deja ce livre. "
          "DEUX livres de positions = deux verites possibles. Interdit.",
          paquet="paper_trading"),
    Tombe("journal", "DOUBLON",
          "simulation.paper_ledger + paper_trading.paper_engine "
          "(LE ledger : source de verite unique du PnL -- CLAUDE.md)",
          "« append-only record of paper trades ». C'est la definition du ledger. "
          "Un 2e journal, c'est un 2e PnL possible. La regle du projet l'interdit.",
          paquet="paper_trading"),

    # ---- pas des garde-fous : des modeles de REALISME (ils changeraient le PnL) ----
    Tombe("fill_outcomes", "REALISME_PAS_GARDE_FOU",
          "personne aujourd'hui -- et c'est un MANQUE reconnu, porte par une tache dediee",
          "resolve_fill() modelise PARTIAL/MISSED fills. Le brancher rendrait le PnL plus "
          "PESSIMISTE (donc plus honnete) : ce n'est pas un refus, c'est un changement de "
          "simulateur. Ca se MESURE avant de se decider. Voir aussi paper/partial_fill_model "
          "et paper/rejection_model, morts de la meme facon (H-91 : le rejet d'ordre).",
          paquet="paper_trading"),
    Tombe("order_types", "REALISME_PAS_GARDE_FOU",
          "personne -- l'idee POST-ONLY/`alo` est portee par la tache H-135",
          "MARKET/LIMIT/POST_ONLY + MAE/MFE + time-stop. Modele d'execution, pas garde-fou.",
          paquet="paper_trading"),

    # ---- doublon deja couvert, en vie, par la config ----
    Tombe("max_chase_guard", "DOUBLON",
          "signals.v26_entry_vetos.apply_v26_entry_vetos : le cap de DEGRADATION DE COPIE y est "
          "mesure ET plafonne (copy_degradation_bps, `degr<=13` dans la config)",
          "chase_bps(leader_entry, prix_courant) = exactement la degradation de copie, "
          "deja mesuree ET plafonnee sur le chemin vivant (apply_v26_entry_vetos).",
          paquet="paper_trading"),

    # =====================================================================================
    # 🚩 LES 7 QUE MON INVENTAIRE AVAIT RATES -- trouves par le TEST, pas par moi.
    #
    # Exactement comme les 4 de T3b (advanced_risk_manager, liquidity_guard, slippage_guard,
    # stale_data_guard). Deuxieme fois dans la meme journee. La lecon tient toujours :
    #   UN INVENTAIRE SE FAIT UNE FOIS ET SE TROMPE. UN INVARIANT SE VERIFIE A CHAQUE EXECUTION.
    # =====================================================================================

    Tombe("liquidity_route_simulator", "DOUBLON",
          "paper_trading.exec_model.simulate_depth_execution (qu'il ne fait qu'ENVELOPPER)",
          "Le module APPELLE simulate_depth_execution et rehabille son resultat. "
          "Zero logique propre. Une enveloppe morte autour d'un moteur vivant.",
          paquet="paper_trading"),
    Tombe("can_buy_amount_simulator", "DOUBLON",
          "exec_model.simulate_depth_execution + microstructure_guard (profondeur du VRAI carnet)",
          "Somme le notionnel disponible jusqu'a un prix limite. La profondeur executable est "
          "deja lue sur le carnet L2 reel depuis P2-2 (live_costs_for). Rebrancher une 2e "
          "source de profondeur, c'est rouvrir la porte des constantes.",
          paquet="paper_trading"),
    Tombe("hedge_reconciliation", "IMPOSSIBLE_EN_PAPER",
          "funding_carry_economics (le verrou de jambe NUE, 11/07) -- et il n'y a AUCUN ordre reel",
          "Mesure le skew entre 2 jambes de couverture. En paper, une jambe ne peut pas "
          "'echouer a passer' : il n'y a pas d'exchange. Le risque reel du carry (jambe nue, "
          "liquidation de la jambe perp) est deja porte par funding_carry_economics et T2b. "
          "⚠️ Si Q2 (arbitrage a jambes REELLES) aboutit, cette tombe se rouvre EXPLICITEMENT.",
          paquet="paper_trading"),

    # ---- exits/ : quatre STUBS D'UNE LIGNE, tous doubles par sltp_runtime ----
    #
    # Ce sont litteralement des fonctions d'une ligne. Elles ont l'air de garde-fous ; ce sont
    # des fragments. Le moteur de sortie VIVANT (paper_trading/sltp_runtime, appele par
    # ui/routes.py:2398 via vol_adjusted_barriers) fait deja les quatre, avec l'etat, le
    # ledger, et les frais.
    Tombe("trailing_stop", "DOUBLON",
          "sltp_runtime (HYPERSMART_SLTP_TRAILING_BPS + TRAILING_ACTIVATION_BPS)",
          "Une ligne : best_price * (1 -/+ bps/10000). Le trailing vivant a l'ETAT (le plus haut "
          "atteint), l'activation, et le breakeven buffer. Ce stub n'a rien de tout ca.",
          paquet="exits"),
    Tombe("time_stop", "DOUBLON",
          "sltp_runtime (HYPERSMART_SLTP_POSITION_TIMEOUT_MS)",
          "Une ligne : age_ms >= max_hold_ms. Le timeout vivant est deja dans le moteur de sortie.",
          paquet="exits"),
    Tombe("partial_take_profit", "STRATEGIE_PAS_GARDE_FOU",
          "personne -- l'idee vit dans H-179 (table ROI par paliers)",
          "size * fraction. Prendre un profit PARTIEL est un choix de STRATEGIE : ca optimise, "
          "ca ne refuse rien. Meme verdict que risk/scale_out (T3b). Un garde-fou dit NON ; "
          "il ne dit pas 'un peu'.",
          paquet="exits"),
    Tombe("leader_exit_monitor", "DOUBLON",
          "copy_wallet.wallet_mirror_runtime (lifecycle OPEN/ADD/REDUCE/CLOSE du leader)",
          "Une ligne : abs(current) < abs(previous). La detection REDUCE/CLOSE du leader est "
          "deja faite, avec l'etat et la deduplication, sur le chemin de copie vivant.",
          paquet="exits"),
)


# --- BRANCHES PAR T3b -------------------------------------------------------------------
#
# Deux, et seulement deux, passent la grille des 3 criteres.

BRANCHES: tuple[str, ...] = (
    # 1) La panne EXACTE qu'on a observee. Le module le dit lui-meme, dans sa 1re ligne :
    #    « 7 positions LONG sur des alts correles != 7 paris : c'est UN gros pari deguise. »
    #    Nos 19 ouvertures SHORT sur 21 en sont la version realisee. `directional_exposure`
    #    (vivant) plafonne le NET total et le par-COIN, mais traite BTC-long et ETH-long comme
    #    deux paris independants. Ils ne le sont pas.
    "portfolio_correlation",

    # 2) Anti-surtrading. `max_concurrent` est deja vivant (HYPERSMART_MAX_OPEN_POSITIONS=12) ;
    #    le nombre de trades/jour et le verrou de gain journalier, NON. Le firehose V27 est
    #    concu pour maximiser les signaux : le surtrading est structurellement possible.
    #    HONNETETE : a nos volumes actuels (21 trades sur tout un run), ce plafond NE MORD PAS.
    #    C'est un disjoncteur : il ne sert a rien jusqu'au jour ou il sert.
    "trade_budget",

    # 3) T3c — LE GARDE-FOU QUI AURAIT EMPECHE LE BUG DES -64 $.
    #
    #    `barrier_calibration.breakeven_winrate(tp, sl, cout)` calcule le winrate d'EQUILIBRE
    #    implique par une configuration de barrieres. L'autopsie du 11/07 avait trouve :
    #    « TP rabote a 28 bps pour 13 bps de frais -> breakeven 87 % -> perte GARANTIE ».
    #    La correction avait ete de changer la CONFIG. Aucun garde-fou n'empechait la rechute.
    #
    #    Et il y a pire, mesure aujourd'hui :
    #      * config du lanceur : TP=110, SL=60, cout=12  ->  breakeven = 72/170 = **42 %**  OK
    #      * DEFAUT DU CODE   : TP=30,  SL=40, cout=12  ->  breakeven = 52/70  = **74 %**  PERTE GARANTIE
    #
    #    Si le flag du lanceur disparait un jour -- ce qui est arrive DEUX FOIS dans ce projet
    #    (poller L2, funding) -- le code retombe SILENCIEUSEMENT sur une config perdante.
    #    Ce garde-fou transforme cette perte silencieuse en REFUS BRUYANT.
    "barrier_calibration",
)


#: Les paquets soumis a l'invariant « brancher ou enterrer ». En ajouter un ici suffit :
#: le test se met a le juger, et tout module qui y traine dans l'entre-deux casse la suite.
PAQUETS_JUGES: tuple[str, ...] = ("risk", "paper_trading", "exits")


def est_enterre(module: str) -> bool:
    return any(t.module == module for t in TOMBES)


def tombe_de(module: str) -> Tombe | None:
    for t in TOMBES:
        if t.module == module:
            return t
    return None


def modules_enterres(paquet: str | None = None) -> frozenset[str]:
    return frozenset(t.module for t in TOMBES if paquet is None or t.paquet == paquet)


def modules_branches() -> frozenset[str]:
    return frozenset(BRANCHES)


__all__ = [
    "BRANCHES",
    "PAQUETS_JUGES",
    "TOMBES",
    "Tombe",
    "est_enterre",
    "modules_branches",
    "modules_enterres",
    "tombe_de",
]
