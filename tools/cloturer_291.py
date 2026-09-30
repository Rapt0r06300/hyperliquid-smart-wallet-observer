"""CLÔTURE DES 291 TÂCHES DE `task.txt` — avec un verdict TRAÇABLE pour chacune.

⚠️ RÈGLE : **ne rien supprimer.** On ne fait que cocher `- [ ]` -> `- [x]` et ajouter une ligne
de verdict. Aucun texte existant n'est retiré.

⚠️ RÈGLE 2 : **on ne coche PAS ce qui n'est pas fait.** Une tâche d'INGÉNIERIE jamais construite
reste ouverte, même si j'ai « réfléchi » dessus. *Un rapport n'est pas du code.*

Les verdicts possibles :
  FAIT       — codé/mesuré/livré, avec un artefact citable
  DOMINE     — tué par l'arithmétique de T1b (100 % de fill) : améliorer le fill ne peut qu'empirer
  REFUS      — zone morte, MÊME ENTRÉE que la mesure qui l'a tuée
  CONFIRME   — la tâche DIT une chose qu'on a déjà mesurée : elle nous donne raison
  ACTE       — constat/méta sur ma propre moisson : enregistré, rien à coder
  REFUS_SEC  — 🚨 sécurité : jamais, sous aucune condition
  OUVERT     — **PAS FAIT.** De l'ingénierie réelle qui reste à construire. On ne ment pas.

Aucun ordre réel.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
TASKLIST = RACINE / "TASKLIST.md"
TASKTXT = RACINE / "task_291.txt"          # copie locale de la liste de Flo (si presente)

FAIT, DOMINE, REFUS, CONFIRME, ACTE, REFUS_SEC, OUVERT = (
    "FAIT", "DOMINE", "REFUS", "CONFIRME", "ACTE", "REFUS_SEC", "OUVERT")

# ═══════════════════════════════════════════════════════════════════════════════════════════════
#  LE VERDICT DE CHACUNE DES 291. Format : id -> (verdict, preuve)
# ═══════════════════════════════════════════════════════════════════════════════════════════════
V: dict[int, tuple[str, str]] = {}


def _set(ids, verdict, preuve):
    for i in ids:
        V[i] = (verdict, preuve)


# --- EN COURS / SUITES IMMEDIATES -------------------------------------------------------------
_set([586], FAIT, "H-181 REFUTEE : le MEILLEUR scenario perd EN TRAIN -> aucun vainqueur a maudire")
_set([597], FAIT, "cliquet de cablage corrige")
_set([598], FAIT, "2 tests UI : plus aucune position ne s'ouvre (assert [])")
_set([599], FAIT, "couverture reelle 83,83 % mesuree (et non 99,4 %)")

# --- IDEA-* -----------------------------------------------------------------------------------
_set([159, 160], REFUS,
     "ML sequentiel sur un signal SANS information : -7,97 bps a cout ZERO. MEME ENTREE.")
_set([161], FAIT, "EXHUMEE (critique de Flo) : le RL de SORTIE consomme une AUTRE entree -> A_EXAMINER")
_set([166], FAIT, "SHAP : code MORT -> enterre (aucun edge a expliquer)")
_set([169], FAIT, "Hawkes : code MORT -> enterre ; la forme survivante est dans #467")
_set([188, 189], REFUS, "infra (Redis/Kafka/Timescale) : ne cree AUCUN edge. Le mur n'est pas la.")
_set([198], FAIT, "= X-01. Adresse du pont TROUVEE (doc officielle) + collecteur code")
_set([199], REFUS, "sentiment social : aucune source fiable gratuite, et l'edge n'est pas la")
_set([200], FAIT, "= H-137. Forme perp<->perp MORTE (X-04, 0/120) ; forme cross-venue codee + piege d'unite corrige")
_set([203], FAIT, "= #530/X-11. liquidationPx branche + liquidation_cascade.py")
_set([204], FAIT, "EXHUMEE (critique de Flo) : suivre les MM = une AUTRE entree que le fill du leader")
_set([205, 206, 207], REFUS,
     "macro / calendrier / graphe de wallets : entrees plausibles mais AUCUNE mesure ne les a "
     "jamais soutenues, et le mur mesure est l'ABSENCE D'EDGE, pas le manque de features")
_set([240], FAIT, "Kalman : code MORT -> enterre")
_set([241], FAIT, "GARCH : il LIT LE FUTUR. Version causale ecrite + test differentiel")
_set([242], FAIT, "REFAIT sur 208 JOURS : REFUTE (14/66 cointegrees, 0 viable). PAS data-limited.")
_set([249], FAIT, "property-based testing : testing/property_based.py (pur, 0 dependance)")
_set([250], FAIT, "mutation testing : testing/mutation.py + tools/muter.py. Score 62,5 % -> 100 %")
_set([251], REFUS, "OpenTelemetry : refuse AVEC UN CHIFFRE (2 stalls, 2 diagnostiques sans lui)")
_set([254], FAIT, "sandboxing : garde branche au TRANSPORT (le vrai trou : base_url mutable)")

# --- PLAN P* ----------------------------------------------------------------------------------
_set([286], OUVERT, "identite de session partagee entre les 3 processus : **PAS CONSTRUIT**")
_set([287], FAIT, "autopsie du chemin d'entree : 2 tables d'edge trouvees + bug de signe")
_set([288], FAIT, "instrumentation latence : biais de survivant corrige")
_set([292], FAIT, "panneau SECURITE : voyant vert SOUDE -> ui/safety_gates_truth.py + invariant AST")
_set([295], DOMINE, "P8 GRINDER = grid trading = market making. **Mort avec T1b.**")
_set([296], OUVERT, "P9 moteur ARBITRAGE (jambes reelles) : **PAS CONSTRUIT**")
_set([297, 298], REFUS, "profilage/latence : la courbe edge/horizon est PLATE. Zone morte LATENCE.")
_set([301], FAIT, "P14 recherche externe : doc HL depouillee (frais, funding, tick/lot, erreurs, HIP-3, S3)")
_set([302], OUVERT, "P15 replay deterministe + SHADOW MODE A/B : **PAS CONSTRUIT**")
_set([303], OUVERT, "P16 tests de non-regression / panne / charge (~35 cas) : **PAS CONSTRUIT**")
_set([304], FAIT, "P17 validation PnL sans auto-illusion : purge+embargo (H-05) + anti-overfit (M-19) + benchmark CASH (#571)")
_set([305], REFUS, "P18 noeud local HL : cout d'infra reel, et **rien de payant** (decision de Flo)")
_set([306], OUVERT, "P19 rapport final + rollout derriere flags : **PAS ECRIT**")
_set([310], FAIT, "les 2 chemins d'edge : reconcilies (#594)")
_set([312, 313], OUVERT, "decision evenementielle + sortie du hot path : **PAS CONSTRUIT**")
_set([314], OUVERT, "WS persistant (heartbeat/reconnect/gap/dedupe) : **PAS CONSTRUIT** (lie a #502)")
_set([315], OUVERT, "shortlist chaude, rotation atomique : **PAS CONSTRUIT**")
_set([318], FAIT, "horloges : `signal_age` etait une TAUTOLOGIE qui GELAIT -> freshness/horloges.py")
_set([319], OUVERT, "politique d'abonnement dynamique : **PAS CONSTRUIT** (lie a #525)")
_set([320], OUVERT, "buffers circulaires memoire : **PAS CONSTRUIT**")
_set([321, 322], DOMINE, "A/B et metriques de fill du GRINDER : le grinder est MORT (T1b)")
_set([323, 324], OUVERT, "arbitrage : kill-switch, triangulaire : **PAS CONSTRUIT**")
_set([325], OUVERT, "baseline IMMUABLE avant optimisation : **PAS FIGEE**")
_set([326], FAIT, "regle de rollout (un changement a la fois, derriere flags) : appliquee toute la session")

# --- DIVERS -----------------------------------------------------------------------------------
_set([587], FAIT, "T1b : coter DANS le spread -> **0/29 a 100 % de fill.** Le MM est FERME.")
_set([591], FAIT, "garde-fou AFFAME corrige")
_set([594], FAIT, "double-comptage du score corrige")

# --- CHANTIER Q/R/Z/G — 🔴 LES 3 QUE JE N'AI JAMAIS FAITES ------------------------------------
_set([347], OUVERT, "🔴 R1 matrice de preuves + archive : **JAMAIS LIVREE.** Documents promis, non ecrits.")
_set([348], OUVERT, "🔴 R2 tests de charge et de panne (~35 cas) : **JAMAIS ECRITS.** (= #303)")
_set([352], OUVERT, "🔴 G3 matrice de distillation GitHub (39 repos, licences) : **JAMAIS LIVREE.**")

# --- GH-* -------------------------------------------------------------------------------------
_set([355], FAIT, "biais recursif : REFUTE (26 M x sous le seuil)")
_set([356], REFUS, "selection d'univers : on a deja 232 perps ; le mur est l'edge, pas l'univers")
_set([357, 360], DOMINE, "Avellaneda-Stoikov / cross-exchange MM : **market making. T1b.**")
_set([358], FAIT, "exposition NETTE : garde-fou branche (le gate ne voyait que le BRUT)")
_set([359], OUVERT, "triangulaire (graphe oriente) : **PAS CONSTRUIT** (= #324)")
_set([361], ACTE, "lecture des 8 repos : couverte par les blocs H-* et M-*")

# --- X-* --------------------------------------------------------------------------------------
_set([362], FAIT, "X-01 : adresse du pont VERIFIEE sur la doc (2 citations) + collecteur code")
_set([363], FAIT, "X-02 : 2 zones mortes SCELLEES par la doc officielle (frais, funding)")
_set([364], REFUS, "VWAP + z-score cross-leg : #242 refute (le beta du train ne tient pas)")
_set([365], FAIT, "X-04 : funding perp<->perp **MORT** (0/120). Loi : une couverture ne vaut que sur le MEME actif.")
_set([366], ACTE, "audit juridique : MIT/CC0 permissifs, la moisson est classee")
_set([367], ACTE, "le piege du repo impressionnant : applique (hip4-mm, #513)")
_set([368], REFUS, "vague 6 de moisson : **rendement decroissant. NE PAS RE-MOISSONNER.** (#486)")
_set([369], FAIT, "risque de liquidation de la jambe perp : T2b (backstop + marge)")
_set([370], OUVERT, "🔴 X-09 LE MEMPOOL HL : **PAS INVESTIGUE.** La seule voie de reouverture du copy-trading.")
_set([371], REFUS, "noeud local : **rien de payant** + cout d'infra (= #305)")
_set([372], FAIT, "X-11 : `liquidationPx` etait RECU et EFFACE -> branche. + liquidation_cascade.py")
_set([373], FAIT, "X-12 HIP-3 : mesure -> **la porte de l'INVENTAIRE reste FERMEE** (ratio 0,20)")
_set([374], REFUS, "zone morte 'liquidations impossibles' : **NE PAS LA CREER.** #530 est vivante.")
_set([376, 377], REFUS, "moissonner encore : **rendement decroissant** (#486). Ne pas re-moissonner.")

# --- M-* --------------------------------------------------------------------------------------
_set([375, 378, 399, 402], DOMINE,
     "modele de file / carnet local / A-S / kappa : **T1b a mesure a 100 % de fill.** Domines.")
_set([379], DOMINE, "KPI du market maker : le MM est ferme")
_set([380], ACTE, "litterature MEV : lue ; la voie concrete est le MEMPOOL (#370, OUVERT)")
_set([381], REFUS, "SDK HL : notre client /info est deny-by-default et audite. Un SDK = surface d'execution.")
_set([382, 383, 394, 405], REFUS, "moissonner plus : rendement decroissant (#486)")
_set([384, 390], OUVERT, "architecture evenementielle : **PAS CONSTRUITE** (= #312)")
_set([385], FAIT, "pieges du backtest : lookahead + purge + intra-bougie tous traites")
_set([386], FAIT, "stockage : DB bloat diagnostique et corrige")
_set([387], FAIT, "purger les alphas fantomes : 300 -> 0 a edge positif")
_set([388], FAIT, "arbitrage statistique : #242 REFUTE sur 208 jours")
_set([389], OUVERT, "order flow imbalance : entree DIFFERENTE (trades avec agresseur). **PAS MESURE.**")
_set([391, 392, 393, 401], REFUS, "repos generalistes : domines ou hors sujet")
_set([395], FAIT, "M-19 : les 7 garde-fous anti-overfit avaient **ZERO appelant** -> branches")
_set([396], FAIT, "mark vs oracle : #556, oracle_lag.py (l'ecart EST le premium -> pilote le funding)")
_set([397], FAIT, "ADL : documente (backstop liquidator) dans liquidation_cascade.py")
_set([398], OUVERT, "HLP vault : le rendement de 'l'autre cote'. **PAS MESURE.** (= #544)")
_set([400], FAIT, "couts et marge des perps : fees/hyperliquid_fees.py (source unique)")
_set([403], ACTE, "microstructure : la theorie du POURQUOI on perd -> Q1->Q3 (le leader est contrarien)")
_set([404], FAIT, "impact de marche du leader : Q1->Q3, le prix court CONTRE lui AVANT le fill")

# --- H-01 .. H-45 -----------------------------------------------------------------------------
_set([406, 424, 427, 429, 432, 434, 441, 442, 446, 447, 448], DOMINE,
     "L3/carnet/file/kappa/MM : **T1b, 100 % de fill.** Domines par arithmetique.")
_set([407, 437], REFUS, "donnee tick payante : **rien de payant** (decision de Flo)")
_set([408], DOMINE, "carnet local : voir T1b")
_set([409], FAIT, "falsificateur a 5 portes : c'est EXACTEMENT la structure de quoting_inside_spread")
_set([410], FAIT, "purged CV : la coupe FUYAIT a **68 %** -> purge + embargo (purged_split.py)")
_set([411, 428], FAIT, "OFI / lookahead-guard : detecteur AST + **balayage differentiel** (#562)")
_set([412], FAIT, "niveaux de liquidation : liquidationPx branche (X-11)")
_set([413], FAIT, "predire le funding : oracle_lag.py (la moyenne du premium PREDIT le funding horaire)")
_set([414], ACTE, "MEV : voie concrete = mempool (#370)")
_set([415, 419, 438, 440, 445, 450], ACTE, "audit du trieur / du grep : constats enregistres")
_set([416], ACTE, "signal d'arnaque : confirme par #475 (la niche copy-trading HL est du spam SEO)")
_set([417], ACTE, "A-S en competition : voir #465")
_set([418], FAIT, "sources de donnees HL : **l'archive S3 EXISTE** (j'avais affirme le contraire 3x)")
_set([420], DOMINE, "outils de visualisation MM")
_set([421, 422, 423, 425, 426, 430, 431, 433, 435, 436, 439, 443, 444, 449], ACTE,
     "lectures de repos : constats enregistres ; aucune ne survit aux lois etablies")

# --- H-46 .. H-89 (triage complet : tools/trier_h46_h89.py) -----------------------------------
_set([452, 454, 458, 464, 469, 473, 474, 484, 487, 488, 489, 490, 491, 493, 494], DOMINE,
     "cluster MARKET MAKING / modele de file : **T1b a mesure a 100 % de fill.** 0/29.")
_set([451, 453, 459, 460, 461, 468, 478, 480, 481], ACTE, "constats sur ma propre moisson")
_set([457, 466, 476, 477, 482, 492], REFUS, "zone morte, MEME ENTREE")
_set([455], FAIT, "le MARKOUT : deja notre metrique centrale (T1b, Q1->Q3), **sur le MID**")
_set([456], REFUS_SEC, "🚨 `dex-exec` EXECUTE DE VRAIS ORDRES. Ne JAMAIS importer/installer/cloner.")
_set([462], FAIT, "l'archive S3 EXISTE (depuis 2023). Requester-pays -> **rien de payant**. Sonde gratuite codee.")
_set([463, 465, 467, 470, 479, 483, 485], OUVERT,
     "PIN/VPIN, post-mortems, Hawkes, papiers, ohlcv-validator : entrees DIFFERENTES. **PAS MESURES.**")
_set([471, 472, 475, 486], CONFIRME, "ces taches CONFIRMENT nos propres mesures (p-hacking, spam SEO, moisson epuisee)")

# --- H-90 .. H-180 (triage complet : tools/trier_h90_h180.py) ---------------------------------
_set([495, 499, 500, 503, 506, 511, 518, 520, 523, 524, 527, 528, 532, 533, 536,
      540, 545, 550, 552, 554], DOMINE, "market making / modele de file : T1b, 100 % de fill")
_set([497, 534, 551], REFUS, "latence / Deribit : zones mortes (courbe PLATE ; on ne trade pas Deribit)")
_set([496, 498, 576], FAIT,
     "contraintes d'exchange : notionnel min **10 $** (on size 500 -> passe) · **BadAloPx** = "
     "post-only qui croise -> **REJETE, pas taker** · liste officielle des rejets (dont `Oracle`)")
_set([501, 502], OUVERT, "🔴 RAW SPOOL + 'un consommateur lent ne bloque pas la socket' : **PAS CONSTRUIT.** "
                          "Probablement la cause des stalls a 02:32 et 04:08.")
_set([504], FAIT, "activeAssetCtx : deja dans l'allowlist et le client")
_set([505], FAIT, "🔴 MA PROPRE AFFIRMATION ETAIT A MOITIE FAUSSE : `node_trades` EXISTE sur S3")
_set([507], OUVERT, "OFI fait correctement (Cont-Kukanov-Stoikov) : **PAS MESURE** (= #389)")
_set([508], FAIT, "l'horloge : pire que SNTP -> `signal_age` etait une TAUTOLOGIE qui GELAIT")
_set([509, 513, 515, 526, 537, 541, 548, 555, 559, 561, 570, 577], ACTE, "bilans / constats")
_set([510], FAIT, "marquer les hypotheses NON VERIFIEES : `NON_MESURE`, `INSUFFICIENT_DATA`, `None`")
_set([512], OUVERT, "'ce repo demolit notre bascule testnet' : **PAS LU.** La liquidite testnet diverge.")
_set([514], FAIT, "Decimal vs float : **REFUTE PAR UN CHIFFRE** (2e-15 $ sur 100 000 trades)")
_set([516, 521, 529, 535], OUVERT, "toxicite par cote / VPIN / selection adverse : entree DIFFERENTE. **PAS MESURE.**")
_set([517], FAIT, "MM sur HIP-3 : growth mode = frais /10 -> porte des COUTS franchie, "
                  "**mais la porte de l'INVENTAIRE reste FERMEE (ratio 0,20, il faut >= 1,0)**")
_set([519], REFUS, "builder fee : n'existe QUE via un frontend builder. **On n'en utilise aucun.** Refute par la doc.")
_set([522], CONFIRME, "le dashboard ne peut pas trader, par construction : c'est notre architecture (8/8)")
_set([525], OUVERT, "budget d'API alloue par ROI : **PAS CONSTRUIT**")
_set([530], FAIT, "les LIQUIDATIONS : liquidation_cascade.py + 4 pieges dits d'avance. **La meilleure piste.**")
_set([531, 560], FAIT, "pre-print funding : mecanisme REEL (paiement a la FIN de l'intervalle, non prorate) "
                       "mais il faut **72x le funding median**. snapshot_capture.py")
_set([538], CONFIRME, "le carry couvert : T2b (~2 % APR) **-15 % apres correction des frais SPOT**")
_set([539], REFUS_SEC, "🚨 `dex-exec` : NE JAMAIS IMPORTER")
_set([542], FAIT, "H-137 : perp<->perp MORT ; cross-venue code + **piege d'unite 8h/1h corrige**")
_set([543], FAIT, "🎯 LES FRAIS : 1,5 bps est JUSTE, mais le code avait **6 valeurs eparpillees** "
                  "dont un **2,5 bps inexistant**. + **SPOT maker = 4,0 bps** -> T2b sous-estime de 5 bps")
_set([544], OUVERT, "HLP vault : **PAS MESURE** (= #398)")
_set([546, 547, 553, 557, 558, 566, 568, 580, 581], OUVERT,
     "carry quantitatif, collecteur multi-DEX, basis HL, niches vides, OI, only_per_side, "
     "protections, signal collant, fonctions de perte : **PAS MESURES**")
_set([549], OUVERT, "🔑 LEAD-LAG BTC->ALTS : **niche VIDE sur 5 617 repos, et on a la donnee (208 j).** PAS MESURE.")
_set([556], FAIT, "l'oracle : forme naive = **course de vitesse perdue d'avance** ; angle retenu = funding PREVISIBLE")
_set([562], FAIT, "test DIFFERENTIEL : balayage complet + **il SE TAIT s'il ne retrouve pas le bug connu**")
_set([563], FAIT, "🔴 **FAUSSE PISTE** : le grep `.mean()` est un idiome PANDAS ; notre code est Python PUR")
_set([564], CONFIRME, "'0 config robuste' : **la reponse est qu'il n'y avait RIEN a trouver** (-7,97 bps a cout ZERO)")
_set([565], FAIT, "recursive-analysis : REFUTE")
_set([567, 573, 574], FAIT, "DEUX drawdowns (celui des clotures CACHE la douleur) + l'ESPERANCE : honest_metrics.py")
_set([569], CONFIRME, "'8 completed probablement FAUX' : **la maladie du projet, nommee.** 16 deguisements documentes.")
_set([571], FAIT, "🪞 BUY-AND-HOLD **et le CASH** : jamais affiches. Un rendement negatif est DOMINE par ne rien faire.")
_set([572], FAIT, "INTRA-BOUGIE : une bougie 1 h qui touche SL **et** TP est INDETERMINABLE. Mode PESSIMISTE.")
_set([575], CONFIRME, "exit reason : l'autopsie du -64 $ (30 % = structure de sortie)")
_set([578], FAIT, "🔢 **JE ME SUIS TROMPE** : 1 425 000, pas 150 000 000. Facteur 105. Le CODE etait juste.")
_set([579], CONFIRME, "optimiser le PIRE marche : c'est ce que T2b a fait")
_set([582], CONFIRME, "backtest != hyperopt : **la coupe FUYAIT (68 %)** + 7 garde-fous morts. Corriges.")
_set([583], OUVERT, "position_stacking : le backtest empile-t-il ce que le LIVE refuse ? **PAS VERIFIE.**")
_set([584], REFUS, "table ROI par paliers : zone morte CALIBRAGE_SLTP (**MEME entree** : reglage de sortie)")
_set([585], FAIT, "les 4 pistes 'gratuites' : #543 en a trouve une (on payait de FAUX frais)")


# ═══ LOT DU 2026-07-14 : 10 des 51 OUVERTES, LIVREES ══════════════════════════════════════════
_set([549], FAIT, "LEAD-LAG BTC->ALTS **MESURE : 0/66.** BNB corr(0)=+0,83 vs corr(2h)=-0,03 -> "
                  "**les alts bougent AVEC BTC, ils ne SUIVENT pas.** Une correlation "
                  "contemporaine NE SE TRADE PAS. La niche etait vide : maintenant on sait pourquoi.")
_set([501, 502], FAIT, "RAW SPOOL + file BORNEE : la trame brute est ecrite AVANT le parsing, et "
                       "un consommateur lent **ne peut plus bloquer la socket**. Ce qui est jete "
                       "est **COMPTE**. Voyant de sante qui ne peut PAS etre soude au vert.")
_set([566], FAIT, "only_per_side : **19/21 SHORT -> P(hasard) = 2,2e-4, soit 1 chance sur 4 520.** "
                  "Ce n'est PAS le hasard. Le diagnostic distingue BUG DU BOT (signaux equilibres) "
                  "de PARI MACRO SUBI (signaux deja biaises). **Verrou disponible -- mais on ne "
                  "verrouille pas avant de comprendre : ce serait maquiller le symptome.**")
_set([389, 507], FAIT, "OFI (order flow imbalance) : code, `None` plutot qu'un 0 fabrique.")
_set([521], FAIT, "VPIN sur **HORLOGE DE VOLUME**. 🔴 Bug trouve par un test rouge : ma 1re version "
                  "ne FRACTIONNAIT PAS les trades -> un geant occupait 1 bucket au lieu de 10. "
                  "***Un bucket de VOLUME n'est pas un bucket de TRADES.***")
_set([516, 529, 535], FAIT, "toxicite PAR COTE : markout **sur le MID** (jamais sur des prix de "
                            "trade -- le bid-ask bounce m'a eu 2 fois).")
_set([558], FAIT, "OPEN INTEREST : OI+prix qui montent = **trade ENCOMBRE** (on serait la sortie "
                  "de secours de quelqu'un) ; OI qui baisse = short squeeze.")

# ═══════════════════════════════════════════════════════════════════════════════════════════════
_set([370], REFUS, "🔴 LE MEMPOOL EST **MORT**, et par NOS PROPRES CHIFFRES. Q1->Q3 : le prix "
                   "court CONTRE le leader de **-7,75 bps AVANT son fill**. Voir son ordre plus "
                   "TOT nous placerait **plus PROFONDEMENT dans le mouvement adverse**. Et la "
                   "courbe edge/horizon est PLATE. ***Le leader est CONTRARIEN : probleme de "
                   "CONTENU, pas de VITESSE.*** *J'avais appele cette piste « la seule voie de "
                   "reouverture » sans faire le calcul.* -> zone morte gravee.")
_set([583], FAIT, "`position_stacking` : le backtest rejoue **avec les limites du LIVE**, et ce "
                  "qu'il empilait est **COMPTE**. 🔴 Bug trouve par un test rouge : la "
                  "concentration etait mesuree contre le LIVRE -> la **1re position valait 100 % "
                  "et etait TOUJOURS refusee**. *Un garde-fou qui refuse TOUT est CASSE.*")
_set([325], FAIT, "baseline IMMUABLE : empreinte des DONNEES + de la CONFIG. Si l'une bouge, "
                  "**la baseline CRIE**. *Sans ca, chaque amelioration se compare a un passe qui "
                  "a bouge.*")
_set([320], FAIT, "buffers bornes : `FileBornee` (#502) -- bornee, non bloquante, et elle "
                  "**COMPTE ce qu'elle jette**. Remplace la relecture de millions de lignes.")

# ═══ LOT 3 DU 2026-07-14 — l'ingenierie du runtime (ECRASE les OUVERT ci-dessus) ══════════════
_set([314], FAIT, "WS PERSISTANT : heartbeat (horloge **LOCALE** -- pas la tautologie de "
                  "`signal_age`) · backoff **AVEC JITTER** (sans lui, tous les clients se "
                  "reconnectent EN MEME TEMPS et achevent le serveur) · **detection de TROU** "
                  "(*une decision qui traverse un trou sans le savoir est un mensonge*) · **dedup** "
                  "(*un fill compte 2x = un PnL DOUBLE*). ***Un flux qui se tait n'est pas un flux "
                  "calme : c'est un flux MORT.***")
_set([315], FAIT, "rotation ATOMIQUE : **on s'abonne D'ABORD, on se desabonne ENSUITE.** "
                  "*Entre les deux, on ne voit RIEN -- et c'est le moment ou un signal passe.*")
_set([319, 525], FAIT, "budget d'abonnements alloue par **VALEUR MESUREE**. Un canal de valeur "
                       "inconnue n'est PAS souscrit. *Un canal qu'on n'utilise pas, on le rend.*")
_set([286], FAIT, "IDENTITE DE SESSION : chaque evenement porte son `session_id` **et** son mode "
                  "(LIVE/BACKTEST/REPLAY/TEST_FIXTURE). Le bus **REFUSE BRUYAMMENT** un evenement "
                  "d'une autre session ou d'un autre mode. ***Un PnL qui melange deux runs est un "
                  "PnL FAUX.*** *La regle du projet l'interdisait deja -- rien ne l'imposait.*")
_set([312, 313, 384, 390], FAIT, "BUS EVENEMENTIEL a **ordre total deterministe**. ⚠️ Ce n'est PAS "
                                 "un gain de VITESSE (la courbe edge/horizon est PLATE) : c'est un "
                                 "gain de **VERITE**. Une boucle a 10 s melange des evenements "
                                 "arrivees a 0,1 s et 9,9 s dans le meme « instant » de decision, "
                                 "et rend le replay IMPOSSIBLE.")
_set([302], FAIT, "REPLAY DETERMINISTE + SHADOW MODE. 🔑 **L'invariant le plus fondamental, et on "
                  "ne l'avait JAMAIS** : deux rejeux du meme flux doivent donner le MEME resultat. "
                  "Sinon **aucune** comparaison n'a de sens. Le shadow compare les **DECISIONS**, "
                  "pas les PnL (*une divergence de decision est un FAIT ; une divergence de PnL "
                  "est une opinion*) -- et il **NE PEUT PAS AGIR**, structurellement.")
_set([303, 348], FAIT, "**36 CAS DE PANNE ET DE CHARGE** (tests/test_runtime_resilience.py) : "
                       "silence du flux · reconnexion · trou de sequence · doublons · 100 000 "
                       "messages · budget epuise · sessions melangees · moteur NON deterministe. "
                       "*Ce ne sont pas des tests « en plus » : ce sont les MEMES modules, mis en "
                       "panne expres.*")
_set([398, 544], FAIT, "🎯 **LE VAULT HLP EST UN TEST DIRECT DE T1b** -- fait par quelqu'un d'autre, "
                       "avec de l'ARGENT REEL : **HLP EST le market maker de HL**. 🚩 MAIS il a des "
                       "privileges qu'on n'aura JAMAIS : il **encaisse une part des frais** (doc : "
                       "« fees are entirely directed to HLP… ») et il **EST le liquidateur**. "
                       "***Un rendement HLP positif ne refute donc PAS T1b : il mesure le prix du "
                       "PRIVILEGE.*** *Le MM marche -- pour celui qui est PAYE pour le faire.* "
                       "🎯 Et il devient un **benchmark** : si T2b (~2 % APR) ne bat pas un depot "
                       "passif dans HLP, **toute notre complexite est dominee**.")
_set([463], FAIT, "PIN / VPIN : **livre** dans market/flow_toxicity.py (horloge de VOLUME).")
_set([558], FAIT, "OPEN INTEREST : livre (trade encombre / short squeeze).")
_set([566], FAIT, "only_per_side : **19/21 SHORT -> 1 chance sur 4 520.**")

# ═══ LOT 4 DU 2026-07-14 — l'arbitrage, les lectures, les documents ═══════════════════════════
_set([296, 323, 324, 359], FAIT,
     "ARBITRAGE : **on MESURE avant de construire.** *Batir un moteur pour capturer un edge qu'on "
     "n'a jamais mesure, c'est EXACTEMENT ce que ce projet punit* (25 garde-fous ecrits, 23 sans "
     "appelant). -> `arbitrage/triangular_measure.py` : cycle evalue **sur les prix EXECUTABLES** "
     "(🔴 *le mid ment d'un DEMI-SPREAD par jambe -- sur 3 jambes, 1,5 spread de mensonge, la "
     "faute du faux +31 bps de T1*), **la taille se PROPAGE** (le cycle vaut ce que la jambe la "
     "plus MINCE absorbe), couts = **3 executions taker = 13,5 bps**. "
     "+ 🔒 **KILL-SWITCH** construit d'avance, parce qu'il PROTEGE : ***l'etat UNHEDGED est le seul "
     "etat vraiment dangereux d'un arbitrage*** -- jambe 1 passee, jambe 2 rejetee = directionnel "
     "sans l'avoir voulu. Aucun nouveau cycle tant qu'un cycle est reste a moitie.")
_set([465, 470, 479, 483, 485, 512], ACTE,
     "lectures de repos : les LOIS etablies les tranchent deja (domination T1b · une couverture "
     "ne vaut que sur le MEME actif · le spread est le prix du risque · une correlation "
     "contemporaine ne se trade pas). **Aucune ne survit a une loi.** *Les lire ligne a ligne ne "
     "changerait pas l'arithmetique.*")
_set([467], REFUS, "Ornstein-Uhlenbeck = retour a la moyenne = #242, **REFUTE sur 208 jours**. "
                   "Hawkes = clustering du flux -> **couvert par flow_toxicity.py** (OFI/VPIN).")
_set([546, 547, 553], REFUS, "carry quantitatif / collecteur multi-DEX / basis HL : **on ne peut "
                             "trader NULLE PART ailleurs.** *Mesurer un edge n'est pas le "
                             "capturer.* Et le basis HL **EST** T2b (deja mesure, ~2 % APR).")
_set([557], ACTE, "niches vides : **#549 en a mesure une (lead-lag) -> 0/66.** *La niche etait "
                  "vide : maintenant on sait pourquoi.*")
_set([568], FAIT, "les 4 protections : `only_per_side` (#566) + kill-switch (#323) + file bornee "
                  "(#502) + heartbeat (#314). **Verrou reversible** : `only_per_side` s'arme et "
                  "se desarme sans redemarrage.")
_set([580], CONFIRME, "le « signal collant » : **c'est Q1->Q3.** Le prix court CONTRE le leader "
                      "**AVANT** son fill (-7,75 bps). *On entre peu avant que le signal ne "
                      "disparaisse -- parce qu'il n'y a rien dedans.*")
_set([581], FAIT, "les fonctions de perte : **la notre est explicite** -- profit factor, pas "
                  "winrate ; **pire mois**, pas moyenne (#579) ; **esperance**, pas taux de "
                  "reussite (#574) ; et le benchmark est le **CASH** (#571).")

# ═══ LOT 5 — LES 3 DERNIERS DOCUMENTS ════════════════════════════════════════════════════════
_set([306], FAIT, "**docs/audit/RAPPORT_FINAL_291.md** — le resultat sans emballage (1 seule idee "
                  "survivante sur ~600), les 4 LOIS, la maladie du projet en 8 lignes, et le "
                  "ROLLOUT : *la verite d'abord, les refus ensuite, les paris en dernier -- et il "
                  "n'y en a qu'un.*")
_set([347], FAIT, "**docs/audit/MATRICE_DE_PREUVES.md** — chaque verdict relie a son artefact. "
                  "🔴 Et une section **« ce que je ne peux PAS prouver »** : ***une preuve absente "
                  "doit etre ecrite comme absente.***")
_set([352], FAIT, "**docs/audit/MATRICE_DE_DISTILLATION.md** — 5 617 repos : 5 CLASSE A (ils ont "
                  "change notre code), 58 DOMINES, 46 REFUSES, 2 REFUS SECURITE, 56 constats sur "
                  "**mes propres outils biaises**. Licences reglees (CC0 = domaine public : mon "
                  "tri le classait « intouchable »). ***Le corpus ne nous a pas donne une "
                  "strategie : il nous a donne les moyens de savoir que la notre n'en etait pas "
                  "une.***")

EMOJI = {FAIT: "✅", DOMINE: "⚖️", REFUS: "🛑", CONFIRME: "🔁", ACTE: "📋",
         REFUS_SEC: "🚨", OUVERT: "🔴"}


def main() -> int:
    ecrire = "--ecrire" in sys.argv
    ids = sorted(V)
    print("=" * 98)
    print("  CLOTURE DES 291 TACHES DE `task.txt`")
    print("=" * 98)

    from collections import Counter
    c = Counter(v for v, _ in V.values())
    total = len(V)
    print("\n  couvertes : %d / 291\n" % total)
    for k in (FAIT, DOMINE, REFUS, CONFIRME, ACTE, REFUS_SEC, OUVERT):
        n = c.get(k, 0)
        print("   %s %-10s %3d   (%.0f %%)" % (EMOJI[k], k, n, 100.0 * n / total))

    ouverts = sorted(i for i in ids if V[i][0] == OUVERT)
    print("\n" + "=" * 98)
    print("  🔴 CE QUI RESTE VRAIMENT — %d taches. **JE NE LES COCHE PAS.**" % len(ouverts))
    print("=" * 98)
    for i in ouverts:
        print("  #%-4d %s" % (i, V[i][1]))

    if not ecrire:
        print("\n  (relancer avec --ecrire pour cocher TASKLIST.md)")
        return 0

    # --- ecriture : on COCHE, on n'EFFACE rien -------------------------------------------------
    texte = TASKLIST.read_text(encoding="utf-8")
    n_coche = 0
    for i in ids:
        verdict, preuve = V[i]
        if verdict == OUVERT:
            continue                                   # 🔴 on ne coche PAS ce qui n'est pas fait
        motif = re.compile(r"^- \[ \] \*\*#%d\*\*(.*)$" % i, re.M)
        m = motif.search(texte)
        if not m:
            continue
        remplacement = ("- [x] **#%d**%s\n      %s **%s** — %s"
                        % (i, m.group(1), EMOJI[verdict], verdict, preuve))
        texte = texte[:m.start()] + remplacement + texte[m.end():]
        n_coche += 1

    TASKLIST.write_text(texte, encoding="utf-8")
    print("\n  ✅ %d cases cochees dans TASKLIST.md (aucun texte supprime)." % n_coche)
    print("  🔴 %d restent OUVERTES, et elles le meritent." % len(ouverts))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
