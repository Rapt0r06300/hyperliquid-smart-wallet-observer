# MATRICE DE PREUVES (#347 / R1)

**Règle du document : une affirmation sans artefact citable n'est pas une affirmation. C'est une
opinion.**

Chaque ligne ci-dessous relie **un verdict** à **la chose qui le prouve** — un fichier, un test,
un rapport, un chiffre. *Si la preuve n'existe pas, le verdict est marqué comme non prouvé.*

---

## 1. Les verdicts qui FERMENT des portes

| verdict | chiffre | preuve (artefact) |
|---|---|---|
| **Le copy-trading n'a aucun edge** | −7,97 bps sur **24 133** signaux OOS, **à coût ZÉRO** | mesure Q1→Q3 · `backtesting/horizon_curve.py` |
| **La cause : le leader est CONTRARIEN** | −7,75 bps **AVANT** son fill | markout sur le **MID** (Q1→Q3) |
| **La latence n'a jamais été le problème** | courbe edge/horizon **PLATE** : −3,74 bps à 500 ms, idem à 8 h | `backtesting/horizon_curve.py` |
| **Le market making est FERMÉ** | **0/29** coins viables **à 100 % de remplissage** | `backtesting/quoting_inside_spread.py` |
| **Le funding perp↔perp est MORT** | **0/120** paires · ratio couvert **0,0035** vs nu **0,0036** | `funding/funding_spread_perp_perp.py` |
| **La cointégration est RÉFUTÉE** (pas data-limited) | 14/66 cointégrées, **0 viable**, sur **208 jours** | `backtesting/cointegration_measure.py` · `refaire_242.txt` |
| **Le lead-lag BTC→alts n'existe pas** | **0/66** · BNB : corr(0) = **+0,83** vs corr(2 h) = −0,03 | `backtesting/lead_lag.py` |
| **Le mempool ne rouvrirait rien** | *voir l'ordre plus tôt = plus profondément dans le mouvement adverse* | zone morte `MEMPOOL_VOIR_L_ORDRE_AVANT_EXECUTION` |
| **Le MM sur HIP-3 échoue aussi** | frais ÷10 → porte B franchie ; **ratio inventaire = 0,20** (il faut ≥ 1,0) | `market/hip3_markets.py` |
| **Le biais récursif est réfuté** | écart **26 millions de fois** sous le seuil qui décide | `biais_recursif.json` |
| **`Decimal` ne changerait rien** | **2 × 10⁻¹⁵ $** d'écart sur 100 000 trades | mesure directe |

## 2. Le SEUL verdict positif — et ses réserves

| verdict | chiffre | preuve | ⚠️ réserve |
|---|---|---|---|
| **Le carry HYPE existe** | +33,6 bps dans son **PIRE mois** | `funding/delta_neutral_carry.py` | 7 des 8 candidats meurent |
| **… et il rapporte ~2 % APR, pas 4 %** | la marge est sur **DEUX** jambes | `funding/carry_liquidation_risk.py` | T2b l'a **divisé par deux** |
| **… et encore −15 % après correction** | le **spot** coûte **4,0 bps** maker (perp : 1,5) → aller-retour **18 → 23 bps** | `fees/hyperliquid_fees.py` | **il maigrit à chaque examen** |

> **C'est le seul chiffre positif survivant sur ~600 idées. Il ne promet rien.**

## 3. Les bugs trouvés dans NOTRE code (avec la preuve du bug)

| bug | preuve |
|---|---|
| **« Data-limited » était auto-infligé** | `candleSnapshot(startTime)` **déjà écrit, déjà autorisé** → 18,9 h → **208 jours** |
| **6 fichiers, 4 valeurs de frais**, dont un **2,5 bps inexistant** | grep + grille officielle (`trading/fees`) |
| **La coupe train/test FUYAIT** | **479/700 = 68 %** du train avait sa sortie **dans le test** |
| **7 garde-fous anti-overfit : ZÉRO appelant** | `audit/cablage.py` |
| **`liquidationPx` reçu puis EFFACÉ** | `clearinghouseState` le renvoyait ; le parseur le jetait |
| **Le panneau SÉCURITÉ avait un voyant SOUDÉ** | `UiRiskGate(passed=True)` **en dur** |
| **`signal_age` était une TAUTOLOGIE qui GELAIT** | `context_now = max(timestamps)` → âge **0 par construction** |
| **GARCH lisait le futur** | test **différentiel** : `f(série)[i] ≠ f(série[:i+1])[i]` |
| **« 150 millions » était 1 425 000** | `runtime/scenarios/replay_4h_report.json` — **facteur 105** |
| **Le garde-fou de concentration refusait TOUT** | la 1ʳᵉ position vaut 100 % du livre → toujours refusée |
| **Le VPIN ne fractionnait pas les trades** | un géant occupait 1 bucket au lieu de 10 |

## 4. Ce que je ne peux PAS prouver — et je le dis

| affirmation | pourquoi elle n'est pas prouvée |
|---|---|
| « Le carnet L2 n'a aucune source historique » | 🔴 **FAUX — je l'ai affirmé 3×.** L'archive S3 existe depuis 2023. *(Requester-pays → décision de Flo : rien de payant.)* |
| « Le VPIN filtrerait nos pertes » | **jamais mesuré sur nos données.** Le module existe ; le chiffre n'existe pas. |
| « Les liquidations rapportent » | **jamais mesuré.** 4 pièges identifiés d'avance, aucun réfuté. |
| « HLP rapporte X % » | **jamais mesuré.** Le module attend un run réseau. |
| Les 36 cas de panne | ✅ **écrits et verts** — mais **jamais éprouvés sur une vraie coupure de production**. |

> ***Une preuve absente doit être écrite comme absente. C'est la seule règle de ce document.***

---

**Sécurité : 0 ordre réel · 0 argent réel · 0 clé privée · 0 signature · 0 dépôt/retrait.**
