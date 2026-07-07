# Audit PnL session 2026-07-03 — gate liquidité inversé + profil V24 perdant

## Constat (session live, serveur laissé ouvert)
- Equity 995.23 / 1000 ; PnL -4.77 USDC (réalisé -4.40, latent -0.37) ; coûts payés 5.10 USDC.
- Profit factor 0.343 (84 gains +1.96 / 124 pertes -5.71). Fees sur closes : 3.75 USDC.
- Réconciliation ledger OK (écart 0.0) — le chiffre est vrai, pas un bug d'affichage.
- Session en `SESSION_HARD_LOSS_HALT` (644 refus), y compris edges 64–68 bps refusés en boucle.
- Entrées : 42 FUSION_DIRECT + 28 FUSION vs 2 consensus replay. Le canal propre était étranglé.

## Causes racines (par ordre d'impact)

### 1. Gate liquidité inversé (`ui/routes.py` ~1088)
`liquidity_score = max(0.2, min(1.0, fill_notional/2500))` : c'est la **taille du fill
du leader**, pas la liquidité du marché. Un clip de 45 USDT sur BTC → 0.2 < seuil 0.22
→ `LIQUIDITY_TOO_LOW`. Observé : **BTC refusé 1472×, ETH 695×, SOL 484×** pendant que
de gros fills sur coins fins passaient. Résultat : le flux consensus (le bon) était
bloqué, le flux fusion direct (min edge 18, sans ce gate) alimentait seul le book.

**Fix** : nouveau module pur `src/hl_observer/markets/realtime_liquidity.py`
(tier marché conservateur : majors 0.92, mid 0.65, inconnus = proxy notional sans
plancher 0.2 ; une mesure réelle fournie prime toujours). Branché dans
`opportunity_metrics` de routes.py. Tests : `tests/test_realtime_liquidity_market_gate.py` (15).

### 2. Stops scalping V24 (SL 55 bps, trailing 35)
Les plus grosses pertes unitaires = `SLTP_STOP_LOSS` (HYPE -0.315/-0.271, ONDO -0.269,
PUMP -0.168…). Gain moyen 0.023 vs perte moyenne 0.046 : les stops se faisaient prendre
par le bruit et le trailing coupait les gains. Re-confirme le diagnostic historique
(profil prouvé = sorties par replay leader, pas de SL/TP serrés).

**Fix (launcher, profil V25)** : SL/TP purement catastrophiques — TP 160, SL 120,
trailing/activation/breakeven 0, min-hold 120 s, catastrophique 180.

### 3. Guards session asphyxiants
Soft 0.50 USDC (0.05 %) et hard 2.50 USDC (0.25 %) : après ~5 stops la session était
morte définitivement (hard halt sans reset intra-session), book gelé qui saigne.

**Fix** : soft 2.50 (0.25 %), hard 10.00 (1 %), `SESSION_LOSS_GUARD_USDC` 0.75→2.50,
min-liquidity des modes recovery 0.55→0.45 (cohérent avec la nouvelle échelle tier).

### 4. Canal fusion direct trop laxiste
Min edge 18 bps vs 28 pour le consensus single-wallet → sélection adverse.
**Fix** : `HYPERSMART_DIRECT_COPY_MIN_EDGE_BPS` 18→28.

## Fichiers modifiés
- `src/hl_observer/markets/realtime_liquidity.py` (nouveau, pur, sans I/O)
- `src/hl_observer/ui/routes.py` (import + calcul liquidity_score, 2 edits chirurgicaux)
- `tools/start_hypersmart_simulation.ps1` (profil V25 : SLTP, guards, min edge)
- `tests/test_realtime_liquidity_market_gate.py` (nouveau)
- `tests/test_hypersmart_single_launcher.py` (asserts profil V25)

## Tests (sandbox, PYTHONPATH=src)
- test_realtime_liquidity_market_gate.py : 15 passed
- launcher/guards/SLTP : 23 passed (1 échec = troncature mount de la vue sandbox,
  fichier réel vérifié sain ligne 200 `read_text(...)`)
- sécurité/foundations/ledger/reconciliation/simulateur : 19 passed
- Vérité complète à rejouer sur Windows : `set PYTHONPATH=src && python -m pytest -q`

## Sécurité
0 ordre réel, 0 /exchange, 0 clé, 0 signature. Changements = scoring paper, env
simulation, tests. Le module neuf est pur (invariant testé : pas de réseau, pas de
mots interdits opérationnels).

## Attendu après relance (aucune promesse de PnL)
Moins d'entrées mais mieux filtrées (consensus débloqué sur majors, fusion durci),
sorties par replay leader au lieu de stops bruités, session qui ne gèle plus à -0.25 %.
À surveiller sur les prochaines sessions : part des closes `SLTP_*` (devrait ≈ 0 hors
catastrophe), refus `LIQUIDITY_TOO_LOW` sur BTC/ETH/SOL (devrait = 0), profit factor.
