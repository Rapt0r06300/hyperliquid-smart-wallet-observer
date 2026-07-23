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
REM 20/07 — CAPITAL DECLARE (repli de la marge dynamique si l'etat UI est illisible).
REM Sans lui : capital=None -> marge 50 $/position -> 40 %% du capital dort. La distance a la
REM liquidation depend du LEVIER, pas de la taille : deployer plus a levier constant est sur.
set "HYPERSMART_SIMULATION_INITIAL_EQUITY_USDT=1000"
REM 21/07 — ARBITRAGE DE DISLOCATION paper v1 (portes dures pre-declarees : ouverture
REM >=35 bps = couts 22 + marge 13 -> edge positif a l entree PAR CONSTRUCTION ; sortie
REM <=5 bps ou 4 h ; 50$ x2 max). Ecrit au MEME ledger -> PnL unifie. 0 ordre reel.
set "HYPERSMART_ARB_DISLOCATION_PAPER=1"
REM 23/07 — VOIE EXPERIMENTAL_PAPER (decision Flo) : ouvre de VRAIES positions SIMULEES tout de suite
REM (cross-venue survivants geles / lead-lag / copy-vaults) SANS attendre la preuve OOS. Ledger, budget
REM et limites ISOLES du livre live (experimental_paper_ledger.jsonl). Admission = frais + executable +
REM edge net > 0 apres couts. L'allocateur strict de promotion et le no-real-trade restent intacts.
set "HYPERSMART_EXPERIMENTAL_PAPER=1"
REM 23/07 (v2) — CARRY FUNDING SUPPRIME DU SCOPE (rectif Flo) : la v1 cross-venue (funding + hold 168 h)
REM est en QUARANTAINE (fichiers experimental_paper_positions/ledger sans suffixe, plus lus). Le scope
REM ACTIF est experimental_paper_V2_* : cross-venue COURT TERME (dislocation de prix executable, entree/
REM sortie rapide, ZERO funding) + lead-lag + copy-vaults. Ce flag ne gele plus que le legacy funding.
set "HYPERSMART_EXPERIMENTAL_CROSS_VENUE_GELE=0"
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
REM ── VOLUME DE DONNEES (decision de Flo, 20/07) : « un replay A/B se fait sur des
REM    donnees ». Le plafond break-even passe de 120 h a 235 h pour ADMETTRE plus de
REM    carrys (fenetre d'admission doublee) et produire plus d'outcomes de sorties.
REM    ⚠️ COHERENCE VERROUILLEE PAR TEST : jamais au-dessus de 0,7 x AGE_MAX (336 h),
REM    sinon on fabrique des positions expulsees AVANT d'avoir amorti = churn garanti.
set "HYPERSMART_CARRY_MAX_BREAK_EVEN_H=235"
set "HYPERSMART_SIMULATION_MIN_EDGE_BPS=16"
set "HYPERSMART_SIMULATION_MIN_LIQUIDITY_SCORE=0.55"
set "HYPERSMART_SIMULATION_MAX_COPY_DEGRADATION_BPS=24"
REM 2026-07-18 — MODE SNIPER MONO-WALLET DECLARE FERME (sentinelle >= 1000), pas desactive en
REM douce : un plancher de 55 (ou 30) laissait croire que le mode vivait, alors que RIEN ne
REM pouvait le franchir. Nos mesures : edge de copie -7,97 bps sur 24 133 signaux hors
REM echantillon, leader CONTRARIEN. Copier un seul wallet, c'est payer pour perdre.
REM ⚠️ Ca ne retire AUCUNE ouverture aujourd'hui (le mode etait deja infranchissable de fait).
REM REVERSIBLE : le jour ou on mesure un edge de copie POSITIF, on remet un vrai plancher.
set "HYPERSMART_SINGLE_WALLET_MIN_EDGE_BPS=9999"
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
REM === CARRY HISTORIQUE : DESACTIVE / SHADOW (decision Flo 2026-07-23) ===
REM Ce carry delta-neutre HL-only affichait -8,24 $ : 100%% du funding au PLANCHER (0,125 bph) -> ~2-3%%
REM APR net, DOMINE par HLP (15-30%%). Le cross-venue mid-cap (DOT/NEO/RUNE, net OOS positif battant
REM HLP) le remplace comme piste carry. On coupe donc l'OUVERTURE (budget 0, AUCUNE entree). Les 6
REM positions ouvertes sont fermees proprement aux prix executables (couts complets) par
REM tools\fermer_carry_historique.py APRES la relance ; l'historique reste au ledger. SHADOW : le
REM module peut encore EVALUER/journaliser mais n'OUVRE plus rien. Remettre a 1 = re-litiger une piste refutee.
set "HYPERSMART_CARRY_HYPE_PAPER=0"
set "HYPERSMART_CARRY_ETAPE2=0"
set "HYPERSMART_CARRY_DISABLED=1"
REM === CARRY : alimentation AUTO des inputs spot (best coin, toutes les 10 min, en arriere-plan) ===
REM Sans ca, carry_spot_inputs.json n'est jamais ecrit -> le carry refuse tout (INPUTS_SPOT_ABSENTS).
REM 19/07 — SANS FENETRE. Ces 3 collecteurs ouvraient 3 fenetres cmd a chaque demarrage :
REM insupportable a l'usage, et c'est moi qui les avais ajoutees. Ils tournent desormais CACHES.
REM ⚠️ Mais un processus cache qui echoue en SILENCE serait exactement la maladie qu'on vient de
REM corriger (les 105 `except: pass`). Chacun ecrit donc son journal dans runtime\logs\ :
REM   runtime\logs\carry-feeder.log · marks-collector.log · liq-collector.log
REM En cas de doute : ouvre le .log, ou double-clique le .cmd correspondant pour le voir tourner.
if not exist "%~dp0runtime\logs" mkdir "%~dp0runtime\logs" >nul 2>&1
REM ⚠️ `start "" /b` et PAS PowerShell/Start-Process. J'avais d'abord ecrit une ligne PowerShell
REM avec trois niveaux de guillemets imbriques sur un chemin qui contient une ESPACE
REM ("Projet invest") -- du code qui casse en silence, et un collecteur qui ne demarre jamais
REM sans le dire, c'est exactement la maladie qu'on passe la journee a corriger.
REM `/b` = pas de nouvelle fenetre (doc Windows), UN seul niveau de guillemets, et toute la
REM sortie part deja dans le log depuis boucle_collecteur.cmd.
REM ⚠️ CHEMINS RELATIFS, ZERO GUILLEMET. Ma version precedente passait des chemins ABSOLUS
REM entre guillemets ; le dossier s'appelle « Projet invest » (avec une ESPACE), et `start /b`
REM lance un .cmd via `cmd /c` qui, des qu'il voit PLUSIEURS paires de guillemets, retire la
REM premiere et la derniere. Resultat mesure chez Flo :
REM     'C:\Users\flo\Desktop\Projet' n'est pas reconnu... (x3, un par collecteur)
REM Le lanceur a deja fait `cd /d "%~dp0"` (ligne 3) : on est DANS le dossier projet. Des chemins
REM relatifs n'ont donc ni espace ni guillemet -- le bug ne peut plus se produire.
REM 21/07 ANTI-ORPHELIN : marqueur UNIQUE de session, ecrit AVANT les boucles. Les boucles
REM d'une session precedente voient le marqueur changer et s'arretent d'elles-memes ->
REM plus jamais deux carry-feeders en parallele apres un Q, une croix ou un crash.
if not exist "runtime\data" mkdir "runtime\data" >nul 2>&1
echo %random%-%random%-%date%-%time% > "runtime\data\lanceur_session_marqueur.txt"
REM [SHADOW 23/07] carry-feeder COUPE : le carry historique n'ouvre plus -> inputs spot inutiles.
REM (Reactiver cette ligne uniquement si on re-litige le carry historique, une piste refutee.)
REM start "" /b tools\boucle_collecteur.cmd carry-feeder tools\ecrire_carry_spot_inputs.py 240

REM === REPLAY : collecte des MARKS (prix futur) sur TOUS les coins des candidats ===
REM Mesure du 19/07 : 30 148 candidats sur 106 coins, mais des marks sur 2 coins seulement
REM -> 29 %% des candidats rejouables. BTC/ETH/SOL/ZEC avaient des candidats et AUCUN prix
REM futur : impossible de calculer leur PnL forward. Sans ce collecteur, le replay A/B ne
REM peut juger qu'une poignee de coins. Lecture seule (/info allMids), 0 ordre.
start "" /b tools\boucle_collecteur.cmd marks-collector tools\ecrire_marks_tous_coins.py 60 --une-fois

REM === allMids TOUS-COINS (non filtre) : prix HL frais pour Copy-Vaults sur les ~100 coins que ===
REM les vaults tradent (le flux BBO n'en couvre que 8). Un seul appel public /info allMids, 0 ordre. ===
start "" /b tools\boucle_collecteur.cmd allmids-collector tools\collecter_allmids.py 15 --une-fois

REM === LIQUIDATIONS : sans ce collecteur, la mesure #3 est impossible A JAMAIS ===
REM Constat du 19/07 : "snapshots": 0 -> AUCUN_HISTORIQUE_LA_MESURE_EST_IMPOSSIBLE. Le message
REM conseillait d'attendre plus longtemps -- mauvais conseil : RIEN n'ecrivait ces donnees
REM (enregistrer_grappes n'etait appele que par mainnet_readonly_observer, hors boucle live).
REM 3 endpoints PUBLICS en lecture, modules existants, 0 ordre.
start "" /b tools\boucle_collecteur.cmd liq-collector tools\collecter_liquidations.py 300 --une-fois

REM === DISPERSION CROSS-VENUE : la DERNIERE piste ouverte du projet ===
REM Toutes les autres sont mortes, tuees par nos propres mesures (copy -7,97 bps, MM 0/29,
REM funding perp-perp MEME venue 0/120, lead-lag 0/66, liquidations inmesurables).
REM Celle-ci n'a jamais ete testee : HL et Binance ne cotent pas le meme funding.
REM Barres de rejet fixees AVANT la donnee : docs\audit\PROTOCOLE_CROSS_VENUE.md
REM ⚠️ Binance = SOURCE DE PRIX uniquement. Lecture seule, 0 cle, 0 ordre.
start "" /b tools\boucle_collecteur.cmd venues-collector tools\collecter_dispersion_venues.py 60 --une-fois
start "" /b tools\boucle_collecteur.cmd carnet-collector tools\collecter_carnet.py 60 --une-fois

REM === EVENEMENTS DE LIQUIDATION (overshoot mark/oracle) : l'infra n1 du 23/07 ===
REM La meilleure piste (fade de cascades de liquidations) etait BLOQUEE faute d'events reels.
REM On capture l'overshoot mid-vs-oracle (le forced-flow deborde le mid de l'oracle puis revient)
REM + le chemin forward -> matiere du fade. BTC exclu (mort). Etat persiste (survit aux relances).
REM ⚠️ 2 endpoints PUBLICS en lecture (metaAndAssetCtxs + allMids). 0 cle, 0 ordre, 0 signature.
start "" /b tools\boucle_collecteur.cmd overshoot-collector tools\collecter_overshoots.py 10 --une-fois

REM === VAULTS HL (chantier COPY 23/07) : la derniere porte copy non ouverte ===
REM Le copy de fills est mort (signal 62s, 76%% = 4 wallets MM). Un VAULT tient des JOURS -> nos 62s
REM sont negligeables. On capture NAV/positions/levier/PnL latent+realise/drawdown/expo pour mesurer
REM si repliquer sa trajectoire reste rentable apres delai+couts. Liste = runtime\data\vaults_suivis.json
REM (vaults DIRECTIONNELS ; les vaults de MARKET-MAKING type HLP sont exclus). Vide -> idle propre.
REM ⚠️ 2 endpoints PUBLICS en lecture (clearinghouseState + vaultDetails). 0 cle, 0 ordre, 0 signature.
start "" /b tools\boucle_collecteur.cmd vault-collector tools\collecter_vaults.py 300 --une-fois

REM === BBO RAPIDE HL/Binance (chantier ARB 23/07) : quotes SYNCHRONISEES pour trancher le lead-lag ===
REM Le detecteur d'arb actuel est INVALIDE (base persistante +17-30bps = mapping/quote perimee).
REM Ce collecteur WS PERSISTANT (HL bbo + Binance bookTicker) donne des quotes MAPPEES exactement,
REM FRAICHES (rejet des perimees), HORODATEES (exchange+local) -> teste proprement le lead-lag
REM Binance->HL en shadow. PERSISTANT : reconnecte SEULEMENT sur panne, garde son etat, horloge
REM MONOTONE a la reception (un skew d'horloge ne doit PAS ressembler a un edge), heartbeat +
REM anti-orphelin INTERNE (sort si la session change). boucle_collecteur ne relance qu'en cas de crash.
REM ⚠️ 2 flux PUBLICS en lecture. 0 cle, 0 ordre, 0 signature. Necessite le module python `websockets`.
start "" /b tools\boucle_collecteur.cmd bbo-collector tools\collecter_bbo.py 5

REM ---- VOIE EXPERIMENTAL_PAPER (23/07) : ouvre/gere/sort de VRAIES positions SIMULEES toutes les 60 s
REM (cross-venue geles + lead-lag + copy-vaults) des qu'un signal est frais + executable + edge net > 0.
REM Ledger/budget/limites ISOLES du livre live. Gate par HYPERSMART_EXPERIMENTAL_PAPER=1. 0 ordre reel.
start "" /b tools\boucle_collecteur.cmd experimental-paper tools\experimental_paper_tick.py 60 --une-fois

REM ---- COPY-WHITELIST (#185, 20/07) : nourrit la porte copy (leaders au markout prouve). ----
REM La whitelist se PERIME a 24 h (porte deny-by-default) -> regeneree toutes les 6 h.
REM Sans donnees de fills forward, elle ecrit une liste VIDE = copy verrouille (honnete).
start "" /b tools\boucle_collecteur.cmd copy-whitelist tools\ecrire_copy_whitelist.py 21600
REM ---- RAPPORT QUOTIDIEN AUTO (20/07) : rapports\RAPPORT_DU_JOUR.md toujours frais (6 h). ----
start "" /b tools\boucle_collecteur.cmd rapport-quotidien tools\rapport_quotidien.py 21600

REM AUTO-VERIFICATION : un collecteur cache qui ne demarre pas ne se voit PAS. On attend qu'il
REM ecrive son log (il l'ecrit des la 1re ligne) et on DIT si l'un des trois manque a l'appel.
ping -n 6 127.0.0.1 >nul 2>&1
for %%C in (carry-feeder marks-collector liq-collector venues-collector copy-whitelist rapport-quotidien) do (
  if exist "%~dp0runtime\logs\%%C.log" (
    echo   [collecteurs] %%C ......... demarre
  ) else (
    echo   [collecteurs] %%C ......... !! N'A PAS DEMARRE -- voir runtime\logs\
  )
)
echo   [collecteurs] sans fenetre. Journaux : runtime\logs\  ^|  arret : ARRETER-COLLECTEURS.cmd

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\start_hypersmart_simulation.ps1" -Port 8794 -IntervalSeconds 15 -MaxLeaders 50 -Interactive

exit /b 0
