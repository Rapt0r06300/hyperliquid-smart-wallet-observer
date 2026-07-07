# HyperSmart Code-First Delivery Report

Generated: 2026-06-02

## Livraison recente

Cette passe ajoute des journaux de simulation exploitables dans :

`C:\Users\flo\Desktop\Projet invest\logs\logs à envoyer`

Objectif : permettre d'envoyer a ChatGPT/Jules un dossier de logs clair pour comprendre
pourquoi la simulation gagne, perd ou refuse une action, sans jamais creer d'ordre reel.

## Fichiers de logs produits

- `simulation_resume_pour_chatgpt.md` : resume lisible en francais pour analyse.
- `simulation_decisions_latest.jsonl` : dernier lot de decisions UI detaillees.
- `simulation_decisions_append_only.jsonl` : historique append-only deduplique des decisions.
- `simulation_snapshot_latest.json` : etat complet de la simulation et du portefeuille virtuel.
- `simulation_export_state.json` : etat interne de deduplication export.
- `cli_simulation_resume_pour_chatgpt.md` : resume CLI.
- `cli_simulation_decisions_latest.jsonl` : decisions CLI.
- `cli_simulation_snapshot_latest.json` : snapshot CLI.

Les fichiers sont texte/JSON/JSONL uniquement. Aucune base SQLite n'est creee dans
`logs à envoyer`.

## Contenu trace

Les logs capturent :

- capital virtuel de depart et equity courante ;
- PnL realise, PnL latent, couts, exposition ouverte ;
- wallet leader, coin, action leader, side, prix, notional ;
- decision locale du bot, statut, raison, edge remaining, degradation de copie ;
- age du signal, consensus wallets, mode de position ;
- notional copie, taille apres action, frais, PnL estime ;
- explication en langage simple pour chaque entree, reduction, fermeture ou refus ;
- rappel de securite : simulation seulement, execution interdite.

## Garde-fous

- Aucun mainnet.
- Aucun endpoint d'ecriture operationnel.
- Aucune signature.
- Aucune cle privee.
- Aucun ordre reel.
- Aucun executor testnet actif.
- Simulation locale uniquement.
- Dashboard read-only.
- Les mentions de securite dans les logs ne sont pas stockees comme endpoint operationnel dans le code source.

## Preuves lancees

- `python -m pytest -q tests/test_hypersmart_no_exchange.py tests/test_hypersmart_paper_no_exchange.py tests/test_hypersmart_simulation_diagnostic_logs.py tests/test_hypersmart_simulation_engine_diagnostic_logs.py tests/test_hypersmart_single_launcher.py tests/test_copy_cli_and_safety.py`
  - Resultat : 21 passed.
- `python -m pytest -q tests/test_hypersmart_*.py`
  - Resultat : 217 passed.
- `python -m pytest -q`
  - Resultat : 497 passed.
- `python -m hyper_smart_observer.app.main --audit-safety`
  - Resultat : OK, matches interdits = 0.
- `python -m hyper_smart_observer.app.main --runtime-check`
  - Resultat : archive_ready True, root archives = 0, warning legacy DB dans logs.
- `python -m hyper_smart_observer.app.main --archive-audit`
  - Resultat : rapport ecrit.
- `python -m hyper_smart_observer.app.main --dashboard-export`
  - Resultat : dashboard exporte.

## Limite connue

`logs\hl_observer.sqlite3` existe encore comme fichier runtime legacy verrouillable. Il
n'est pas supprime brutalement et reste exclu des archives propres. Les nouveaux logs
diagnostiques sont separes dans `logs\logs à envoyer`.

## Utilisation

Pour generer un nouveau lot CLI :

```powershell
python -m hyper_smart_observer.app.main simulate-magic-bot --capital 1000 --scenario conservative
```

Pour envoyer l'etat le plus utile a un autre assistant, joindre le dossier :

`C:\Users\flo\Desktop\Projet invest\logs\logs à envoyer`

