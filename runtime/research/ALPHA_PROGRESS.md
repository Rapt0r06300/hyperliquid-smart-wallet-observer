# ALPHA PROGRESS — reprise en <2 min

ETAT_GLOBAL  : LAB_READY_DATA_BLOCKED  (aucun DONE_GLOBAL premature ; 0 alpha net-positif prouve)
LAST_COMMIT  : bridge bdc8f6c (tracker) ; sandbox = miroir. Ce run: FIX-16, FIX-17, FIX-34(PARTIAL), FIX-35, FIX-18, FIX-20, FIX-14, FIX-15, FIX-36(PARTIAL), FIX-39(PARTIAL) + trackers (1 tache = 1 commit).
TESTS        : suite recherche verte (unitaire). « vert unitaire » != « execute dans la factory sur vraie data ».
RESULT       : corrections = 26 DONE / 14 PARTIAL / 3 TODO / 7 BLOCKED_EXTERNAL / 5 MORE_DATA / 3 RESEARCH_READY.
NEXT_TASK    : par priorite eco, data-ready d'abord — FIX-34 (finir pf/es par famille: exposer les votes dans ofi/leadlag/mlofi/anticipation) ; FIX-36 (cabler DSR dans le verdict factory + PBO + placebos) ; FIX-39 (appeler mesurer_decay_par_age par famille dans run_factory) ; FIX-10 (cross-venue end-to-end) ; FIX-41 (exit factory) ; FIX-44 (replay=forward end-to-end) ; FIX-26/27 (maker queue/toxicite) ; FIX-50/51 (sizing, portfolio) ; FIX-52/53/54 (cache/streaming/parallel) ; FIX-55/56 (CI observable, fault injection) ; FIX-58 (recette finale BASE/ADVERSE_P95/P99/OPTIMISTIC).
BLOCKERS     : data HF simultanee HL+Binance, node_fills wallets, userTwapSliceFills, L4 intent, multi-venue = collecte cote user. Livrer recorders/scripts prets, statut BLOCKED_EXTERNAL PRECIS, jamais DONE.

## SYNC BRIDGE (important — mecanisme fiable etabli ce run)
- Le repo pousse par Flo = « C:\Users\flo\Desktop\Projet invest » (monte sous /sessions/.../mnt/Projet invest). Le sandbox /home/claude/hypersmart est un miroir.
- `.git/index.lock` du bridge ne peut PAS etre unlink (mount) -> commit par PLUMBING : GIT_INDEX_FILE=/tmp/idx ; git read-tree HEAD ; git add <fichiers> ; write-tree ; commit-tree -p HEAD ; ecrire le hash dans .git/refs/heads/main. (les warnings tmp_obj unlink sont cosmetiques, les objets s'ecrivent.)
- Transfert de contenu sandbox->bridge : NE PAS coller de gros base64/hex (corruption reproductible observee). Utiliser SendUserFile -> device_commit_files (binaire fidele) puis VERIFIER sha256 cote mnt avant de commit-tree. Si 2 commits touchent le MEME fichier, transferer l'etat intermediaire (git show <sha>:path) pour le 1er commit, puis l'etat final pour le 2e.
- Toujours : sandbox commit d'abord (git normal), puis miroir bridge. Jamais git push (Flo pousse).

## Niveaux d'etat (gradue)
LAB_READY_DATA_BLOCKED -> RESEARCH_READY -> OOS_CANDIDATES -> FORWARD_VALIDATED -> ECONOMICALLY_VALIDATED -> DONE_GLOBAL
DONE_GLOBAL interdit tant qu'une dependance essentielle est bloquee. BLOCKED_EXTERNAL n'est JAMAIS DONE.

## Regles (renforcees)
- 1 TASK = 1 COMMIT. Stage uniquement les fichiers de la task. Jamais push. PAPER/READ-ONLY (0 ordre reel, 0 /exchange, 0 cle). Carry/funding = DISABLED_BY_SCOPE.
- Reclasse honnete: helper/interface/unit-test/in-memory/verifier != DONE ; module existant != module execute ; BLOCKED_EXTERNAL != DONE.
- PROMOTE seulement si net>0 & LCB>0 & OOS>0 & forward>0 & couts complets (fees+spread+slippage+latency mesures) & fill/capacity mesures & concentration ok & stat gates & ADVERSE_P95 survit. Jamais fabriquer du vert : un KILL honnete > un faux PROMOTE.

## Fait ce run (preuves)
- FIX-16 : matching horizon Wallet×Binance = point le PLUS PROCHE de T±h (tolerance bornee <=h/2) ; plus jamais un stale de plusieurs secondes rebaptise « horizon ».
- FIX-17 : direction trade = lifecycle × position_side (close/reduce SHORT=BUY, LONG=SELL, flip, side B/A) ; un close n'est plus maquille en follower.
- FIX-34 (PARTIAL) : metriques risque pf/es/drawdown mesurees depuis la distribution + wiring population (pf/es/net/n_ind reels) ; verdict<->net coherent (jamais CANDIDAT net<0). RESTE : exposer les votes dans ofi/leadlag/mlofi/anticipation ; slippage/latency/fill/capacity restent data-BLOCKED.
- FIX-35 : N independant conscient des ENTITES (annoter_entites collapse les wallets co-tradant en une voix ; metaorder prime ; conservateur).
- FIX-18 : dedup des fills par identite d'evenement (event_id/fill_hash/tid/oid, sinon empreinte).
- FIX-20 : discipline DECOUVERTE->FREEZE->OOS dans l'anticipation ; verdict+LCB sur l'OOS disjoint (l'edge doit survivre hors-echantillon).
- FIX-14 : classer_desync (SCHEMA/DUPLICATE/ORDERING/SOURCE_GAP/STALE/BOOTSTRAP/OK ; seuls OK propres).
- FIX-15 : entity fingerprint (coins/taille/cadence) ; clusters_entite unit co-trade timing OU empreinte (une entite = une voix meme sans co-trade au meme instant). Reste 'infra'(IP) = data-BLOCKED.
- FIX-36 (PARTIAL) : Deflated Sharpe Ratio (Bailey-LdP) deflated_sharpe.py — un beau SR parmi 1000 essais devient insignifiant. RESTE : PBO, placebos, cabler dans le verdict factory.
- FIX-39 (PARTIAL) : mesurer_decay_par_age — edge net par age du signal -> half_life/break_even/max_signal_age ; au-dela NO_TRADE. RESTE : appeler par famille dans run_factory.

## Deja PROUVE (ne pas refaire sans nouvelle donnee)
BTC lead-lag KILL ; OFI/microprice L1 gross<cout KILL ; cross-venue basis=out-of-scope ; wallet 0x1e9b +58bps=artefact PUMP ; 27 wallets population=0 candidat ; Wallet×Binance anticipation=MORE_DATA (overlap trop court).
