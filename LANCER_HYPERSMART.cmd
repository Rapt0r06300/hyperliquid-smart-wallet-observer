@echo off
setlocal
cd /d "%~dp0"
REM item 9/10 : code de sortie propage de bout en bout. Jamais un exit /b 0 systematique en cas d'echec.
set "RC=0"
REM PORTABILITE : choisit en priorite le Python embarque relatif au dossier.
REM Le PATH est modifie uniquement pour cette session du lanceur et ses enfants.
call "%~dp0tools\portable_env.cmd"
if errorlevel 1 (
  echo   HyperSmart ne peut pas demarrer sans runtime Python valide.
  set "RC=30"
  goto :fin
)
if not defined HYPERSMART_PYTHON (
  echo   HYPERSMART_PYTHON non defini par portable_env. Abandon.
  set "RC=31"
  goto :fin
)
REM ============================================================================
REM  LANCER_HYPERSMART.cmd  --  LANCEUR RUNTIME OFFICIEL (2026-07-28)
REM ----------------------------------------------------------------------------
REM  Double-clic SANS argument = RUNTIME CORE : prevol securite/paper-only,
REM  verrou d'instance unique, moteur + dashboard + poller + stream leaders,
REM  allMids, BBO et userFills read-only. Les backtests/replays/recherches restent hors du hot path.
REM
REM  Sous-commandes (LANCER_HYPERSMART.cmd <cmd>) :
REM    status stop restart restart-userfills collectors report test audit
REM    replay moisson verify-oos github-push menu self-test
REM  Avances : audit-moissonneur premier-raw kill-userfills verif-l2 sonde notif-test
REM
REM  Les anciens .cmd de la racine sont ABSORBES ici (archives en .cmd.txt dans
REM  docs\archive\legacy_cmd\). Le seul second lanceur officiel est
REM  ANALYSER_BACKTESTS_REPLAYS.cmd, reserve aux analyses hors runtime.
REM  Securite : lecture seule marche. 0 ordre reel, 0 argent, 0 cle, 0 signature.
REM ============================================================================
if not "%~1"=="" goto :dispatch

:autopilot
REM ---- PREVOL : verrou d'instance unique (evite tout double lancement) ----
powershell -NoProfile -Command "try { if ((Test-NetConnection -ComputerName 127.0.0.1 -Port 8794 -WarningAction SilentlyContinue -InformationLevel Quiet)) { exit 2 } else { exit 0 } } catch { exit 0 }"
if errorlevel 2 (
  echo.
  echo   HyperSmart tourne DEJA ^(UI 127.0.0.1:8794 active^).
  echo   Pour redemarrer proprement : LANCER_HYPERSMART.cmd restart
  echo.
  goto :fin
)
REM === ITEM 11 : VERROU d'instance ATOMIQUE (le seul controle du port ne suffit PAS pendant le warmup,
REM   avant que l'UI ne lie 8794). Deux double-clics simultanes ne lancent JAMAIS deux recoltes.
if not exist "runtime\data" mkdir "runtime\data" >nul 2>&1
"%HYPERSMART_PYTHON%" -m hl_observer.ops.verrou_lanceur acquerir "%~dp0."
if errorlevel 1 (
  echo.
  echo   HyperSmart demarre DEJA ^(warmup en cours, verrou d'instance present^). Un seul lancement a la fois.
  echo   Pour redemarrer proprement : LANCER_HYPERSMART.cmd restart
  echo.
  set "RC=3"
  goto :fin
)
REM ---- PREVOL : registre PID/run_id + dossier logs du lanceur ----
if not exist "runtime\data" mkdir "runtime\data" >nul 2>&1
if not exist "runtime\logs\launcher" mkdir "runtime\logs\launcher" >nul 2>&1
powershell -NoProfile -Command "$o=[ordered]@{ role='launcher_autopilot'; note='pid_reels_dans_lanceur_pids.json'; run_id=([guid]::NewGuid().ToString('N').Substring(0,12)); port=8794; demarre=(Get-Date).ToString('s'); commit=(& git rev-parse --short HEAD 2>$null) }; ($o | ConvertTo-Json -Compress) | Set-Content -Encoding UTF8 (Join-Path '%~dp0' 'runtime\data\launcher_pids.json')" 2>nul
REM Le verificateur OOS planifie est strictement opt-in.
REM Utiliser "LANCER_HYPERSMART.cmd verify-oos install" pour l'activer explicitement.

set "PYTHONPATH=%~dp0src;%PYTHONPATH%"
REM === ITEM 21 : PREVOL PREMIER-LANCEMENT (PC neuf apres extraction de l'archive). Verifie OS/arch,
REM   droits d'ecriture, chemin a espaces/accents, horloge, port UI, aucune cle copiee, sessions
REM   preservees, et REGENERE l'identite machine (PID/verrous perimes/COURANTE, machine-id neuf) pour
REM   qu'une archive/dossier copiee ne reutilise JAMAIS l'etat de la machine de build. S'execute APRES
REM   le verrou (notre verrou d'instance vivant est preserve) et AVANT tout collecteur/session.
"%HYPERSMART_PYTHON%" -m hl_observer.ops.premier_lancement --racine "%~dp0."
if errorlevel 1 (
  echo.
  echo   [PREVOL] Premier lancement NO_GO : environnement inadapte ^(droits d'ecriture, ou cle presente^).
  echo   Voir le detail ci-dessus. Corrige puis relance. Aucun collecteur n'est demarre.
  echo.
  set "RC=7"
  goto :fin
)
set "HL_ENV=paper"
set "HL_ENABLE_MAINNET_EXECUTION=0"
set "HL_ENABLE_TESTNET_EXECUTION=0"
set "HYPERSMART_MODE=SIMULATION_ONLY_UNTIL_MANUAL_REVIEW"
set "HYPERSMART_STARTUP_PROFILE=harvest"
set "HYPERSMART_V12_SQLITE_PATH=%~dp0runtime\data\hypersmart_v12_artifacts.sqlite3"
rem ANTI-BLOAT: coupe le stockage brut (payloads L2/leaderboard/fills) qui a fait
rem gonfler la DB a 29 Go puis crasher. Le PnL/ledger n en depend pas. Mettre a 0
rem seulement si tu veux le replay brut (avec cap manuel).
set "HYPERSMART_DISABLE_RAW_STORAGE=1"
rem Item 11 : le brut SQL reste coupe (anti-bloat), mais on ACTIVE un stockage brut FICHIER BORNE
rem (shards gzip + quota + retention, aucune suppression silencieuse). 10 Go de plafond hot.
set "HYPERSMART_RAW_STORAGE_QUOTA_GO=10"
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
REM 23/07 (rectif Flo) — COHORTE EXPLORATORY_PAPER : apprend MAINTENANT sans attendre l'OOS complet.
REM Ouvre sur mouvement LIVE d'un vault retenu + edge PRELIMINAIRE positif (copy_prelim_edge.json) +
REM L2<1s + VWAP + couts complets + sortie definie. Budget $300, max 3, pertes plafonnees. Isole. 0 reel.
set "HYPERSMART_EXPLORATORY_PAPER=1"
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
set "HYPERSMART_FUNDING_ARB_PAPER=0"
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
REM 25/07 (Fix 1) : DEFAUT = CONSERVER equity/PnL/ledgers/positions/historique entre lancements.
REM AUTOPILOT et `restart` ne remettent PLUS a zero. Le reset ne se fait QUE via
REM `LANCER_HYPERSMART.cmd reset-paper --confirm` (sauvegarde horodatee AVANT toute remise a zero).
set "HYPERSMART_RESET_ON_LAUNCH=0"
REM Les anciens modules d'analyse multi-plateforme restent sur disque, non lances.
REM Les auxiliaires HyperSmart utiles (IA shadow + stream read-only) sont demarres par le script
REM principal, rattaches a la meme session, et stoppes avec Q.

REM L'entrainement IA n'est pas necessaire au runtime de collecte/decision. Il reste
REM disponible comme outil d'analyse explicite, sans consommer de ressources au demarrage.
set "HYPERSMART_ENABLE_AUX_IA=0"

REM MOTEUR TEMPS REEL (V16, 2026-06-26): flux WebSocket Hyperliquid PERSISTANT sur les 10 MEILLEURS
REM leaders (cap HL = 10 wallets). Stocke chaque fill FRAIS a la seconde ou il arrive (sub-seconde)
REM au lieu du snapshot REST laggé (~10s) -> entrees vraiment fraiches. Lecture seule, 0 ordre.
REM Fenetre minimisee "HyperSmart Stream" - ferme-la pour stopper le flux temps reel.
REM Stream rattache au lanceur principal; pas de fenetre separee.
set "HYPERSMART_ENABLE_AUX_STREAM=1"

REM === PREFLIGHT BLOQUANT (item 6) — env/deps/disque/dossiers/horloge/endpoints/quotas/schemas/paper.
REM   NO-GO => le moteur NE demarre PAS. Paper strict, lecture publique HL info uniquement, 0 ordre.
"%HYPERSMART_PYTHON%" -m hl_observer.ops.preflight_lanceur "%~dp0."
if errorlevel 1 (
  echo.
  echo   [PREFLIGHT] NO-GO : environnement non pret. Le moteur ne demarre pas. Corrige les blocages ci-dessus.
  echo.
  pause
  exit /b 2
)

REM ARCHIVE REPLAY (2026-07-09, demande Flo): au lieu de perdre les donnees du run precedent,
REM on les DEPLACE dans runtime\replay\_archive\run_<ts>\ (serveur eteint, avant tout writer).
REM => le dataset replay s'accumule entre rallumages ; runtime\replay\ reste propre pour le run.
REM Le replay (merge_replay/include_archive) lit TOUT l'historique. Best-effort, jamais destructif.
if not exist "%~dp0runtime\logs" mkdir "%~dp0runtime\logs" >nul 2>&1
"%HYPERSMART_PYTHON%" -m hl_observer.runtime.replay_recorder --archive-run --base "%~dp0runtime\replay" 1>>"%~dp0runtime\logs\archive_replay.log" 2>&1
if errorlevel 1 echo   [ATTENTION] Archivage replay: erreur signalee (non masquee) -- voir runtime\logs\archive_replay.log

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
call :demarrer_collecteurs
REM === Item 8 : une source OBLIGATOIRE (CORE) non demarree BLOQUE le moteur (superviseur -> exit 3).
if errorlevel 1 (
  echo.
  echo   [COLLECTEURS] Une source obligatoire n'a pas demarre. Le moteur ne demarre pas. Voir ci-dessus.
  echo.
  pause
  exit /b 3
)
REM Le superviseur enregistre directement les PID et reutilise les instances deja
REM vivantes. Aucun second passage de detection, aucun demarrage en double.
ping -n 3 127.0.0.1 >nul 2>&1
"%HYPERSMART_PYTHON%" -m hl_observer.ops.superviseur_collecteurs status harvest
echo   [collecteurs HARVEST] allMids + BBO(HL+Binance) + userFills + carnet L2 + marks + liq + venues + vaults + backfills.
REM === ITEM 1 : BARRIERE READY_CORE **BLOQUANTE** =============================================
REM Apres le demarrage des collecteurs, on attend (fenetre BORNEE de warmup) que le socle CORE
REM (allMids + BBO + userFills) PROUVE reellement sa vie. Tant que READY_CORE != true, le moteur,
REM l'UI et le poller NE demarrent PAS. On verifie ERRORLEVEL immediatement ; sortie non-zero
REM DATA_NOT_READY avec la SOURCE et la RAISON exactes affichees ci-dessus. Paper strict.
REM Fenetre de warmup surchargable : set HYPERSMART_WARMUP_CORE_SEC avant le lancement (defaut 90 s).
set "HYPERSMART_WARMUP_CORE_SEC=%HYPERSMART_WARMUP_CORE_SEC%"
if "%HYPERSMART_WARMUP_CORE_SEC%"=="" set "HYPERSMART_WARMUP_CORE_SEC=90"
echo   [READY_CORE] Attente bornee (%HYPERSMART_WARMUP_CORE_SEC% s) de la preuve de vie du socle CORE...
"%HYPERSMART_PYTHON%" -m hl_observer.ops.preuve_de_vie "%~dp0." --niveau core --attendre %HYPERSMART_WARMUP_CORE_SEC% --intervalle 3
if errorlevel 1 (
  echo.
  echo   [READY_CORE] DATA_NOT_READY : allMids/BBO/userFills n'ont PAS prouve leur vie dans la fenetre.
  echo   Le moteur, l'UI et le poller NE demarrent PAS ^(paper strict, aucune donnee fabriquee^).
  echo   Source et raison exactes affichees ci-dessus. Corrige puis relance.
  echo.
  pause
  exit /b 4
)
echo   [READY_CORE] OK : allMids + BBO + userFills prouves vivants. Demarrage moteur/UI/poller autorise.
REM Item 4 : niveau HARVEST detaille (COMPLET / DEGRADE_DOCUMENTE) — INFORMATIF, va au catalogue de session.
"%HYPERSMART_PYTHON%" -m hl_observer.ops.preuve_de_vie "%~dp0." --niveau harvest

REM === ITEM 7 (cablage) : ouverture de la SESSION canonique + declaration de TOUTES les sources ========
REM   Ecrit runtime\data\sessions\<run_id>\DATA_CATALOG.json (ACTIVE) + le pointeur COURANTE.json que le
REM   moniteur et ANALYSER retrouvent. Chaque source est DECLAREE (vivante avec compteurs reels, ou absente
REM   avec sa raison). Aucune donnee fabriquee.
"%HYPERSMART_PYTHON%" -m hl_observer.ops.session_harvest ouvrir "%~dp0."

REM === ITEM 9 : MONITEUR de sante INTEGRE AU LANCEMENT (plus besoin de "LANCER_HYPERSMART.cmd sante"). ==
REM   Boucle CACHEE (start /b) : rafraichit le tableau + APPEND runtime\logs\sante_journal.log en continu
REM   (READY_CORE/HARVEST, source, PID, heartbeat, events/s, fichier qui grossit, gaps/reconnects/stale,
REM   carnet sync, statut/raison). Process separe : une panne du moniteur n'affecte pas le moteur. 0 ordre.
if not exist "%~dp0runtime\logs" mkdir "%~dp0runtime\logs" >nul 2>&1
REM item 9 : UN SEUL writer pour sante_journal.log = le module moniteur_sante (journal synthetique).
REM La sortie CONSOLE redirigee va dans un fichier SEPARE (sante_console.log) -> plus d'ecritures
REM concurrentes ni de doublons sur le journal.
start "" /b "%HYPERSMART_PYTHON%" -m hl_observer.ops.moniteur_sante "%~dp0." --intervalle 3 1>>"%~dp0runtime\logs\sante_console.log" 2>&1

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\start_hypersmart_simulation.ps1" -Port 8794 -IntervalSeconds 15 -MaxLeaders 50 -Interactive

REM item 4 : a la SORTIE du moteur interactif (Q / croix / fin), on arrete REELLEMENT les writers puis on
REM CLOTURE la session (COMPLETE si tout verifie + zero orphelin + preuve d'arret ; sinon QUARANTINED).
set "RC_MOTEUR=%ERRORLEVEL%"
echo   [ARRET] Sortie du moteur : arret des collecteurs + cloture de session...
call :stop_impl
set "RC_STOP=%ERRORLEVEL%"
REM item 9 : propage le PREMIER code non nul (moteur PowerShell puis arret/cloture).
if not "%RC_MOTEUR%"=="0" ( set "RC=%RC_MOTEUR%" ) else ( if not "%RC_STOP%"=="0" set "RC=%RC_STOP%" )
goto :fin

:fin
REM item 9 : code de sortie reel (0 seulement si tout a reussi), jamais un exit /b 0 systematique.
REM [2026-08-05] JAMAIS de fermeture invisible. Un prevol NO_GO sortait en 7 sans pause : la
REM fenetre disparaissait avant d'etre lue, et la panne devenait indiagnosticable a l'oeil nu.
if not "%RC%"=="0" if /I not "%HYPERSMART_NO_PAUSE%"=="1" (
  echo.
  echo   ============================================================
  echo     ARRET sur le code %RC% - la raison exacte est AU-DESSUS.
  echo     Diagnostic complet : DIAGNOSTIC_LANCEUR.cmd
  echo     ^(HYPERSMART_NO_PAUSE=1 pour supprimer cette pause en automatise^)
  echo   ============================================================
  echo.
  pause
)
endlocal & exit /b %RC%

REM ############################################################################
REM #  SOUS-ROUTINE PARTAGEE : DEMARRAGE DES COLLECTEURS (source unique)
REM #  Reutilisee par l'AUTOPILOT et par la sous-commande `collectors`.
REM #  Le canari test_superviseur_collecteurs compte ces lignes 'start' : NE PAS
REM #  en ajouter/retirer sans mettre a jour le registre du superviseur.
REM ############################################################################
:demarrer_collecteurs
REM Profil HARVEST officiel (items 1/2) : socle CORE (allMids+BBO+userFills) PLUS la recolte dense
REM doublons et enregistre lui-meme les PID pour l'arret cible.
"%HYPERSMART_PYTHON%" -m hl_observer.ops.superviseur_collecteurs demarrer-tous harvest
exit /b %ERRORLEVEL%

REM ---------------------------------------------------------------------------
REM REFERENCE LEGACY CONSERVEE, MAIS INATTEIGNABLE.
REM Ces collecteurs sont disponibles via les profils maintenance/research/all.
REM Ils ne doivent plus etre lances avec le bot principal.
REM ---------------------------------------------------------------------------
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

REM === SCORE 8-FACTEURS DES VAULTS (rectif Flo 23/07) : on ne selectionne PLUS sur l'APR ===
REM PnL net + regularite + drawdown + anciennete + concentration + turnover + capacite + copyabilite.
REM Ecrit vaults_scores.json ; le signal copy_vault ne copie QUE les vaults RETENUS. 0 ordre.
start "" /b tools\boucle_collecteur.cmd scorer-vaults tools\scorer_vaults.py 600 --une-fois

REM === BACKFILL FILLS + MESURE OOS DE L'EDGE DE COPIE (rectif Flo 23/07 : ne pas attendre des jours) ===
REM backfill_vault_fills : userFillsByTime des vaults RETENUS + temoin -> episodes OPEN/ADD/REDUCE/CLOSE
REM (reduces de RETRAIT exclus). mesurer_copie : edge OOS train->walk-forward vs placebo -> gel si valide.
REM 2 endpoints PUBLICS en lecture. 0 ordre, 0 cle, 0 signature. Le signal copy_vault ne copie que si gele.
start "" /b tools\boucle_collecteur.cmd backfill-fills tools\backfill_vault_fills.py 14400 --une-fois
REM prix HISTORIQUES candles 5m SUR LES COINS DE VAULTS (5000 bougies = 416 h couvrent les 335 h des
REM fills) : DEBLOQUE la couverture prix pour la RECHERCHE, separee du forward L2 <1s (rectif Flo 23/07).
start "" /b tools\boucle_collecteur.cmd backfill-candles-vaults tools\backfill_candles_vaults.py 14400 --une-fois
REM ORCHESTRATEUR REEL : episodes+ledger+candles -> audit couverture + OOS walk-forward temporel purge
REM (generalisation vault en secondaire) + IC + ranking + SCALE/KILL. Forward candle ANTI-LOOKAHEAD.
start "" /b tools\boucle_collecteur.cmd pipeline-reel tools\pipeline_copie_reel.py 1800 --une-fois
REM GEL VERSIONNE de la table prelim (anti-reoptimisation : le forward ne se reoptimise jamais dessus).
start "" /b tools\boucle_collecteur.cmd geler-prelim tools\geler_prelim_copie.py 3600 --une-fois
REM FLUX WS userFills des vaults CORE+CHALLENGERS -> snapshots FRAIS event-driven (ouverture immediate).
start "" /b tools\boucle_collecteur.cmd userfills-live tools\collecter_userfills_vaults.py 5

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
REM 23/07 (rectif Flo) — l'ouverture exploratoire est desormais INLINE dans le flux WS userFills
REM (voir userfills-live plus bas : 2 cohortes ALPHA + DISCOVERY_PROBE, admission->L2->open dans le
REM meme flux). L'ancien tick passif exploratory-paper est donc RETIRE (remplace par l'inline).

REM ---- COPY-WHITELIST (#185, 20/07) : nourrit la porte copy (leaders au markout prouve). ----
REM La whitelist se PERIME a 24 h (porte deny-by-default) -> regeneree toutes les 6 h.
REM Sans donnees de fills forward, elle ecrit une liste VIDE = copy verrouille (honnete).
start "" /b tools\boucle_collecteur.cmd copy-whitelist tools\ecrire_copy_whitelist.py 21600
REM ---- RAPPORT QUOTIDIEN AUTO (20/07) : rapports\RAPPORT_DU_JOUR.md toujours frais (6 h). ----
start "" /b tools\boucle_collecteur.cmd rapport-quotidien tools\rapport_quotidien.py 21600

REM === LABORATOIRE DE RECHERCHE PARALLELE (RESEARCH_PARALLEL_V1, 25/07) : process ISOLE, read-only ===
REM UNE seule ligne reversible (la retirer = rollback total). Tout futur module de recherche passe par le
REM REGISTRE de plugins (src\hl_observer\research_parallel), plus jamais par ce lanceur. Data / ledgers /
REM positions / logs ISOLES sous runtime\research_lab (rien touche a RAW/OOS/MAIN). Kill-switch mou :
REM creer le fichier runtime\research_lab\DISABLED arrete le labo proprement sans toucher ce lanceur.
REM Une panne ou surcharge du labo n'affecte JAMAIS le moteur principal (process separe + isolation par
REM plugin dans le superviseur). Lecture seule, 0 cle, 0 ordre, 0 signature.
start "" /b tools\boucle_collecteur.cmd research-lab tools\lancer_research_parallel.py 60 --max-ticks 1

REM === LABO : collecteur WS microstructure DENSE (l2Book top20 + trades + BBO tailles), univers adaptatif ===
REM 24 coins (vol x OI x liquidations), isole sous research_lab. PERSISTANT : boucle_collecteur ne relance
REM qu'en cas de crash (comme bbo-collector). Debloque la profondeur (VWAP/capacite) + les familles HL
REM natives (OFI/microprice/absorption/cascade). Necessite le module python `websockets`. 0 cle, 0 ordre.
start "" /b tools\boucle_collecteur.cmd lab-microstructure tools\collecter_lab_microstructure.py 30

exit /b 0

REM ############################################################################
REM #  DISPATCHER DES SOUS-COMMANDES
REM ############################################################################
:dispatch
set "PYTHONPATH=%~dp0src;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
set "SUB=%~1"
if /I "%SUB%"=="status"            goto :cmd_status
if /I "%SUB%"=="stop"              goto :cmd_stop
if /I "%SUB%"=="restart"           goto :cmd_restart
if /I "%SUB%"=="restart-userfills" goto :cmd_ruserfills
if /I "%SUB%"=="collectors"        goto :cmd_collectors
if /I "%SUB%"=="collectors-maintenance" goto :cmd_collectors_maintenance
if /I "%SUB%"=="collectors-research"    goto :cmd_collectors_research
if /I "%SUB%"=="collectors-all"         goto :cmd_collectors_all
if /I "%SUB%"=="sante"             goto :cmd_sante
if /I "%SUB%"=="report"            goto :cmd_report
if /I "%SUB%"=="test"              goto :cmd_test
if /I "%SUB%"=="audit"             goto :cmd_audit
if /I "%SUB%"=="replay"            goto :cmd_replay
if /I "%SUB%"=="moisson"           goto :cmd_moisson
if /I "%SUB%"=="verify-oos"        goto :cmd_verifoos
if /I "%SUB%"=="github-push"       goto :cmd_github
if /I "%SUB%"=="reset-paper"       goto :cmd_resetpaper
if /I "%SUB%"=="self-test"         goto :cmd_selftest
if /I "%SUB%"=="menu"              goto :cmd_menu
if /I "%SUB%"=="audit-moissonneur" goto :cmd_auditmoiss
if /I "%SUB%"=="premier-raw"       goto :cmd_premierraw
if /I "%SUB%"=="kill-userfills"    goto :cmd_killuserfills
if /I "%SUB%"=="verif-l2"          goto :cmd_verifl2
if /I "%SUB%"=="sonde"             goto :cmd_sonde
if /I "%SUB%"=="notif-test"        goto :cmd_notiftest
if /I "%SUB%"=="portable-check"    goto :cmd_portablecheck
if /I "%SUB%"=="portable-install"  goto :cmd_portableinstall
if /I "%SUB%"=="portable-build"    goto :cmd_portablebuild
echo.
echo   Sous-commande inconnue : "%SUB%"
goto :cmd_menu

:cmd_menu
echo.
echo   =================  LANCER_HYPERSMART.cmd  =================
echo   Double-clic sans argument = RUNTIME CORE ^(moteur + dashboard + flux essentiels^).
echo.
echo   Controle :
echo     status              etat des processus du lanceur ^(lecture seule^)
echo     stop                arret cible ^(collecteurs + userfills^), jamais un kill global
echo     restart             stop puis autopilot
echo     restart-userfills   recharge le collecteur userfills avec le code courant
echo     collectors          demarre/reanime allMids + BBO + userFills ^(CORE^)
echo     collectors-maintenance   outils periodiques explicites
echo     collectors-research      collecteurs de recherche explicites
echo     collectors-all           tous les collecteurs ^(diagnostic exceptionnel^)
echo   Rapports / recherche :
echo     report              rapport du jour
echo     self-test           verification rapide 7 sections
echo     test                suite complete TOUT-TESTER
echo     audit               audit ~180 controles ^(resultat-audit.md^)
echo     replay              lance ANALYSER_BACKTESTS_REPLAYS.cmd
echo     moisson [github^|relire^|voir^|stop]     moissonneur de recherche
echo   Ops :
echo     verify-oos [install^|uninstall^|run^|diag^|test-notif]   verificateur OOS local
echo     github-push     push git fast-forward EXPLICITE ^(jamais de force^)
echo     reset-paper --confirm   remise a zero VOLONTAIRE ^(sauvegarde horodatee avant^)
echo     portable-check          verifie le runtime Python relocalisable
echo     portable-install        installe/repare le runtime Windows x64 local
echo     portable-build          cree le ZIP portable verifie sur le Bureau
echo     menu                cette aide
echo.
echo   Securite : lecture seule marche. 0 ordre reel, 0 cle, 0 signature.
echo.
goto :fin

REM -------- PORTABILITE WINDOWS --------
:cmd_portablecheck
echo.
"%HYPERSMART_PYTHON%" tools\portable_runtime.py --root "%~dp0." check --require-embedded --json
set "RC=%ERRORLEVEL%"
if "%RC%"=="0" echo PORTABLE_LAUNCHER_CHECK_OK
echo.
goto :fin

:cmd_portableinstall
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\install_portable_runtime.ps1" -ProjectRoot "%~dp0."
echo.
goto :fin

:cmd_portablebuild
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\create_portable_bundle.ps1" -ProjectRoot "%~dp0."
echo.
goto :fin

REM -------- STATUT (lecture seule) --------
:cmd_status
echo.
echo   ===  STATUT HYPERSMART  ^(lecture seule^)  ===
if exist "runtime\data\launcher_pids.json" ( echo   Registre lanceur : & type "runtime\data\launcher_pids.json" & echo. ) else ( echo   Pas de registre lanceur. )
powershell -NoProfile -Command "try { $ok=(Test-NetConnection -ComputerName 127.0.0.1 -Port 8794 -WarningAction SilentlyContinue -InformationLevel Quiet) } catch { $ok=$false }; Write-Host ('  UI 8794 : ' + $(if($ok){'ACTIVE'}else{'inactive'}))"
"%HYPERSMART_PYTHON%" -m hl_observer.ops.superviseur_collecteurs status harvest
echo.
goto :fin

REM -------- SANTE LIVE (tableau dynamique + journal horodate) --------
:cmd_sante
echo   Tableau de sante live des collecteurs (Ctrl-C pour quitter).
echo   Journal append-only : runtime\logs\sante_journal.log
"%HYPERSMART_PYTHON%" -m hl_observer.ops.moniteur_sante "%~dp0." --intervalle 2
goto :fin

REM -------- STOP (cible, jamais de kill global) --------
:cmd_stop
echo.
echo   Arret cible des collecteurs + userfills ^(par ligne de commande du projet ; aucun kill global^)...
call :stop_impl
set "RC=%ERRORLEVEL%"
echo.
echo   Arret + cloture termines ^(code %RC%^). QUARANTINED si un writer vivait encore ou un artefact manque.
echo.
goto :fin

:stop_impl
REM ARRET CIBLE (Fix 5) : SEULEMENT les PID enregistres du run + enfants verifies + process signes
REM registre + detenteur valide du port 8794 + verrou userfills. AUCUN motif large (*hl_observer*/*projet*).
"%HYPERSMART_PYTHON%" -m hl_observer.ops.superviseur_collecteurs arreter
set "RC_SUP=%ERRORLEVEL%"
REM === ITEMS 4 & 8 : CLOTURE SURE APRES l'arret des writers. On NE passe PLUS --writers-arretes : la
REM   preuve d'arret est CALCULEE independamment (registre PID -> aucun collecteur vivant). La session ne
REM   passe COMPLETE que si writers reellement arretes + checksums OK + artefacts reels + ZERO orphelin ;
REM   sinon QUARANTINED. Un collecteur orphelin encore vivant => QUARANTINED (jamais un faux COMPLETE).
"%HYPERSMART_PYTHON%" -m hl_observer.ops.session_harvest cloturer "%~dp0."
set "RC_CLO=%ERRORLEVEL%"
REM item 11 : libere le verrou d'instance (le lanceur est autoritaire sur son cycle de vie).
"%HYPERSMART_PYTHON%" -m hl_observer.ops.verrou_lanceur liberer "%~dp0." >nul 2>&1
REM item 9 : PREMIER code non nul (superviseur puis cloture). Jamais un exit /b 0 systematique.
set "RC_STOP=0"
if not "%RC_SUP%"=="0" ( set "RC_STOP=%RC_SUP%" ) else ( if not "%RC_CLO%"=="0" set "RC_STOP=%RC_CLO%" )
exit /b %RC_STOP%

REM -------- RESTART = stop puis autopilot --------
:cmd_restart
echo.
echo   Redemarrage : arret cible ^(collecteurs + userfills + moteur^) puis autopilot...
call :stop_impl
set "RC_STOP=%ERRORLEVEL%"
REM item 9 : un arret/cloture en echec NE redemarre PAS en silence (on propage le code).
if not "%RC_STOP%"=="0" (
  echo   [RESTART] Arret/cloture en echec ^(code %RC_STOP%^) : on NE redemarre pas. Corrige d'abord.
  set "RC=%RC_STOP%"
  goto :fin
)
timeout /t 6 >nul
goto :autopilot

REM -------- RESTART-USERFILLS (absorbe REDEMARRER / RELANCER / TUER-ORPHELIN) --------
:cmd_ruserfills
echo.
echo   Rechargement du collecteur userfills-live avec le code courant...
powershell -NoProfile -Command "$projet='%~dp0'; $lk=Join-Path $projet 'runtime\data\userfills_live.lock'; if (Test-Path $lk) { try { $pp=(Get-Content $lk -Raw | ConvertFrom-Json).pid; Stop-Process -Id $pp -Force -ErrorAction SilentlyContinue } catch {} }; $py = Get-CimInstance Win32_Process | Where-Object { ($_.Name -eq 'python.exe' -or $_.Name -eq 'pythonw.exe') -and $_.CommandLine -like '*collecter_userfills_vaults.py*' }; foreach ($x in $py) { Stop-Process -Id $x.ProcessId -Force -ErrorAction SilentlyContinue }; $w = Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'cmd.exe' -and $_.CommandLine -like '*boucle_collecteur.cmd userfills-live*' }; foreach ($x in $w) { Stop-Process -Id $x.ProcessId -Force -ErrorAction SilentlyContinue }; Start-Sleep -Milliseconds 800; Remove-Item $lk -Force -ErrorAction SilentlyContinue; Write-Host '  ancien userfills arrete + verrou libere.'"
cmd /c start "" /b tools\boucle_collecteur.cmd userfills-live tools\collecter_userfills_vaults.py 5
echo   collecteur userfills-live relance ^(detache, sans fenetre, code courant^).
timeout /t 9 >nul
if exist "runtime\data\userfills_live.lock" ( echo   OK : verrou recree : & type "runtime\data\userfills_live.lock" ) else ( echo   Pas encore de verrou ^(demarrage en cours, patiente ~10 s^). )
echo.
goto :fin

REM -------- COLLECTORS (absorbe REANIMER-COLLECTEURS ; reutilise la source unique) --------
:cmd_collectors
echo.
echo   Reanimation du profil CORE ^(idempotent, sans doublon^)...
call :demarrer_collecteurs
echo   Profil CORE actif. Journaux : runtime\logs\. Le moteur n'a pas ete touche.
echo.
goto :fin

:cmd_collectors_maintenance
echo.
"%HYPERSMART_PYTHON%" -m hl_observer.ops.superviseur_collecteurs demarrer-tous maintenance
"%HYPERSMART_PYTHON%" -m hl_observer.ops.superviseur_collecteurs status maintenance
echo.
goto :fin

:cmd_collectors_research
echo.
"%HYPERSMART_PYTHON%" -m hl_observer.ops.superviseur_collecteurs demarrer-tous research
"%HYPERSMART_PYTHON%" -m hl_observer.ops.superviseur_collecteurs status research
echo.
goto :fin

:cmd_collectors_all
echo.
"%HYPERSMART_PYTHON%" -m hl_observer.ops.superviseur_collecteurs demarrer-tous all
"%HYPERSMART_PYTHON%" -m hl_observer.ops.superviseur_collecteurs status all
echo.
goto :fin

REM -------- REPORT (absorbe RAPPORT-DU-JOUR) --------
:cmd_report
echo.
"%HYPERSMART_PYTHON%" tools\rapport_quotidien.py
echo.
pause
goto :fin

REM -------- TEST (absorbe TOUT-TESTER) --------
:cmd_test
"%HYPERSMART_PYTHON%" "%~dp0tools\lanceur_tout_tester.py" %2 %3 %4 %5 %6 %7 %8 %9
goto :fin

REM -------- AUDIT (absorbe TEST-AUDIT-complet) --------
:cmd_audit
echo.
echo   Lancement de l'audit ^(~180 controles^)...
"%HYPERSMART_PYTHON%" -m pip install -q pytest-timeout coverage 2>nul
"%HYPERSMART_PYTHON%" tools\audit_report.py %2 %3 %4 %5 %6 %7 %8 %9
set "AUDIT_CODE=%ERRORLEVEL%"
if exist "resultat-audit.md" ( echo   Rapport ecrit : %~dp0resultat-audit.md ) else ( echo   ATTENTION : le rapport n'a pas ete ecrit. )
echo.
pause
goto :fin

REM -------- REPLAY / BACKTESTS (outil separe du runtime principal) --------
:cmd_replay
echo.
call "%~dp0ANALYSER_BACKTESTS_REPLAYS.cmd" %2 %3 %4 %5 %6 %7 %8 %9
exit /b %ERRORLEVEL%

REM -------- MOISSON (absorbe LANCER-MOISSON-12H / MOISSONNER-GITHUB / RELIRE / VOIR / FERMER + workers) --------
:cmd_moisson
if /I "%~2"=="voir"   goto :moisson_voir
if /I "%~2"=="stop"   goto :moisson_stop
if /I "%~2"=="github" goto :moisson_github
if /I "%~2"=="relire" goto :moisson_relire
if not "%GITHUB_TOKEN%"=="" ( echo   Cle GitHub deja presente : on l'utilise. & goto :moisson_go )
set /p GITHUB_TOKEN=  Ta cle GitHub ^(vide = 60 req/h, sans recherche code^) :
:moisson_go
if exist "%~dp0moisson-termine.flag" del "%~dp0moisson-termine.flag" >nul 2>&1
if exist "%~dp0moisson-en-cours.txt" del "%~dp0moisson-en-cours.txt" >nul 2>&1
start "MOISSON 12h - travail (NE PAS FERMER)" /min cmd /c "set PYTHONPATH=%~dp0src;%~dp0& set PYTHONIOENCODING=utf-8& set PYTHONUTF8=1& "%HYPERSMART_PYTHON%" tools\moissonner_10h.py --heures 12 > "%~dp0moisson_console.txt" 2>&1& echo done> "%~dp0moisson-termine.flag""
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\voir_dashboard.ps1" -Root "%~dp0"
echo   Moisson terminee. Resultat : moisson-fini.md
goto :fin
:moisson_relire
if not exist "%~dp0data\reports\moisson_10h_etat.json" ( echo   Aucun etat sauvegarde -- lance d'abord `moisson`. & goto :fin )
if exist "%~dp0moisson-termine.flag" del "%~dp0moisson-termine.flag" >nul 2>&1
start "MOISSON 12h - travail (NE PAS FERMER)" /min cmd /c "set PYTHONPATH=%~dp0src;%~dp0& set PYTHONIOENCODING=utf-8& set PYTHONUTF8=1& "%HYPERSMART_PYTHON%" tools\moissonner_10h.py --heures 3 --relire > "%~dp0moisson_console.txt" 2>&1& echo done> "%~dp0moisson-termine.flag""
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\voir_dashboard.ps1" -Root "%~dp0"
goto :fin
:moisson_github
"%HYPERSMART_PYTHON%" tools\moissonner_10h.py %3 %4 %5 %6 %7 %8 %9
echo.
pause
goto :fin
:moisson_voir
title Tableau de bord - Moisson
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\voir_dashboard.ps1" -Root "%~dp0"
goto :fin
:moisson_stop
taskkill /FI "WINDOWTITLE eq MOISSON 12h*" /T /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq Tableau de bord*" /T /F >nul 2>&1
if exist "%~dp0moisson-termine.flag" del "%~dp0moisson-termine.flag" >nul 2>&1
echo   Moisson fermee. Rien n'est perdu : relancer reprend ou on s'etait arrete.
goto :fin

REM -------- VERIFY-OOS (absorbe LANCER/INSTALLER/DESINSTALLER/VERIF-PLANIF/TESTER-NOTIFICATION) --------
:cmd_verifoos
if /I "%~2"=="install"    goto :oos_install
if /I "%~2"=="uninstall"  goto :oos_uninstall
if /I "%~2"=="diag"       goto :oos_diag
if /I "%~2"=="test-notif" goto :oos_testnotif
if not exist "runtime\rapports\checkpoint_oos_shadow" mkdir "runtime\rapports\checkpoint_oos_shadow" >nul 2>&1
"%HYPERSMART_PYTHON%" tools\verif_checkpoint_oos_shadow.py >> "runtime\rapports\checkpoint_oos_shadow\verif.log" 2>&1
goto :fin
:oos_install
schtasks /Create /SC MINUTE /MO 30 /TN "HyperSmart_VerifOOS" /TR "wscript.exe \"%~dp0tools\run_verify_oos_silent.vbs\"" /F
schtasks /Query /TN "HyperSmart_VerifOOS" /V /FO LIST 2>nul | findstr /I "TaskName Next Task_To_Run Scheduled"
echo.
pause
goto :fin
:oos_uninstall
schtasks /Delete /TN "HyperSmart_VerifOOS" /F
echo.
pause
goto :fin
:oos_diag
set "DIR=%~dp0runtime\rapports\checkpoint_oos_shadow"
if not exist "%DIR%" mkdir "%DIR%" >nul 2>&1
schtasks /Query /TN "HyperSmart_VerifOOS" /V /FO LIST
schtasks /Run /TN "HyperSmart_VerifOOS"
timeout /t 12 /nobreak >nul
if exist "%DIR%\status.json" type "%DIR%\status.json"
echo.
pause
goto :fin
:oos_testnotif
"%HYPERSMART_PYTHON%" tools\verif_checkpoint_oos_shadow.py --test-notification
echo   Code de sortie : %ERRORLEVEL%
echo.
pause
goto :fin

REM -------- GITHUB-PUSH (absorbe POUSSER-GITHUB / POUSSER-GITHUB-FORCE ; jamais automatique) --------
:cmd_github
echo === Remote configure ===
git remote -v
echo.
echo === Etat local (status court + branche) ===
git status --short --branch
echo.
echo === Diff a pousser (resume) ===
git --no-pager diff --stat origin/main..HEAD 2>nul
echo.
echo === Envoi FAST-FORWARD de la branche main (jamais de force) ===
git push --ff-only origin main
if errorlevel 1 (
  echo.
  echo   REFUS PROPRE : le distant a diverge -- push fast-forward impossible. AUCUN force-push.
  echo   Resous d'abord :  git pull --rebase origin main   puis relance  LANCER_HYPERSMART.cmd github-push
)
echo.
pause
goto :fin

REM -------- RESET-PAPER (Fix 1) : remise a zero VOLONTAIRE, sauvegarde horodatee, exige --confirm --------
:cmd_resetpaper
echo.
echo   RESET PAPER : efface equity/PnL/positions ^(sauvegarde horodatee AVANT^). Exige --confirm.
"%HYPERSMART_PYTHON%" tools\reset_paper.py %2 %3
echo.
pause
goto :fin

REM -------- SELF-TEST (absorbe VERIFIER-TOUT) --------
:cmd_selftest
"%HYPERSMART_PYTHON%" tools\verifier_tout.py %2 %3 %4 %5 %6 %7 %8 %9
echo.
pause
goto :fin

REM -------- AVANCES (conservation totale) --------
:cmd_auditmoiss
"%HYPERSMART_PYTHON%" tools\audit_moissonneur.py > audit_moissonneur.txt 2>&1
echo   Rapport : audit_moissonneur.txt
goto :fin
:cmd_premierraw
"%HYPERSMART_PYTHON%" -c "from hl_observer.experimental import rapport_raw as R; p=R.ecrire_rapport('.'); print('Rapport ecrit :', p) if p else print('Aucun OPEN RAW pour l instant.')"
if exist "runtime\rapports\PREMIER_RAW.md" type "runtime\rapports\PREMIER_RAW.md"
echo.
pause
goto :fin
:cmd_killuserfills
powershell -NoProfile -Command "$projet='%~dp0'; $lk=Join-Path $projet 'runtime\data\userfills_live.lock'; if (Test-Path $lk) { try { $p=(Get-Content $lk -Raw | ConvertFrom-Json).pid; Stop-Process -Id $p -Force -ErrorAction SilentlyContinue; Start-Sleep -Milliseconds 700; Remove-Item $lk -Force -ErrorAction SilentlyContinue; Write-Host ('  PID ' + $p + ' arrete, verrou supprime.') } catch {} } else { Write-Host '  pas de verrou.' }; $py = Get-CimInstance Win32_Process | Where-Object { ($_.Name -eq 'python.exe' -or $_.Name -eq 'pythonw.exe') -and $_.CommandLine -like '*collecter_userfills_vaults.py*' }; foreach ($x in $py) { Stop-Process -Id $x.ProcessId -Force -ErrorAction SilentlyContinue }"
echo.
pause
goto :fin
:cmd_verifl2
if not exist "runtime\data" mkdir "runtime\data" >nul 2>&1
"%HYPERSMART_PYTHON%" -c "import sys; sys.path.insert(0,'tools'); import collecter_userfills_vaults as C; [print(c, C._lecteur_l2_ondemand(c)) for c in ('WLD','AERO','TIA','IO','LDO','SOL')]"
echo.
pause
goto :fin
:cmd_sonde
if not exist "runtime\data" mkdir "runtime\data" >nul 2>&1
"%HYPERSMART_PYTHON%" "tools\sonde_confirmation_vaults.py" --shard B
echo.
pause
goto :fin
:cmd_notiftest
"%HYPERSMART_PYTHON%" tools\verif_checkpoint_oos_shadow.py --test-notification
echo.
pause
goto :fin
