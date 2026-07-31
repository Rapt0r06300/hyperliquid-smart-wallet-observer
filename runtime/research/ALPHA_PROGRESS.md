# ALPHA PROGRESS — reprise en <2 min

CURRENT_TASK : (aucune en cours — P2 terminee MORE_DATA)
LAST_COMMIT  : 039b440 (P2 Wallet x Binance anticipation)
TESTS        : suite recherche verte (OFI/wallet/factory/mlofi/population/L4/run_factory/anticipation)
RESULT       : 0 candidat net-positif prouve. P13 a CORRIGE la selection (min->max) + registre append-only + hashes. P2 = MORE_DATA (donnees non simultanees).
NEXT_TASK    : P14 (source UNIQUE de couts, supprimer hardcodes 9/3) -> P50 (classifieur basis vs latency) -> P44/P45 (early-stop + multiple-testing). Toutes data-ready, cheap, durcissent la factory.
BLOCKERS     : le VRAI deblocage = collecte HF SIMULTANEE cote user (fills wallet + Binance BBO + L2 multi-niveaux + node_fills archives + flux L4). Pas de reseau ici.

## Ledger de session (commits, jamais pushes)
- e2247ec  P-SYS  systeme de TASKS P0-P65 (66 tasks)
- 367e576  P13    fix factory: best=max, append-only, trial_id+config/dataset/pipeline hashes
- 039b440  P2     Wallet x Binance anticipation + RUN reel (MORE_DATA, 86 fills/~27min overlap)

## Deja prouve (ne pas refaire sans nouvelle hypothese/donnee)
- BTC Binance->HL taker lead-lag : KILL
- OFI/microprice L1 : gross reel < couts (KILL) ; MLOFI multi-niveaux : math prete, data-limited (MORE_DATA)
- cross-venue gap<cout / gaps persistants = basis (autocorr 0.63-0.94) : KILL / DISABLED_BY_SCOPE
- wallet '+58bps' 0x1e9b : PUMP, 3 votes, concentration 0.79 -> artefact ; population 27 wallets : 0 candidat
- P2 anticipation : MORE_DATA (fills et Binance BBO collectes a des dates differentes)

## Regles actives
- 1 task = 1 commit ; jamais push (l'user pousse) ; commit via plomberie git (mount interdit unlink de index.lock)
- >70% temps sur DATA/EXPERIENCES/OOS/FORWARD/EXECUTION ; PROMOTE seulement si net>0 & LCB>0 & OOS>0 & forward>0 & couts complets
- carry/funding = DISABLED_BY_SCOPE ; PAPER/READ-ONLY (0 ordre reel)
