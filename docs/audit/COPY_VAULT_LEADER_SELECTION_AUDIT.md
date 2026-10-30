# Audit de sélection des leaders Copy-Vault

Audit local du chemin canonique `src/hl_observer/`, PAPER / READ-ONLY / FAIL-CLOSED.
Les classements publics peuvent découvrir une adresse, mais ils ne constituent pas
une preuve économique et ne peuvent pas geler un candidat.

## Séparation des données

| Champ | Source | Usage autorisé | Usage interdit |
|---|---|---|---|
| `rank` | `LeaderboardRowRecord` / plateforme publique | ordre de découverte ou traçabilité | score économique, gel, champion |
| `pnl_usdc`, `roi_pct` | affichage public | prior de découverte non certifiant | preuve de PnL, gate ou score économique |
| `volume_usdc`, `account_value_usdc` | affichage public | triage de backfill non certifiant | copieabilité prouvée ou sizing |
| `source_confidence_score` | qualité d'extraction | qualité du signal de découverte | preuve de rentabilité |
| `copy_vault_evidence` | replay/backtest Copy-Vault canonique | seule entrée économique de `evaluate_copy_leader_candidate` | remplissage depuis un classement public |

`score_leaderboard_row()` produit désormais explicitement un score de découverte.
`select_copy_leaders()` ne trie plus les candidats par `leaderboard_score` et
`evaluate_copy_leader_candidate()` refuse toute candidature sans preuve Copy-Vault
point-in-time. Le score final, la cohérence, la qualité d'exécution, le drawdown,
la concentration et la fenêtre d'historique viennent uniquement de cette preuve.

## Contrat d'admission économique

Une preuve admissible doit déclarer `MEASURED` ou `PROVEN` et confirmer :

- timestamps et données point-in-time vérifiés ;
- fills et positions vérifiés ;
- replay compatible ;
- coûts nets inclus ;
- splits temporels disjoints ;
- scores économiques finis et bornés.

Toute absence, valeur non finie, plage incohérente ou drapeau faux reste
`UNMEASURABLE`. Les champs sociaux/publics ne sont jamais utilisés comme valeur de
repli.

## Fixtures adversariales vérifiées

`tests/test_copy_leaderboard_autoselect.py` et
`tests/test_leaderboard_candidates.py` couvrent :

- adresse très populaire sans historique Copy-Vault : refus, score nul ;
- rang, ROI et PnL publics manipulés : résultat économique inchangé ;
- rang artificiel et limite top-N : le rang ne départage pas le score économique ;
- preuve manquante ou invalide : refus fail-closed ;
- historique court, concentration extrême et adresse tronquée : refus ;
- preuve mesurée complète : sélection possible uniquement sur ses métriques
  canoniques.

Résultat local : **9 tests ciblés passés**, Ruff vert. Aucun collecteur social n'a
été ajouté et aucun moteur parallèle n'a été créé.
