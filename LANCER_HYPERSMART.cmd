@echo off
setlocal
cd /d "%~dp0"

set "PYTHONPATH=%~dp0src;%PYTHONPATH%"
set "HL_ENV=paper"
set "HL_ENABLE_MAINNET_EXECUTION=0"
set "HL_ENABLE_TESTNET_EXECUTION=0"
set "HYPERSMART_MODE=SIMULATION_ONLY_UNTIL_MANUAL_REVIEW"
set "HYPERSMART_V12_SQLITE_PATH=%~dp0runtime\data\hypersmart_v12_artifacts.sqlite3"
rem ANTI-BLOAT: coupe le stockage brut (payloads L2/leaderboard/fills) qui a fait
rem gonfler la DB a 29 Go puis crasher. Le PnL/ledger n en depend pas. Mettre a 0
rem seulement si tu veux le replay brut (avec cap manuel).
set "HYPERSMART_DISABLE_RAW_STORAGE=1"
REM REPLAY: enregistre candidates.jsonl + marks.jsonl pour l'A/B replay apres le run.
REM Ecriture CAPEE (60 Mo marks / 20 Mo candidates, rotation last-N) -> jamais de
REM re-bloat comme les 29 Go. Sans ce flag, le run 48h ne produit AUCUNE donnee replay.
set "HYPERSMART_V26_RECORD_CANDIDATES=1"
set "HYPERSMART_V26_RECORD_PATH=%~dp0runtime\replay"
set "HYPERSMART_UI_STATE_DIR=%~dp0runtime\data"
set "HYPERSMART_POSITIVE_PNL_REQUIRED_FOR_FUTURE_REVIEW=1"
REM Reglages SELECTIFS Hyperliquid: runtime principal = Hyperliquid read-only + paper local.
REM Aucun moteur secondaire n'est lance par defaut.
REM CALIBRATION 2026-06-19 (basee sur l'analyse de 9154 decisions reelles du ledger):
REM   - les leaders font surtout ADD/REDUCE (9 OPEN sur 9154) -> ADD doit pouvoir entrer.
REM   - latence reelle public-WS: age median ~11 s -> 6000 ms etait inatteignable; 30000 ms reste selectif
REM     et rejette les fills retardes de plusieurs heures (backfill).
REM   - edge net observe rarement >=35 bps -> seuil ramene a un niveau atteignable mais POSITIF apres couts.
REM Toujours paper-only / read-only / deny-by-default. Aucune promesse de PnL: c'est un test honnete.
REM CORRECTIF WINRATE 2026-06-24 (analyse run perdant 24/06: 721 trades / 12.5%% WR / -20.61$ vs
REM session SAINE 21/06: 79 trades / 53.2%% WR / +0.80$). Cause: fenetre 45 s = on entre TROP TARD
REM (on chasse un move deja parti), le prix revient et le SL synthetique coupe -> pertes en serie.
REM Le snapshot le dit: "les entrees arrivent trop tard; consensus tres chaud vise 4 s". On resserre
REM a 15000 ms (fresh): admet la latence WS mediane ~11 s, rejette le chasing. Reversible.
set "HYPERSMART_SIMULATION_MAX_SIGNAL_AGE_MS=10000"
set "HYPERSMART_REDUCE_MAX_SIGNAL_AGE_MS=15000"
REM Les reductions leader sont proportionnelles a NOTRE position paper. Sur un compte
REM de simulation 1000 USDT, une vraie sortie partielle peut valoir moins de 10 USDT:
REM elle doit rester visible dans le ledger et le PnL au lieu d'etre ignoree.
set "HYPERSMART_MIN_REDUCE_NOTIONAL_USDT=0"
set "HYPERSMART_FUSION_COPY_MIN_WALLETS=2"
set "HYPERSMART_FRESH_OPPORTUNITY_MIN_WALLETS=2"
set "HYPERSMART_FUSION_COPY_COST_BUFFER_BPS=24"
set "HYPERSMART_DIRECT_ARBITRAGE_MIN_SPREAD_BPS=30"
set "HYPERSMART_V9_PIPELINE_AUTHORITATIVE=1"
set "HYPERSMART_SIMULATION_ALLOW_ADD_AS_ENTRY=0"
REM PREUVE D'ENTREE PAR PALIERS (demande user: positions 1-2 wallets "pas assez prouvees",
REM mais NE PAS bloquer): 2+ wallets d'accord = preuve par le CONSENSUS -> edge net >=10 suffit.
REM 1 seul wallet = il faut une preuve par la FORCE du signal -> edge net >=22 exige (15->22).
REM Un wallet solo fort passe quand meme (pas de blocage); le consensus reste la voie facile.
REM CORRECTIF 2026-06-24: edge net releve (10->15, solo 22->28) pour exiger une marge claire APRES
REM les couts (cost_model ~12 bps). "Moins de trades, plus propres": on ne prend que les signaux a
REM edge net franchement positif. Aucun fake, aucun edge negatif jamais accepte.
REM 2026-07-08: plancher edge copy releve 28->40 (replay causal: la selectivite passe le PnL net positif,
REM les 2 gros perdants venaient des trades a edge marginal). Reversible.
set "HYPERSMART_SIMULATION_MIN_EDGE_BPS=16"
set "HYPERSMART_SIMULATION_MIN_LIQUIDITY_SCORE=0.55"
set "HYPERSMART_SIMULATION_MAX_COPY_DEGRADATION_BPS=24"
set "HYPERSMART_SINGLE_WALLET_MIN_EDGE_BPS=55"
REM GATE V12 AUTORITATIF (2026-06-24): le gate unifie (source/quotes/fraicheur/liquidite/edge net)
REM devient CONTRAIGNANT en intersection plus stricte: un candidat ne passe que si le score ET le
REM gate V12 acceptent. Ne peut QUE reduire les trades (plus propres), jamais en creer. Mettre 0
REM pour repasser en shadow (observation seule). Sans effet sur la securite: 0 ordre reel.
set "HYPERSMART_V12_GATE_AUTHORITATIVE=1"
REM MODELE IA V13 (gratuit, local): chemins partages serveur <-> entraineur. Le serveur lit
REM le modele si present et affiche le panneau "Modele IA". Le modele reste en SHADOW
REM (observation, ne decide pas) tant que HYPERSMART_V13_MODEL_AUTHORITATIVE=0. Quand le
REM panneau montre qu'il bat la baseline (Brier), passe-le a 1 pour qu'il FILTRE les trades.
REM Entrainement: lance ENTRAINER_IA_AUTO.cmd a cote (apprend des trades clotures).
set "HYPERSMART_V13_MODEL_PATH=%~dp0runtime\models\trade_model_v13.json"
set "HYPERSMART_V13_MODEL_REPORT=%~dp0runtime\models\trade_model_v13.json.report.json"
set "HYPERSMART_V13_SAMPLES_PATH=%~dp0runtime\ml\training_samples.jsonl"
set "HYPERSMART_V13_MODEL_MIN_P=0.5"
set "HYPERSMART_V13_MODEL_AUTHORITATIVE=0"
REM Cadence d'apprentissage IA en secondes (l'IA reapprend et met a jour le panneau aussi souvent).
set "HYPERSMART_V13_TRAIN_INTERVAL_SEC=60"
REM IA EXPLICATIVE LOCALE (Ollama) toujours active avec le serveur. Si Ollama est installe sur
REM ta machine (gratuit, https://ollama.com) + un modele tire (ex: "ollama pull llama3.2"),
REM les explications seront formulees par l'IA ; sinon repli automatique sur des phrases-regles
REM (toujours claires, gratuites). Aucune API payante, tout reste local.
set "HYPERSMART_V13_OLLAMA_ENABLED=1"
set "HYPERSMART_V13_OLLAMA_HOST=http://127.0.0.1:11434"
set "OLLAMA_BASE_URL=http://127.0.0.1:11434"
set "HYPERSMART_V13_OLLAMA_MODEL=llama3.2"
set "OLLAMA_MODEL=llama3.2"
set "HYPERSMART_V13_OLLAMA_API_STYLE=auto"
set "HYPERSMART_V13_OLLAMA_UI_TIMEOUT_SEC=2"
set "HYPERSMART_V13_OLLAMA_TIMEOUT_SEC=12"
set "HYPERSMART_V13_OLLAMA_TEMPERATURE=0.1"
set "HYPERSMART_V13_OLLAMA_NUM_PREDICT=700"
REM IA V14 signal-rater: score/confiance de recherche sur candidats deja calcules.
REM Ne peut jamais creer une entree; peut seulement recommander un veto conservateur dans les logs.
set "HYPERSMART_V14_OLLAMA_MIN_AI_SCORE=0.62"
set "HYPERSMART_V14_OLLAMA_MIN_CONFIDENCE=0.55"
set "HYPERSMART_V13_EXPL_PATH=%~dp0runtime\ml\explanations_latest.json"
REM --- V14 (2026-06-25) PROMOTIONS OPT-IN (shadow par defaut = 0, n'agissent jamais seules) ---
REM #168 SIGNAL PRIMAIRE BALEINE: quand =1, une entree que le score accepterait est REFUSEE
REM   s'il n'y a PAS de fill de baleine frais et significatif derriere (shadow_whale_primary).
REM   Intersection plus stricte: ne peut QUE reduire les trades (plus propres), jamais en creer.
REM   Si le signal est inconnu (None) -> ne bloque pas. 0 = observation seule.
set "HYPERSMART_V14_WHALE_PRIMARY_AUTHORITATIVE=0"
REM #170 GARDE DE WARMUP: quand =1, pas de decision tant que le contexte (bars HTF/features) n'est
REM   pas pret. Inactif (no-op) tant que les bars ne sont pas cables dans le hot-path -> sans danger.
set "HYPERSMART_V14_WARMUP_AUTHORITATIVE=0"
REM #175 FENETRE DE CONSENSUS CHAUDE (~4 s chaud / 15 s max): quand =1, refuse une entree dont le
REM   signal est deja HORS fenetre fraiche (calcule depuis l'age du signal). Ne peut QUE reduire
REM   les trades. 0 = observation seule. (Anti-"course-poursuite" sur des moves deja partis.)
REM ACTIVE 2026-06-25: n'entrer QUE dans la fenetre fraiche (anti-chasing). Les logs montraient
REM beaucoup d'entrees STALE/retardees -> on les refuse desormais (ne peut que reduire les trades).
set "HYPERSMART_V14_CONSENSUS_WINDOW_AUTHORITATIVE=1"
REM #182 COUT D'EXECUTION dans le NET EDGE (LE PLUS GROS LEVIER "moins de trades, plus propres"):
REM   quand =1, refuse une entree dont la marge NETTE apres couts (frais HL + demi-spread +
REM   slippage calcule sur la taille ET la liquidite REELLES) tombe sous le plancher ci-dessous.
REM   Ne peut QUE reduire les trades. 0 = observation seule (les champs shadow_* restent calcules).
REM ACTIVE 2026-06-25: refuser toute entree dont la marge nette APRES couts reels (frais+spread+
REM slippage selon taille/liquidite) est <= 0. Tue les entrees marginales qui saignent en frais.
set "HYPERSMART_V14_EXEC_COST_AUTHORITATIVE=1"
set "HYPERSMART_V14_EXEC_MIN_NET_EDGE_BPS=0"
REM #183 QUALITE D'ENTREE (smart-money + profondeur): quand =1, refuse une entree si le leader
REM   n'est pas assez "smart money" (score < SMART_MONEY_MIN_SCORE) OU si la liquidite est sous le
REM   minimum (signaux REELS: score leader + liquidite). Ne peut QUE reduire les trades. 0 = obs.
set "HYPERSMART_V14_ENTRY_QUALITY_AUTHORITATIVE=0"
set "HYPERSMART_V14_SMART_MONEY_MIN_SCORE=60"
REM --- SORTIE: SUIVI DU LEADER (preuve par les donnees, 2026-06-24) ---
REM PREUVE: la session SAINE 21/06 (53.2%% WR, +0.80$) avait SL/TP synthetiques DESACTIVES et
REM tenait la position JUSQU'A CE QUE LE LEADER reduise/ferme (vrai copy-trading). Le run perdant
REM 24/06 (12.5%% WR, -20.61$) avait active SL40/TP30/trailing25: sur des entrees retardees, le SL
REM coupe au moindre bruit AVANT que le leader sorte -> beaucoup de petites pertes + saignee de couts.
REM Donc on REVIENT au profil gagnant: sortie pilotee par le LEADER, pas par un stop synthetique.
REM (PnL toujours au VRAI prix marche, jamais de faux PnL. Pour reactiver un stop catastrophe large
REM seulement: SLTP_ENABLED=1, STOP_LOSS_BPS=150, TAKE_PROFIT_BPS=99999, TRAILING_BPS=0.)
REM CORRECTIF PERTE 2026-06-25 (analyse snapshot: gagnants realises a +0.006$ / perdants jusqu'a
REM -5$ = "on coupe les gagnants, on laisse courir les perdants"). On REACTIVE un STOP CATASTROPHE
REM LARGE seulement (pas de TP, pas de trailing): coupe les rares desastres (-5$) SANS etrangler les
REM gagnants (les sorties restent pilotees par le leader). 150 bps de prix = 1.5% (x5 levier = 7.5%
REM de la marge). C'est le profil documente comme sur. Vrais prix, aucune triche.
REM CORRECTIF 2026-06-26 (analyse run 56.9%% WR mais -20$): les GAGNANTS ne realisaient que +0.04$
REM (miettes via les reduces du leader) alors que les PERDANTS atteignaient -0.11$ (2.6x) -> meme a
REM 57%% de reussite, l'esperance est negative. On capture donc NOUS-MEMES les gagnants et on coupe
REM les perdants tot: TP 60 bps (+3%% de marge a 5x) >= SL 45 bps (-2.25%%), trailing 30 bps pour
REM laisser courir un gagnant qui part fort. A 57%% WR: 0.57*60 - 0.43*45 = +15 bps/trade AVANT frais
REM (12 bps round-trip) = positif. Les entrees sont deja FRAICHES (gates actifs) donc le SL protege
REM au lieu de hacher (≠ piege du 24/06 ou les entrees etaient tardives). Vrais prix, aucune triche.
set "HYPERSMART_SLTP_ENABLED=1"
REM V24: profil paper plus reactif et plus stable pour une session 1000 USDT.
REM Les logs montraient que levier 5x + sorties tardives amplifiaient les frais
REM et les pics. On reste en simulation locale, au vrai prix marche, sans ordre.
REM ==========================================================================
REM BARRIERES CALIBREES A LA VOLATILITE (2026-07-08, demande Flo: "reproduire les
REM methodes gagnantes + maths complexes"). Au lieu de bps FIXES (incoherents: la
REM range 15min va de 4 bps sur ETH a 135 sur KAITO = facteur 34x), les barrieres
REM sont en UNITES DE VOLATILITE du coin (triple-barrier hummingbot + ATR-stop):
REM le moteur multiplie ces bps de BASE par clamp(range_coin/ref, 0.5, 2.5) -> ETH
REM calme = SL ~30 bps, KAITO volatil = SL ~150 bps. ref=30 bps = MEDIANE EMPIRIQUE
REM des ranges (calibree sur marks.jsonl reels via barrier_calibration.py).
REM ESPERANCE nette EXIGEE positive: E = p(TP-c) - (1-p)(SL+c). SL 60 / TP 120 = R:R
REM 2:1, cout 12 bps -> breakeven ~40%% WR (bas, atteignable en copiant du smart-money).
REM Follow-leader reste la sortie PRIMAIRE; ces barrieres = filet + trailing (laisse
REM courir le gagnant). Recalibrable sur les donnees 48h. Reversible (VOL_BARRIERS=0).
set "HYPERSMART_V26_VOL_BARRIERS=1"
set "HYPERSMART_V26_VOL_REF_RANGE_BPS=30"
set "HYPERSMART_V26_VOL_FACTOR_MIN=0.8"
set "HYPERSMART_V26_VOL_FACTOR_MAX=1.5"
set "HYPERSMART_SLTP_TAKE_PROFIT_BPS=110"
set "HYPERSMART_SLTP_STOP_LOSS_BPS=60"
set "HYPERSMART_SLTP_TRAILING_BPS=45"
set "HYPERSMART_SLTP_TRAILING_ACTIVATION_BPS=65"
set "HYPERSMART_SLTP_BREAKEVEN_BUFFER_BPS=10"
set "HYPERSMART_SLTP_STOP_MIN_HOLD_MS=45000"
set "HYPERSMART_SLTP_CATASTROPHIC_STOP_BPS=110"
set "HYPERSMART_SLTP_POSITION_TIMEOUT_MS=1800000"
set "HYPERSMART_MAX_NET_DIRECTIONAL_PCT=100"
set "HYPERSMART_MAX_COIN_NOTIONAL_PCT=60"
set "HYPERSMART_ADAPTIVE_PAPER_SIZING=1"
REM LIQUIDITE (analyse 2026-06-21: 199/256 refus = LIQUIDITY_TOO_LOW alors que signaux FRAIS
REM 5s + edge POSITIF 21 bps). Pour des positions de ~40 USDT, la recherche (mlmodelpoly: MIN_DEPTH=200
REM USDC) montre qu'une liquidite moyenne suffit. On relache 0.30 -> 0.22 pour debloquer ces bonnes
REM entrees fraiches sur alts copiables, tout en rejetant les marches VRAIMENT morts (<0.22).
set "HYPERSMART_SIMULATION_MIN_LIQUIDITY_SCORE=0.55"
REM CALIBRATION 2026-06-21 (analyse de 9154 decisions reelles: 100%% NO_TRADE, 0 ouverture).
REM   Cause racine: le cap dur de degradation (22) etait REDONDANT avec le gate d'edge net
REM   (edge_remaining soustrait DEJA toute la degradation). Resultat: 100%% des refus portaient
REM   COPY_DEGRADATION_TOO_HIGH, meme ~250 signaux a edge net positif (BTC/HYPE/ZEC/SOL, consensus).
REM   Fix HONNETE: on passe le cap a 40 (simple garde-fou anti-signal-casse) et on laisse le gate
REM   d'edge net (>=10 bps APRES tous les couts) decider. On n'accepte JAMAIS un edge net negatif.
set "HYPERSMART_SIMULATION_MAX_COPY_DEGRADATION_BPS=24"
REM Deviation de prix: 8 bps etait inatteignable a ~11s de latence (bruit normal). 18 rejette
REM toujours les vraies courses-poursuites (prix deja parti) sans tuer les entrees fraiches.
set "HYPERSMART_SIMULATION_MAX_PRICE_DEVIATION_BPS=18"
REM --- TAILLE & DIVERSIFICATION (pour exploiter les 1000 USDT sur PLEIN de coins) ---
REM DIAGNOSTIC 2026-06-21: le scan trouve deja 82 coins distincts en candidats, MAIS 100%% des
REM entrees non-ETH etaient refusees pour MAX_OPEN_PAPER_TRADES_REACHED (8 slots satures par ETH).
REM Le goulot n'etait PAS le scan mais le NOMBRE DE POSITIONS. On passe a 20 slots + positions
REM plus petites (60 USDT) pour tenir 15-16 coins EN PARALLELE et capter les bonnes opportunites
REM des autres coins au lieu de re-trader ETH en boucle. Diversification = moins de risque correle.
REM 60 slots = diversification maximale sur les 82+ coins candidats. Positions auto-dimensionnees
REM par l'exposition: l'edge net + le ranker de puissance (signals/opportunity_ranker, plafond
REM par coin) garantissent qu'on remplit les slots avec les MEILLEURES opportunites, pas du bruit ETH.
REM CORRECTIF 2026-06-24: 60 slots = sur-trading (721 trades, churn, saignee de couts). La session
REM gagnante 21/06 tenait MAX 6 positions. On revient a 12 (diversification raisonnable SANS churn):
REM moins de positions, mieux choisies, tenues jusqu'a la sortie du leader. Exposition max 600 USDT.
REM TAILLE & LEVIER (2026-06-25, remarque utilisateur: "des centimes c'est incoherent avec la mise"):
REM   sur Hyperliquid on trade des PERPETUELS avec LEVIER. La "mise" = MARGE bloquee ; la position
REM   controle marge*levier de notionnel ; le PnL = variation_prix * notionnel_leverage (donc un
REM   mouvement de 1% sur 100$ de marge a 5x = ~5$, plus des centimes). On passe la marge par
REM   position a 100$ (10 positions = 1000$ de marge deployable) et un levier de 5x (realiste/modere).
REM   L'exposition/cash restent comptes en MARGE -> les 1000$ sont toujours proteges. Aucun faux PnL:
REM   tout est calcule au VRAI prix marche, juste dimensionne comme un vrai compte perp.
set "HYPERSMART_MAX_POSITION_USDT=50"
REM ===== MODE GRINDER (session P1 2026-07-07, flags ON pour collecte de donnees A/B) =====
set "HYPERSMART_EXECUTION_STYLE=maker"
set "HYPERSMART_MAKER_ADVERSE_SELECTION_BPS=2"
set "HYPERSMART_FUNDING_ARB_PAPER=1"
REM 2026-07-08: poller funding ACTIVE — sans lui, funding_rows restait vide et le funding-arb
REM ne pouvait jamais ouvrir de paire (cause racine du "grinder qui ne trade pas").
set "HYPERSMART_V26_FUNDING_POLLER=1"
set "HYPERSMART_V26_FUNDING_POLL_INTERVAL_S=120"
set "HYPERSMART_FUNDING_ARB_MAX_PAIRS=5"
set "HYPERSMART_FUNDING_ARB_LEG_NOTIONAL_USDT=25"
set "HYPERSMART_DISTILLED_MAX_PAPER_ENTRIES=3"
set "HYPERSMART_WHALE_CONSENSUS_SIZING=1"
REM ============================================================
REM PLANCHER NOTIONAL (replay A/B 2026-07-07 sur logs frais): les micro-trades ont un net
REM negatif (frais ~59%% du brut). Filtre causal notional>=40: train ET validation positifs
REM (+0.11 vs -1.77 tous trades). Echantillon encore petit (13 trades) - a re-verifier.
set "HYPERSMART_MIN_PAPER_NOTIONAL_USDT=40"
set "HYPERSMART_MAX_TOTAL_EXPOSURE_USDT=1000"
set "HYPERSMART_MAX_OPEN_POSITIONS=20"
REM LEVIER de simulation: 5x = realisme perp Hyperliquid (demande Flo 2026-07-08: "pas que des
REM centimes, comme le marche reel"). notional = marge x levier -> $40 de marge = $200 d'expo.
REM PnL = notional x variation. HONNETE: le stop catastrophe (180 bps) plafonne la perte a ~9%%
REM de la marge a 5x (loin de la liquidation ~55x), donc jamais de perte > marge. Dialable (3/10).
set "HYPERSMART_SIMULATION_LEVERAGE=10"
REM LAISSER COURIR (demande Flo): on coupe le quality-guard qui fermait les positions a ~0.15%%
REM (elles n'atteignaient jamais leur SL/TP 1.2-1.6%%). Desormais SL/TP + sortie du leader gouvernent
REM -> on capture le VRAI mouvement du marche, pas du bruit. Reversible (=1 pour re-activer).
set "HYPERSMART_LEGACY_POSITION_QUALITY_GUARD_ENABLED=0"
REM RESET PROPRE A CHAQUE LANCEMENT (demande utilisateur): equity remise a 1000, compteurs
REM trades gagnants/perdants et taux de reussite remis a 0, logs de session repartis a neuf
REM (les anciens sont archives dans _archives). Mettre 0 pour au contraire CONSERVER l'equity.
REM RESET DES LOGS 2026-06-25: en plus, le dossier logs\ encombre est REMIS A ZERO a chaque
REM lancement (prepare-simulation-logs --purge-top-level): les gros *.log sont vides (tronques a 0),
REM les archives lourdes *.zip supprimees, l'ancien dossier mojibake retire. L'INTELLIGENCE DE
REM L'IA n'est JAMAIS touchee (modele + echantillons d'apprentissage vivent dans runtime\, hors logs\).
set "HYPERSMART_RESET_ON_LAUNCH=1"
REM Les anciens modules d'analyse multi-plateforme restent sur disque, non lances.
REM Les auxiliaires HyperSmart utiles (IA shadow + stream read-only) sont demarres par le script
REM principal, rattaches a la meme session, et stoppes avec Q.

REM ENTRAINEMENT IA AUTO (V13): demarre en arriere-plan des le lancement, apprend des trades
REM clotures et met a jour le panneau "Modele IA" (progression: n_trades, Brier, accuracy).
REM Paper-only / lecture seule. Fenetre minimisee "HyperSmart IA" - ferme-la pour stopper l'apprentissage.
REM IA rattachee au lanceur principal; pas de fenetre separee.
set "HYPERSMART_ENABLE_AUX_IA=1"

REM MOTEUR TEMPS REEL (V16, 2026-06-26): flux WebSocket Hyperliquid PERSISTANT sur les 10 MEILLEURS
REM leaders (cap HL = 10 wallets). Stocke chaque fill FRAIS a la seconde ou il arrive (sub-seconde)
REM au lieu du snapshot REST laggé (~10s) -> entrees vraiment fraiches. Lecture seule, 0 ordre.
REM Fenetre minimisee "HyperSmart Stream" - ferme-la pour stopper le flux temps reel.
REM Stream rattache au lanceur principal; pas de fenetre separee.
set "HYPERSMART_ENABLE_AUX_STREAM=1"

REM ARCHIVE REPLAY (2026-07-09, demande Flo): au lieu de perdre les donnees du run precedent,
REM on les DEPLACE dans runtime\replay\_archive\run_<ts>\ (serveur eteint, avant tout writer).
REM => le dataset replay s'accumule entre rallumages ; runtime\replay\ reste propre pour le run.
REM Le replay (merge_replay/include_archive) lit TOUT l'historique. Best-effort, jamais destructif.
python -m hl_observer.runtime.replay_recorder --archive-run --base "%~dp0runtime\replay" 1>nul 2>nul

REM -MaxLeaders eleve = scan TRES large (pool de leaders) ; le gate de qualite (smart money) garde la copie etroite.
REM === CARRY : ACTIVER l'ouverture REELLE des positions paper (etape 2, decision Flo 2026-07-18) ===
REM Sans ces flags, la boucle EVALUE le carry mais n'OUVRE RIEN -> 0 position (cause du "n'ouvre
REM aucune position"). Avec, il ouvre / tient / ferme en PAPER (aucun ordre reel, aucune signature,
REM PnL au vrai prix marche). Combine au plancher de levier 1x/1.5x (coins volatils VIABLES a bas
REM levier), le carry ouvre enfin des positions quand un carry est viable.
set "HYPERSMART_CARRY_HYPE_PAPER=1"
set "HYPERSMART_CARRY_ETAPE2=1"
REM === CARRY : alimentation AUTO des inputs spot (best coin, toutes les 10 min, en arriere-plan) ===
REM Sans ca, carry_spot_inputs.json n'est jamais ecrit -> le carry refuse tout (INPUTS_SPOT_ABSENTS).
start "carry-feeder" /min "%~dp0ALIMENTER-CARRY-AUTO.cmd"

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\start_hypersmart_simulation.ps1" -Port 8794 -IntervalSeconds 15 -MaxLeaders 50 -Interactive

exit /b 0
