# HyperSmart - preuves HS-070 a HS-100

Date: 2026-07-29

Portee: durcissement de la recherche, du walk-forward, des configurations, des
strategies et de l'attribution comptable. Aucun seuil de strategie n'a ete
abaisse pour embellir le PnL. Les changements restent PAPER/READ-ONLY.

| Exigences | Statut | Preuve principale |
|---|---|---|
| HS-070, HS-071, HS-079, HS-080, HS-081 | DONE | Split train/validation/holdout purge avec embargo; holdout historique marque hypothese; promotion seulement apres forward paper post-freeze, candidat exact et meme moteur d'evenements. |
| HS-072, HS-073, HS-074, HS-077, HS-078 | DONE | Registre global append-only des essais; essais tues/renommes comptes; distribution reelle des Sharpes; PBO prudent sur ex-aequo/identiques; dimensions placebo obligatoires. |
| HS-075, HS-076, HS-083 | DONE | Blacklist exige 30 trades et 3 sessions; projection lineaire de capacite non promotable; objectif net/PF/drawdown sans bonus au nombre de trades. |
| HS-082, HS-086, HS-087, HS-088, HS-096, HS-097, HS-098, HS-099 | DONE | Etats et capacites de strategie explicites; ledgers STRICT/EXPERIMENTAL isoles; funding/carry et edge non empirique en shadow; arbitrage multi-leg diagnostic; profils externes interdits en strict. |
| HS-084, HS-085 | DONE | Valeurs PowerShell/Python alignees; provenance DEFAULT/ENV/CLI et hash de configuration exposes dans le statut runtime. |
| HS-089, HS-090, HS-091 | DONE | Metriques JSON structurees avec session/timestamp/producteur; SLA par composant; texte arbitraire non interprete comme metrique. |
| HS-092, HS-093 | DONE | Runner de production invoque Click directement; exceptions programmeur distinguees des erreurs recuperables. |
| HS-094, HS-095 | DONE | Lock atomique avec identite run_id; heartbeat/liberation proteges; une session terminee ne peut pas etre reprise. |
| HS-100 | DONE | Refs ledger obligatoires: candidate, strategie, famille, instance de position, signal source et execution; valeurs UNKNOWN non utilisees comme identifiants promotables. |

Tests de regression:

- `tests/test_promotion_gate.py`
- `tests/test_anti_overfit_gate.py`
- `tests/test_robustesse_selection.py`
- `tests/test_pnl_improvement_lab.py`
- `tests/test_persistent_poll_runner.py`
- `tests/test_session_identity.py`
- `tests/test_verrou_instance.py`
- `tests/test_v12_strategy_registry.py`
- tests PaperEngine, ledger et profils externes existants

Limite explicite: un holdout historique positif ne constitue jamais une preuve
de rentabilite future. La promotion exige encore un forward paper reel,
post-freeze, specifique au candidat et execute par le meme pipeline.
