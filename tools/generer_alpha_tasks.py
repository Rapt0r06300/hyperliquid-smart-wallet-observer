"""Génère le système de TASKS persistant P0→P65 (JSON) + le fichier de progression court.

Source de vérité structurée pour l'autonomie : chaque task porte id, priorité économique, objectif, deps,
fichiers, critères DONE, tests, preuve attendue, statut, SHA, résultat économique, next_action.
Reflète le travail DÉJÀ prouvé (ne pas refaire) avec ses SHAs. Ne supprime jamais une task non terminée.
"""
from __future__ import annotations

import json
import os

# (id, prio, objectif, deps, fichiers, done, tests, preuve, statut, sha, eco, next_action)
T = []


def t(id, prio, obj, deps, files, done, tests, proof, statut="TODO", sha=None, eco=None, nxt=""):
    T.append({"id": id, "prio_eco": prio, "objectif": obj, "deps": deps, "fichiers": files,
              "done_criteria": done, "tests_attendus": tests, "preuve_attendue": proof,
              "statut": statut, "sha": sha, "resultat_economique": eco, "next_action": nxt})


# ── Méta ──
t("P-SYS", 0, "Systeme de TASKS persistant + progression + ledger", [], ["runtime/research/alpha_tasks.json", "runtime/research/ALPHA_PROGRESS.md"],
  "JSON P0-P65 + progress + jamais suppr. task non finie", "n/a", "fichiers commit + relisibles", "IN_PROGRESS", None, None,
  "commit le systeme puis executer P13")

# ── Correctness / discipline (cheap, unblocks trustworthy verdicts) ──
t("P13", 1, "Audit + correction Alpha Factory: min/max best net OOS (BUG: min->max), append-only, reset non destructif, ajouter trial_id/config_hash/dataset_hash/pipeline_hash",
  ["P-SYS"], ["src/hl_observer/research/run_factory.py", "src/hl_observer/research/alpha_factory.py", "tests/test_alpha_factory.py", "tests/test_run_factory.py"],
  "min->max corrige; reset defaut False; hashes presents; registry append-only prouve", "test selection best=max; test reset defaut n'ecrase pas; test hashes presents",
  "run reel montre la BONNE meilleure cellule; registry conserve l'historique", "TODO")
t("P14", 3, "Source UNIQUE de couts (config/frais_venues). Supprimer hardcodes 9/3 bps concurrents. Separer fees/spread/slippage/latency. cost_incomplet=true interdit CANDIDAT/PROMOTE",
  ["P13"], ["src/hl_observer/config/frais_venues.py", "src/hl_observer/research/*.py"],
  "1 seule source frais; 0 hardcode concurrent; cost_incomplet bloque promote", "test source unique; test cost_incomplet bloque",
  "tous les modules lisent la meme source", "TODO")
t("P16", 6, "Search space pre-enregistre & hashe AVANT OOS: EVENT x STATE x FILTER x HORIZON x EXECUTION. Discovery explore, Freeze choisit, OOS mesure seulement",
  ["P8"], ["src/hl_observer/research/search_space.py"], "espace ecrit+hashe avant OOS; selection gelee", "test hash stable; test OOS ne voit pas discovery",
  "config_hash scelle par trial", "TODO")
t("P33", 5, "Cost-aware gate: trade seulement si LCB(gross) > P95(cout total) + marge. Pas moyenne>moyenne",
  ["P14"], ["src/hl_observer/research/cost_gate.py"], "gate LCB>P95cout implemente+branche", "test gate refuse si LCB<=P95",
  "gate applique dans la factory", "TODO")
t("P44", 5, "Sequential early-stop: KILL si LCB clairement <0 avec N suffisant; MORE_DATA si incertain; jamais stopper favorablement apres serie chanceuse",
  ["P8"], ["src/hl_observer/research/early_stop.py"], "regle early-stop codee+branchee", "test KILL rapide; test MORE_DATA",
  "verdicts precoces coherents", "TODO")
t("P45", 5, "Multiple-testing: registry donne N total d'essais; DSR/PBO/correction selon N reel. Plus la recherche est massive, plus PROMOTE est dur",
  ["P8", "P13"], ["src/hl_observer/research/multiple_testing.py", "src/hl_observer/backtesting/robustesse_selection.py"],
  "correction multiple-testing branchee sur N registry", "test seuil PROMOTE monte avec N", "PROMOTE plus dur si + d'essais", "TODO")

# ── Priority alpha leads (data-ready first) ──
t("P2", 2, "Wallet x Binance ANTICIPATION: wallets dont l'info PRECEDE Binance. Par action OPEN/ADD/REDUCE/CLOSE/FLIP, move_before/after a 50ms..30s, edge d'anticipation, signal age, copyable, capacity, net. Follower=KILL. DISCOVERY->RANK->FREEZE->OOS->FORWARD",
  ["P13"], ["src/hl_observer/research/wallet_binance_anticipation.py", "tests/test_wallet_binance_anticipation.py"],
  "mesure move_before/after Binance autour des fills wallet; ranking anticipation; OOS disjoint; verdict par wallet",
  "test sens anticipation; test follower->KILL; test OOS disjoint", "RUN reel sur bbo_synchro x leader_fills: table wallets par edge d'anticipation net", "TODO", None, None,
  "coder + mesurer sur bbo_synchro(HL+Bin) x leader_fills")
t("P3", 4, "TWAP/metaorder: brancher twapId/executedSz/executedNtl/total/residual/cadence/catch-up/EARLY-MIDDLE-LATE/crowding + depth replenishment/OFI/microprice. Predire le FLUX RESIDUEL, pas copier une slice publique",
  ["P13"], ["src/hl_observer/research/twap_residual.py", "tests/test_twap_residual.py"],
  "reconstruction metaorder + residual; test EARLY+LARGE_RESIDUAL+LOW_CROWDING+DEPTH_REPL+FAVORABLE", "test reconstruction; test residual signe",
  "RUN sur metaorder_l2_tape (24min -> MORE_DATA probable, mesure honnete)", "TODO")
t("P27", 4, "Metaorder hazard/residual: P(next slice|state), remaining_flow_probability, expected_remaining_notional. Features stage/cadence/executed fraction/residual/catch-up/replenishment/crowding",
  ["P3"], ["src/hl_observer/research/metaorder_hazard.py"], "modele hazard + sorties probabilistes", "test hazard monotone; test residual",
  "RUN sur metaorder tape", "TODO")
t("P7", 4, "ETH strong-shock GELE: ne pas retune. Accumuler + d'evenements independants; maker queue-aware reel; mesurer gross/fill prob/adverse/net/LCB/capacity/forward",
  ["P6"], ["src/hl_observer/research/hl_binance_leadlag.py", "src/hl_observer/research/execution_maker.py"],
  "N augmente sans retune; maker reel (pas sensibilite)", "test config gelee inchangee", "RUN: net/LCB sur + d'evenements", "MORE_DATA",
  "9d04bfa?", "net +5.87 N=4 -> MORE_DATA (besoin +N)", "attendre + de tape synchronise")

# ── Microstructure / execution ──
t("P5", 4, "Microstructure STATE->FLOW->SIGNAL. STATE: spread/depth L1-L20/queue imb/slope/convexity/vol/regime. FLOW: OFI/MLOFI/microprice/aggr signed vol/trade imb/add-cancel/depletion. Feature sans incrément NET OOS = DROP",
  ["P17"], ["src/hl_observer/research/ofi_microprice.py", "src/hl_observer/research/mlofi.py", "src/hl_observer/research/feature_increment.py"],
  "STATE/FLOW combos mesures; DROP applique", "tests OFI/MLOFI/increment", "OFI L1 KILL (11a29a9); MLOFI MORE_DATA (9d04bfa)", "MORE_DATA", "11a29a9",
  "L1 gross<cout; multi-niveaux data-limited", "besoin L2 HF multi-niveaux (P17)")
t("P6", 5, "Maker queue-aware reel (fin sensibilite fictive) sur signaux a gross prometteur. Comparer TT/MT/TM/MM. Queue ahead/trade-through/aggr vol/cancels/depletion/partial/non-fill/timeout/opp cost/adverse. JAMAIS price touched=fill",
  ["P23"], ["src/hl_observer/research/execution_maker.py"], "modele maker reel branche", "test non-fill; test adverse", "maker reel (ba97dbf)", "DONE", "ba97dbf",
  "queue-aware sans fill garanti", "brancher sur signaux survivants")
t("P23", 5, "Maker toxicity: predire adverse selection (aggr flow/absorption/fragility/depletion/microprice/spread regime). Maker autorise seulement si E[PnL|fill]>0 apres couts",
  ["P5"], ["src/hl_observer/research/maker_toxicity.py"], "predicteur toxicity + gate E[PnL|fill]>0", "test gate refuse si toxique",
  "toxicity mesuree avant maker", "TODO")
t("P24", 6, "Queue model calibration: baseline RiskAverseQueue puis challenger probabiliste. trade-through/cancels/depletion/partial reels; si L4 calibrer vs vraie priorite",
  ["P6"], ["src/hl_observer/research/queue_model.py"], "2 modeles compares sur data reelle", "test calibration", "fill prob calibree", "TODO")
t("P32", 5, "Alpha decay curves par famille: 0/50/100/250/500ms 1/2/5/10/30s -> half_life_alpha, max_signal_age, break_even_latency. Apres max age: NO_TRADE",
  ["P2"], ["src/hl_observer/research/alpha_decay.py"], "courbes decay + break_even_latency", "test decay decroit; test NO_TRADE apres max age",
  "courbe par famille", "TODO")
t("P50", 4, "Basis vs latency dislocation: classifier persistent basis vs transient. Features half-life/autocorr/duration/executable convergence. Cross-venue ne trade QUE transient",
  ["P13"], ["src/hl_observer/research/basis_vs_latency.py"], "classifieur basis/transient branche", "test basis persistant->rejet; test transient",
  "cross-venue: gros gaps=basis (autocorr>0.6) deja mesure", "MORE_DATA", None, "gaps illiquides=basis DISABLED_BY_SCOPE", "formaliser classifieur")

# ── Data / infra (impact haut mais data souvent BLOCKED ici) ──
t("P0", 7, "DATA HF simultanee HL(BBO/L2 multi/trades/fills/userFills/TWAP/L4) + Binance(BBO/L2/trades/aggTrades/signed vol). Timestamps exchange/receive_wall/receive_mono/normalize/signal/decision/fill. Aucun ts absent=now. sequence/snapshot+diff/DESYNC/reconnect/gaps/dup/out-of-order. raw immutable + canonical + quality manifest + hash. Quotas OFFICIELS dynamiques",
  [], ["src/hl_observer/research/hf_recorder.py", "collection/"], "recorder+normalizer+quality manifest codes+branches; collecte live sur la machine user",
  "test schema ts complet; test dedup/out-of-order", "capture live (hors sandbox: BLOCKED reseau)", "BLOCKED_EXTERNAL", None,
  "pas de reseau ici; collecteurs tournent chez l'user", "construire recorder+manifest (interface) puis brancher cote user")
t("P1", 7, "GLOBAL wallet observer: milliers de wallets via node_fills_by_block/archives. Pipeline streaming fills->normalize->dedup->wallet state->OPEN/ADD/REDUCE/CLOSE/FLIP->episodes->metaorders->features->OOS. chunks/checkpoints. Garder taille/startPosition/oid/twapId/coin/side/ts. DISCOVERY->FREEZE->OOS->FORWARD physiquement separes",
  ["P0"], ["src/hl_observer/research/wallet_population.py"], "ingestion streaming milliers; splits physiques", "tests streaming (fait)",
  "streaming prouve sur leader_fills (63d76c3); node_fills archives ABSENTES", "BLOCKED_EXTERNAL", "63d76c3",
  "streaming OK mais pas d'archives node_fills ici", "obtenir node_fills_by_block cote user")
t("P17", 6, "L2 HF top-20 sub-seconde: levels 1/3/5/10/20 prix/size/update ts + signed trades/add-cancel/depletion/sequence. HL+Binance",
  ["P0"], ["src/hl_observer/research/hf_recorder.py"], "recorder L2 top20 + trades signes", "test niveaux+sequence",
  "l2_book actuel = profondeur agregee (pas de niveaux); metaorder top5 = 24min", "BLOCKED_EXTERNAL", None,
  "data multi-niveaux HF absente", "collecter L2 top20 HF cote user")
t("P4", 7, "L4/order intent: reconstruire ORDER->MODIFY->CHASE->PARTIAL->FILL/CANCEL->POSITION. Features persistence/cancel-replace ratio/chase velocity/size escalation/distance-touch/queue/fill prob. Comparer FILL_ONLY/INTENT_ONLY/WALLET+INTENT/INTENT+MICRO. Si absent: BLOCKED_EXTERNAL + task infra + continue",
  ["P0"], ["src/hl_observer/research/order_intent.py"], "reconstruction+features (fait); mesure si flux L4", "tests (fait, 6315035)",
  "interface prete; flux node/L4 ABSENT", "BLOCKED_EXTERNAL", "6315035", "mesure impossible sans flux L4", "obtenir flux node/L4 cote user")
t("P18", 8, "Multi-venue leader observer READ-ONLY: Binance/Bybit/OKX/Coinbase. Normaliser BBO/L2/trades. HL reste seule venue PAPER d'execution", ["P0"],
  ["src/hl_observer/research/multi_venue.py"], "adaptateurs read-only + normalisation", "test normalisation", "venues additionnelles a brancher", "BLOCKED_EXTERNAL", None,
  "pas de flux Bybit/OKX/Coinbase ici", "brancher flux read-only cote user")

# ── Validation / robustness (cheap-ish, discipline) ──
t("P9", 6, "Replay=Forward: meme pipeline CanonicalEvent->State->Signal->Gate->PaperIntent->CausalExec->Fill->Ledger->Scoreboard. Tests prefix stability/future truncation/duplicate/out-of-order/reconnect/gap/stale. Meme intent+snapshot+config=meme fill/PnL",
  ["P10"], ["src/hl_observer/paper_trading/paper_engine.py"], "replay==forward prouve", "tests prefix/dup/oo/stale", "exec causale par defaut (86cd004)", "MORE_DATA", "86cd004",
  "causal branche; tests replay=forward a completer", "ecrire suite replay=forward")
t("P43", 6, "Purged + embargo validation pour horizons chevauchants: purge/embargo/no leakage + prefix stability", ["P9"],
  ["src/hl_observer/research/purged_cv.py"], "purge+embargo codes", "test no-leakage", "CV sans fuite", "TODO")
t("P59", 6, "Source->feature->alpha lineage: source/source ts/normalisation/transformation/version/causality par feature. Detection leakage", ["P5"],
  ["src/hl_observer/research/lineage.py"], "lineage trace par feature", "test causality flag", "leakage detecte tot", "TODO")
t("P57", 7, "Reproducibility: chaque trial garde code SHA/dataset hash/config hash/seed/python/deps/timestamps. Meme trial->meme resultat", ["P13"],
  ["src/hl_observer/research/alpha_factory.py"], "champs repro dans chaque trial", "test determinisme", "trial reproductible", "TODO")

# ── Regimes / signals (research) ──
for id, prio, obj, files in [
    ("P19", 6, "Dynamic price discovery par coin/regime: cross-corr/async lead-lag/Hayashi-Yoshida/Information Share -> venue_leader_score", ["src/hl_observer/research/price_discovery.py"]),
    ("P20", 6, "Cross-asset lead-lag: BTC->alts, ETH->beta, SOL->beta, majors->alts. Neutraliser beta/vol. Leave-one-coin/day OOS", ["src/hl_observer/research/cross_asset_leadlag.py"]),
    ("P21", 7, "Universal microstructure pooled model, features normalisees, leave-one-coin-out; favoriser signal transferable", ["src/hl_observer/research/universal_micro.py"]),
    ("P22", 8, "State-first nonlinear challenger: baseline simple d'abord; nonlinear seulement si NET OOS incrementale", ["src/hl_observer/research/nonlinear_challenger.py"]),
    ("P26", 7, "Book resiliency apres burst/TWAP/liq/spread shock: replenishment speed/recovery half-life/depth restored/side tilt; continuation vs reversal", ["src/hl_observer/research/book_resiliency.py"]),
    ("P28", 7, "Hidden flow x visible TWAP: permanent impact/crowding/depth response/toxicity", ["src/hl_observer/research/hidden_vs_twap.py"]),
    ("P29", 8, "Trigger/TP-SL map (si L4): isTrigger/triggerPx/isPositionTpsl/children/reduceOnly; densite triggers; accel/absorption/reversal. SHADOW", ["src/hl_observer/research/trigger_map.py"]),
    ("P30", 7, "Liquidation flow observer: direction/notional/partial-full/book impact/depletion/replenishment/continuation; regime LIQUIDATION_CASCADE", ["src/hl_observer/research/liquidation_flow.py"]),
    ("P31", 8, "Cascade early warning: taker-flow compression/price autocorr/depth thinning/liq proxies. Filtre regime jusqu'a preuve", ["src/hl_observer/research/cascade_warning.py"]),
    ("P36", 6, "Signal deconfliction: wallet+TWAP+OFI+Binance shock simultanes = 1 episode. event_cluster_id, eviter quadruple comptage", ["src/hl_observer/research/deconfliction.py"]),
    ("P37", 7, "Signal combination/meta-gate: combiner seulement si chaque composante ajoute NET OOS; ablation obligatoire", ["src/hl_observer/research/meta_gate.py"]),
    ("P38", 8, "Clock regimes comme filtre: seconde/minute/5m/15m/heure/sessions UTC; correction multiple-testing", ["src/hl_observer/research/clock_regimes.py"]),
    ("P39", 7, "Wallet behavior fingerprints: sizes/cadence/coins/offsets/cancel-replace/maker-taker/TWAP/oid patterns; infra commune", ["src/hl_observer/research/wallet_fingerprint.py"]),
    ("P40", 5, "Wallet information ratio: lead time/copyable gross/decay/capacity/latency tol/stability/entity indep. Jamais PnL brut", ["src/hl_observer/research/wallet_info_ratio.py"]),
    ("P51", 7, "Spread/liquidity transition: predire widen/narrow, depth collapse/recovery -> TAKER NOW/MAKER/WAIT/NO_TRADE", ["src/hl_observer/research/spread_transition.py"]),
    ("P52", 7, "New listing/abnormal regime safety: new listing/delisting/tick-lot change/OI cap/illiquid/abnormal spread; pas d'application aveugle", ["src/hl_observer/research/abnormal_regime.py"]),
    ("P54", 7, "Synthetic multi-venue NBBO read-only: best executable ref prix+profondeur; reference/signaux seulement", ["src/hl_observer/research/nbbo.py"]),
]:
    t(id, prio, obj, ["P0"] if id in ("P29", "P30", "P31", "P54") else ["P5"], files,
      "modele code+branche+mesure OOS ou BLOCKED documente", "tests cibles verts", "RUN reel ou BLOCKED_EXTERNAL", "TODO")

# ── Exits / sizing / portfolio / capacity (post-edge) ──
t("P35", 5, "Exit factory: fixed horizon/convergence/opposite signal/micro deterioration/time stop/SL/TP pre-enregistres, geles avant OOS. Mesurer NET/DD/capital-time",
  ["P16"], ["src/hl_observer/research/exit_factory.py"], "exits geles compares", "test exit gele", "NET/DD par exit", "TODO")
t("P46", 6, "Capacity curve: notionals 10/25/50/100/250/500/1000 USD; book walk + liquidity consumption -> capacity_before_edge_decay",
  ["P25"], ["src/hl_observer/research/capacity_curve.py"], "courbe capacity", "test decay avec notional", "capacity mesuree", "TODO")
t("P25", 6, "Liquidity consumption: une quantite affichee remplie une seule fois; ledger consommation par snapshot/level; reconstitution apres vraie update",
  ["P17"], ["src/hl_observer/research/liquidity_consumption.py"], "ledger consommation", "test double-remplissage interdit", "consommation reelle", "TODO")
t("P47", 6, "Capital efficiency: net PnL / avg margin / time-in-market -> net_edge_per_margin_hour", ["P12"],
  ["src/hl_observer/research/capital_efficiency.py"], "metrique capital/h", "test calcul", "capital/h par alpha", "TODO")
t("P48", 8, "Robust position sizing (SEULEMENT apres OOS+forward): fixed vs fractional Kelly plafonne; contraintes capacity/DD/ES. Sizing ne repare pas un mauvais edge",
  ["P41"], ["src/hl_observer/research/sizing.py"], "sizing borne", "test cap Kelly", "sizing sur edge prouve", "TODO")
t("P49", 8, "Portfolio d'alphas: PnL covariance/temporal overlap/coin beta/entity overlap; allouer entre edges independants", ["P41"],
  ["src/hl_observer/research/portfolio.py"], "alloc entre alphas independants", "test covariance", "alloc multi-alpha", "TODO")
t("P41", 6, "Forward frozen service: tout candidat OOS valide -> forward immutable, config/hash scelles, aucun retune. Mesurer PnL/cost/fill/capacity/drift",
  ["P16"], ["src/hl_observer/research/forward_frozen.py"], "service forward immutable", "test scelle+no retune", "forward continu", "TODO")
t("P42", 6, "Alpha drift detector rolling: net edge/LCB/hit rate/PF/cost/latency/regime; rupture->PAUSE/DEMOTE; jamais retune silencieux",
  ["P41"], ["src/hl_observer/research/drift_detector.py"], "detecteur drift", "test rupture->demote", "drift surveille", "TODO")
t("P12", 5, "Recette economique: BASE_CALIBRATED/ADVERSE_P95/ADVERSE_P99/OPTIMISTIC_DIAGNOSTIC_ONLY. Optimistic ne PROMOTE jamais. Table complete",
  ["P14"], ["src/hl_observer/research/recette_economique.py"], "4 scenarios; optimistic!=promote; table", "test optimistic bloque promote",
  "table par scenario", "TODO")
t("P34", 6, "Fee regime matrix: source officielle; base tier/maker/rebate(si applicable)/adverse fees. Aucun frais imaginaire", ["P14"],
  ["src/hl_observer/config/frais_venues.py"], "matrice frais reelle", "test frais officiels", "frais par regime", "TODO")

# ── Factory plumbing / perf / CI ──
t("P8", 3, "Alpha Factory: renforcer (pas reecrire). DATA x EVENT x STATE x FILTER x HORIZON x EXECUTION -> RESULT. Chaque trial: N raw/ind/gross/fees/spread/slippage/latency/net/LCB/PF/DD/ES/fill/capacity/OOS/forward/verdict. Tous trials enregistres",
  ["P13"], ["src/hl_observer/research/alpha_factory.py"], "schema complet; tous trials logges", "tests factory (fait)", "registre + table (00a481c)", "MORE_DATA", "00a481c",
  "factory ok; enrichir apres P13", "P13 corrige puis enrichir champs")
t("P15", 4, "Factory EXHAUSTIVE: run_factory execute TOUTES les familles (Wallet×Binance/lead-lag/strong-shock/TWAP/OFI/MLOFI/state/maker/cross-venue/L4/liquidations/exits/multi-venue). Plus aucun module absent de la Factory",
  ["P8"], ["src/hl_observer/research/run_factory.py"], "toutes familles branchees ou BLOCKED explicite", "P58 coverage test",
  "run reel couvre tout", "MORE_DATA", "95b8a00", "OFI/wallet/MLOFI/L4 branches; manque Wallet×Binance/TWAP/cross-venue live", "brancher P2/P3/cross-venue dans run_factory")
t("P58", 6, "Factory coverage test: echoue si une famille ACTIVE/SHADOW n'est ni testee ni BLOCKED explicite. Plus jamais de module oublie",
  ["P15"], ["tests/test_factory_coverage.py"], "test coverage familles", "meta-test", "aucun module oublie", "TODO")
t("P55", 7, "Data pipeline perf: streaming/chunks/immutable feature cache/memory map; pas de relecture totale JSONL par trial. Benchmark RAM+temps. Resultat invariant",
  ["P8"], ["src/hl_observer/research/feature_cache.py"], "cache + benchmark; resultat identique", "test invariance numerique", "perf mesuree", "TODO")
t("P56", 8, "Parallel factory: workers read-only, 1 seul writer registry, determinisme quel que soit N workers", ["P55"],
  ["src/hl_observer/research/parallel_factory.py"], "parallelisme deterministe", "test determinisme N workers", "meme resultat parallele", "TODO")
t("P10", 5, "Runtime complet par strategie: producer->canonical->decision->PaperEngine->ledger->scoreboard->heartbeat. Aucun module teste jamais appele; aucun flag ON sans producteur vivant",
  ["P9"], ["src/hl_observer/simulation/scoreboard_producer.py"], "chaine vivante par strategie", "test producteur->scoreboard (fait)", "scoreboard alimente runtime (0f18b13)", "MORE_DATA", "0f18b13",
  "producteur branche; strategies a alimenter", "brancher chaque strategie survivante")
t("P11", 8, "CI observable apres push: Linux shards/Windows/safety/full tests/JUnit/timeouts. Fault injection: WS reconnect/gap/dup/oo/stale/outage/ledger corruption/disk error",
  ["P64"], [".github/", "tools/"], "CI + fault injection", "CI verte", "artifacts CI", "TODO")
t("P64", 8, "CI/Windows APRES factory: CI observable/Windows/shards/factory tests/replay determinism/safety. Commit separe", ["P15"],
  [".github/"], "CI reparee", "CI verte", "run CI", "TODO")

# ── Meta research management ──
t("P60", 6, "Runtime->Factory loop: toute capture runtime integree aux recherches Discovery autorisees; forward frozen strictement separe", ["P10", "P41"],
  ["src/hl_observer/research/runtime_loop.py"], "boucle capture->discovery; forward isole", "test isolation forward", "nouvelles captures utilisees", "TODO")
t("P61", 5, "Daily alpha report compact: new trials/KILL/MORE_DATA/OOS/forward/drift/data gaps/N ajoute. Tableaux>prose", ["P8"],
  ["src/hl_observer/research/daily_report.py"], "rapport compact tabulaire", "test generation", "rapport quotidien", "TODO")
t("P62", 6, "Hard negative library: conserver zones KILL; ne pas retester sans nouvelle donnee ou hypothese explicite", ["P8"],
  ["runtime/research/hard_negatives.json"], "librairie KILL persistante", "test skip retest", "KILL memorises", "TODO")
t("P63", 5, "Research backlog scorer: impact x readiness x independence / cost -> Claude choisit auto la prochaine TASK", ["P-SYS"],
  ["src/hl_observer/research/backlog_scorer.py"], "scorer priorise le backlog", "test tri", "prochaine task auto", "TODO")
t("P65", 9, "Final economic acceptance: pas de DONE global sans factory exhaustive/data HF ou blocage/wallets scalable/TWAP teste/L4 si data/maker calibre/couts complets/OOS/forward/ADVERSE P95-P99/capacity/capital eff. Table finale complete",
  ["P15", "P12", "P41", "P46", "P47"], ["docs/audit/"], "tous prerequis satisfaits ou documentes BLOCKED", "meta", "table finale complete", "TODO")

T.sort(key=lambda x: (x["prio_eco"], x["id"]))
# [PORTABILITE item 1] défaut PORTABLE calculé depuis l'emplacement de ce fichier (racine réelle du
# projet), jamais un chemin absolu machine-spécifique. Surchargable par la variable OUT.
from pathlib import Path as _Path                                        # noqa: E402
_racine = _Path(__file__).resolve().parents[1]
out_dir = os.environ.get("OUT") or str(_racine / "runtime" / "research")
os.makedirs(out_dir, exist_ok=True)
with open(os.path.join(out_dir, "alpha_tasks.json"), "w", encoding="utf-8") as f:
    json.dump({"schema": "hypersmart.alpha_tasks.v1", "n_tasks": len(T), "tasks": T}, f, ensure_ascii=False, indent=1)

# progression courte
done = [x for x in T if x["statut"] == "DONE"]
blocked = [x for x in T if x["statut"] == "BLOCKED_EXTERNAL"]
prog = f"""# ALPHA PROGRESS — reprise en <2 min

CURRENT_TASK : P-SYS (systeme de tasks) -> ensuite P13
LAST_COMMIT  : 21dcddd (factory blocs 2-14)
TESTS        : 60 verts (suite recherche)
RESULT       : 0 candidat net-positif prouve a ce jour ; mur = cout/trade
NEXT_TASK    : P13 (fix min/max + append-only + hashes) puis P2 (Wallet x Binance anticipation, data-ready)
BLOCKERS     : data HF multi-niveaux, node_fills archives, flux L4 = a collecter cote user (pas de reseau ici)

## Etat
- Tasks totales : {len(T)}  |  DONE : {len(done)}  |  BLOCKED_EXTERNAL : {len(blocked)}  |  TODO/MORE_DATA : {len(T)-len(done)-len(blocked)}
- Priorite economique = impact x data_readiness x testabilite x independance / cout d'implementation
- Regle : >70% temps sur DATA/EXPERIENCES/REPLAY/OOS/FORWARD/EXECUTION ; 1 task = 1 commit ; jamais push

## Deja prouve (ne pas refaire sans nouvelle hypothese)
- BTC Binance->HL taker lead-lag : KILL
- OFI/microprice L1 : gross reel mais < couts (KILL)
- cross-venue gap<cout / gaps persistants = basis : KILL / DISABLED_BY_SCOPE
- wallet '+58bps' 0x1e9b : petit N/concentration, PUMP artefact -> pas un edge
- population 27 wallets : 0 candidat

## Prochaines pistes (par priorite)
1 DATA HF multi-level  2 milliers de wallets  3 Wallet×Binance anticipation  4 TWAP residual/hazard
5 L4 intent  6 maker toxicity+queue  7 multi-venue leadership  8 decay/cost-aware gates  9 exits  10 capital eff/portfolio
"""
with open(os.path.join(out_dir, "ALPHA_PROGRESS.md"), "w", encoding="utf-8") as f:
    f.write(prog)
print("tasks=", len(T), "done=", len(done), "blocked=", len(blocked))
print("top 8 par priorite:", [x["id"] for x in T[:8]])
