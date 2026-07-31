# ALPHA PROGRESS — reprise en <2 min

ETAT_GLOBAL  : LAB_READY_DATA_BLOCKED  (fini DONE_GLOBAL premature)
CURRENT_TASK : FIX (corrections) — commencer par la Factory + cost/book_walk (data-ready)
LAST_COMMIT  : 7f96e4b (FIX-47 forward persistant) | ce run: A + FIX-06/07/08/09/03/04/47 (1 commit/fix)
TESTS        : suite recherche verte ; MAIS "vert unitaire" != "execute dans la factory sur vraie data"
RESULT       : 0 alpha net-positif prouve. 33 DONE reels (utilitaires), 9 PARTIAL, 13 RESEARCH_READY, 6 MORE_DATA, 5 BLOCKED.
NEXT_TASK    : FIX-01 run_factory execute reellement chaque famille -> trial ou BLOCKED ; FIX-02 coverage chaine (famille->adapter->experience appelee->trial) ; FIX-16 walletxbinance horizon (tolerance autour T+h) ; FIX-17 direction lifecycle ; FIX-44 replay=forward end-to-end. (data-ready d'abord)
BLOCKERS     : data HF simultanee, node_fills, userTwap*, L4, multi-venue = collecte cote user (recorders/scripts a livrer prets, statut BLOCKED_EXTERNAL PRECIS, jamais DONE)

## Niveaux d'etat (gradue)
LAB_READY_DATA_BLOCKED -> RESEARCH_READY -> OOS_CANDIDATES -> FORWARD_VALIDATED -> ECONOMICALLY_VALIDATED -> DONE_GLOBAL
DONE_GLOBAL interdit tant qu'une dependance essentielle est bloquee. BLOCKED_EXTERNAL n'est JAMAIS DONE.

## Regles (renforcees)
- 1 TASK = 1 COMMIT (fini les batches de 6/10). Stage uniquement les fichiers de la task. Jamais push.
- Reclasse honnete: helper/interface/unit-test/in-memory/verifier != DONE ; module existant != module execute.
- >70% temps = DATA/EXPERIENCES/OOS/FORWARD ; <30% helpers sauf blocker direct.
- PROMOTE seulement si net>0 & LCB>0 & OOS>0 & forward>0 & couts complets & latency/fill/capacity mesures & concentration ok & placebos/stat gates & ADVERSE_P95 survit.

## 58 corrections = section "corrections" de alpha_tasks.json (FIX-01..FIX-58), toutes persistantes.
## Faux DONE reclasses: P15/P24/P41/P56/P58/P60/P9/P46=PARTIAL ; P65 verdict corrige ; familles recherche=RESEARCH_READY.

## Deja PROUVE (ne pas refaire sans nouvelle donnee): BTC lead-lag KILL ; OFI L1 gross<cout ; cross-venue basis=scope ; wallet +58bps=PUMP artefact ; 27 wallets=0 candidat.
