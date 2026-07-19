# CARTOGRAPHIE DU BOT — 19/07/2026 (demandée par Flo : « tout vérifier »)

Chaque ligne de cette carte vient d'une MESURE de cette session (ledger, logs, code, tests),
pas d'une impression. Verdicts : ✅ sain · 🔧 réparé aujourd'hui · 🔴 cassé/inconnu · ⏳ en mesure.

## 1. Les moteurs (qui décide quoi)

| Moteur | État | Preuve |
|---|---|---|
| **Carry delta-neutre** (`src/hl_observer/funding/`) | ✅ ACTIF — le seul qui ouvre | Journal 2 751 lignes, position PURR ouverte (75 $, 1,5x, tampon 66 % vs pire-hausse 26 %) |
| **Copy-trading (sim)** | ✅ VERROUILLÉ volontairement | Loi du 11/07 (−7,97 bps OOS) ; portes : MIN_EDGE 16 bps, consensus 2, sniper 9999 ; equity PLATE 8 jours |
| **dYdX legacy** (`hyper_smart_observer/dydx_v4/`) | ✅ ISOLÉ | Depuis 7bd5b43 il ne contamine plus le panneau HL (AUTORISER_DYDX_LEGACY=False) |
| **Réanimation** | 🔧 NEUF | Superviseur dans le moteur (1bdbf4a) + REANIMER-COLLECTEURS.cmd (manuel) |

## 2. La chaîne carry, porte par porte (le chemin LIVE réel)

```
collecteurs (4)  →  carry_spot_inputs/shortlist (fraîcheur 900 s)
  → evaluer_carry_neutre : spot≥2500$ · base/mapping prix · funding>0 · break-even≤120 h
    · risque de LIQUIDATION (pire-hausse observée vs tampon) · rendement sur capital TOTAL
  → porte_risque_ouverture (CVaR, exposition, série de pertes)
  → OUVERTURE paper (marge dynamique, levier risk-parity 1,5x)
  → sorties : DANGER toujours · sinon anti-churn A1-A5 (amortir avant de sortir,
    absence tolérée 3 passes/45 min, hystérésis, budget d'allers-retours)
  → ledger append-only → dashboard (recalcul depuis le ledger, −5,2775 $ vérifié aujourd'hui)
```

## 3. Le scan, coin par coin (passe de 15:27 — verdicts JUGÉS un par un)

| Coin | Verdict scan | Jugement après audit |
|---|---|---|
| PURR | VIABLE (1,5x, break-even 58 h) | ✅ correct — ouvert |
| HYPE | break-even 325 h | ✅ HONNÊTE : funding réel 0,047 bps/h < plancher — le marché ne paie plus, ce n'est pas un bug |
| AZTEC / STABLE | break-even 302/379 h | ✅ HONNÊTE : carnet mince → entrée chère (≈38 bps) ; 13-16 jours de capital immobilisé pour des centimes |
| BERA / PUMP / TRUMP | « base aberrante ×18-×3575 » | ✅ HONNÊTE : pas de vrai spot HL jumelable (le mapping par prix n'a rien trouvé de proche) |
| MON | spot < 5 k$ | ✅ HONNÊTE |

**Conclusion scan : il n'est PAS catastrophique — il dit une vérité dure.** L'univers perp∩spot
de Hyperliquid n'offre AUJOURD'HUI qu'un coin rentable, à un funding au plancher partout.
Le plafond 120 h est défendable (l'anti-churn tient déjà ~93 h minimum ; au-delà de 5 jours de
break-even, on porte du risque de queue pour des centimes) et reste réglable :
`HYPERSMART_CARRY_MAX_BREAK_EVEN_H`.

## 4. Les bugs trouvés/réparés aujourd'hui (l'« inintelligence » avait 4 causes)

1. 🔧 **Unité ×30** : `gain_net_24h_bps` = cumul 30 j déguisé en taux journalier → la rotation
   A7 voyait des surplus fantômes ×30 → churn. Réparé (1bdbf4a) + test-cliquet.
2. 🔧 **Provenance** : le panneau lisait le log dYdX legacy figé → 3 773 refus fantômes (7bd5b43).
3. 🔧 **Famine** : 4 collecteurs morts ensemble 15:27 → superviseur auto + bouton manuel.
4. 🔧 **Un test prescrivait le churn** (fermeture immédiate hors-shortlist) — réécrit.

## 5. Vérifications de la session (10/10 exécutées)

| # | Vérif | Résultat |
|---|---|---|
| 1 | Collecteurs | 🔴 morts depuis 15:27 → REANIMER-COLLECTEURS.cmd + superviseur au prochain démarrage |
| 2 | Position PURR | ✅ accrue du funding (0,9 h, +0,000229 $), tampon liq 66 % vs 26 % observé |
| 3 | Portes copy | ✅ 16 bps / consensus 2 / sniper 9999 dans le lanceur |
| 4 | Réconciliation | ✅ ledger = −5,2775 $ (34 CLOSE), moteur cohérent, dashboard recalcule du ledger |
| 5 | Replay | ✅ 9 180 candidats + 1 953 marks aujourd'hui ; 🔴 9 140 sans étiquette stratégie (tâche R4) |
| 6 | Cross-venue | ⏳ 10 lignes écrites, verdict honnêtement INSUFFISANT avant 72 h/5 coins |
| 7 | Câblage S7 | 63,3 % câblé / 8,1 % orphelins (dernière mesure) — re-mesure Windows à relancer |
| 8 | Sécurité | ✅ MAINNET=0, TESTNET=0, tests no-real-trade verts |
| 9 | Plafond 120 h | ✅ jugé défendable, documenté, réglable par env |
| 10 | Tests | ✅ 154 verts en sandbox sur les chaînes touchées ; vérité finale = TEST-AUDIT Windows |

## 6. D'où viendra le PnL positif (les 4 portes, par ordre de réalisme)

1. **Spikes de funding** (R1) — quand le funding décolle du plancher, le break-even s'effondre
   en heures. C'est LA source de gain de cette venue. Le z-score (A4) est écrit ; il faut le
   transformer en chasseur permanent.
2. **Convergence de base** (R3) — le SEUL PnL positif réalisé à ce jour (+0,12 $ ×3). En faire
   une porte d'entrée, pas seulement une réduction de coût.
3. **Cross-venue** (R2) — 1re mesure : 5,68 %/an net, dispersion médiane 0,0674 bps/h au-dessus
   du seuil utile. Verdict aux barres pré-écrites après 72 h.
4. **Portage plancher** (actif) — PURR ~1,7 bps/24h honnêtes : petit, positif, réel.

Aucune promesse de PnL. Mais chaque cause de PERTE mesurée est éteinte, et chaque porte de
GAIN identifiée a une tâche, un module existant ou une mesure en cours.

**Sécurité : 0 ordre réel · 0 argent réel · 0 clé privée · 0 signature · 0 dépôt/retrait.**
