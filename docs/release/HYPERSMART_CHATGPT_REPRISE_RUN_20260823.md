# HyperSmart — reprise ChatGPT après méga run Codex

Date: 2026-08-23
Branche: `main` uniquement
Mode: PAPER / READ-ONLY

## Objectif

Continuer la feuille de route `HYPERSMART_REPRISE_CHATGPT_3X4_NET_20260822` sans repartir de zéro, avec priorité aux étapes Lead-Lag 51-80 puis Cross-Venue 81-110 et clôture 111-120.

## Travail ChatGPT engagé

1. Ajout d'un diagnostic causal Lead-Lag séparé de la stratégie économique.
2. Seuil diagnostic fixé à 8 bps uniquement pour autopsier les événements déjà observés.
3. Seuil économique V3 maintenu à 20 bps, sans tuning OOS.
4. Classification fail-closed des causes d'absence de carnet :
   - carnet causal exécutable <= 750 ms ;
   - carnet présent mais rejeté par la data gate ;
   - carnet causal trop tardif ;
   - preuve explicite de gap/reconnexion ;
   - aucune observation sans preuve de gap ;
   - loader diagnostic incomplet.
5. Ajout de tests couvrant notamment les délais 2 295 ms et 4 715 ms déjà observés par Codex.
6. Ajout d'un outil autonome `tools/diagnostiquer_lead_lag_causal.py` pour produire une preuve JSON/Markdown sur workspace réel.
7. Déclenchement d'un gros run self-hosted `lead-lag-full` par contrat immuable `control/alina_final_jobs/lead-lag-causal-full-20260823.json`.

## Règles inchangées

- aucune exécution réelle ;
- aucun assouplissement de coût, seuil de sécurité ou preuve ;
- aucun look-ahead ;
- aucune compensation inter-familles ;
- `LIQUIDATABLE_NET >= 4.00 USD` séparément pour Copy-Vault, Lead-Lag et Cross-Venue ;
- OOS, forward post-freeze, placebo, provenance et réconciliation obligatoires.

## Prochaine action après retour runner

Lire l'artifact du run Lead-Lag, déterminer si les événements 8 bps échouent par manque réel de carnet, qualité, gap de collecte ou latence, puis choisir uniquement sur train la prochaine hypothèse multi-actif / exécution avant tout nouveau freeze.
