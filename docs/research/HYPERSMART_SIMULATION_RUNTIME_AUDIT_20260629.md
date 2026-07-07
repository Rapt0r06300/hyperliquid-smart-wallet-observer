# HyperSmart Simulation Runtime Audit - 2026-06-29

## Resume

Audit cible sur les symptomes utilisateur:

- serveur local `127.0.0.1:8794` parfois inaccessible;
- simulation qui semble sauter ou recycler de vieux etats;
- prix/metagraphe qui ne bougent plus;
- PC ralenti;
- PnL negatif et entrees externes/fusion suspectes;
- doute sur le branchement des profils GitHub externes.

Conclusion courte: le serveur UI n'etait plus lance, mais des boucles auxiliaires IA/stream continuaient de tourner en arriere-plan. En plus, le chemin `fusion_paper_engine_adapter` utilisait un edge fixe et optimiste (`80 bps`) et une profondeur arbitraire pour accepter certains signaux paper. Cela pouvait produire des entrees locales peu fiables, puis du PnL negatif.

## Causes confirmees

| Probleme | Preuve | Correction |
|---|---|---|
| UI 8794 eteinte | `Invoke-WebRequest http://127.0.0.1:8794/api/simulation/status` refusait la connexion | Test UI minimal relance: `UI_HEALTH_OK`; le lanceur reste le point d'entree officiel |
| Auxiliaires orphelins | Processus `tools\ia_train_loop.ps1`, `tools\stream_loop.ps1`, `live-user-fills-stream --duration-seconds 0` encore actifs alors que launcher log disait `launcher_exit` | `LANCER_HYPERSMART.cmd` ne lance plus ces boucles en fenetres separees; `start_hypersmart_simulation.ps1` les gere et les arrete |
| Stream infini | `stream_loop.ps1` lancait `--duration-seconds 0` | Segments bornes par defaut 300s, relance seulement si la session n'est pas arretee |
| IA sur snapshot perime | `hypersmart_ia_train.log` continuait a lire `simulation_snapshot_latest.json` vieux de plusieurs heures | Stop file commun + skip snapshot si age > `HYPERSMART_IA_MAX_SNAPSHOT_AGE_SEC` |
| GitHub/fusion trop optimiste | `fusion_paper_engine_adapter.py` injectait `edge_remaining_bps=80.0`, `spread=1`, `slippage=1`, `top_depth=100000` | Edge derive du consensus reel, scores normalises, tailles/levier lus depuis env launcher |
| Externes GitHub pas tous disponibles | Manifest V24: 34/37 presents; 3 repos `FAILED` car GitHub repond `Repository not found` | Le bridge expose ces profils comme unavailable, pas comme actifs |

## Corrections code

- `LANCER_HYPERSMART.cmd`
  - garde un seul bouton/fenetre visible;
  - expose `HYPERSMART_ENABLE_AUX_IA=1` et `HYPERSMART_ENABLE_AUX_STREAM=1`;
  - ne lance plus `HyperSmart IA` et `HyperSmart Stream` dans deux fenetres separees.

- `tools/start_hypersmart_simulation.ps1`
  - cree `runtime\data\hypersmart_runtime.stop`;
  - nettoie aussi les vieux `ia_train_loop`, `stream_loop`, `live-user-fills-stream`, `explain_cli`;
  - lance IA/stream comme processus caches, suivis et arretes avec `Q`;
  - conserve UI + poller dans le meme cycle de vie.

- `tools/stream_loop.ps1`
  - stop file commun;
  - segments WS bornes (`HYPERSMART_STREAM_SEGMENT_SECONDS`, defaut 300s);
  - plus de `--duration-seconds 0`.

- `tools/ia_train_loop.ps1`
  - stop file commun;
  - sommeil interruptible;
  - skip des snapshots trop vieux.

- `src/hl_observer/paper_trading/fusion_paper_engine_adapter.py`
  - suppression de l'edge fixe 80 bps;
  - edge calcule depuis dominance du consensus + nombre de wallets;
  - refus si consensus trop faible ou signal trop vieux;
  - scores wallet/signal normalises;
  - tailles/levier lus depuis les variables launcher.

## Etat GitHub externe

Manifest: `runtime/research/github_repos_v24/EXTERNAL_REPOS_MANIFEST.json`

- Total: 37 repos demandes.
- Presents: 34.
- Echecs GitHub: 3 (`Repository not found`):
  - `06_composio_polymarket_kalshi_arbitrage_bot`
  - `18_neron888_polymarket_copy_trading_bot`
  - `19_terauss_polymarket_copy_trading_bot`

Important: HyperSmart n'execute pas le code upstream dans le hot path. Les repos restent preserves sous `runtime/research/github_repos_v24`, puis le bridge expose des profils paper locaux. Aucune action externe, aucun ordre reel.

## Tests lances

```powershell
python -m pytest -q tests/test_hypersmart_single_launcher.py tests/test_launcher_guards_match_runtime.py
python -m pytest -q tests/test_fusion_strategy_runtime.py tests/test_ui_simulation_status_fast.py tests/test_fusion_paper_engine_adapter.py tests/test_paper_engine_realized_unrealized_pnl_equity.py
python -m pytest -q tests/test_external_github_strategy_bridge.py tests/test_hypersmart_v19_repo_coverage.py tests/test_hypersmart_v23_portage_docs.py tests/test_no_external_code_copy_license_markers.py
```

Resultat cible observe:

- launcher/tests runtime: OK
- fusion/PaperEngine/UI status: OK
- GitHub bridge/docs/license checks: OK
- UI health local 8794: OK

## Limites restantes

- Le PnL positif ne peut pas etre garanti. Le logiciel doit montrer le vrai resultat paper, y compris les pertes.
- 3 repos externes demandes ne sont pas recuperables depuis GitHub avec les URLs fournies.
- L'IA locale reste en shadow/explication tant que son rapport indique qu'elle ne bat pas la baseline.
- Le scan peut encore etre limite par les sources publiques et les limites Hyperliquid; il ne doit pas contourner les protections reseau.

## Prochaine action conseillee

1. Relancer via `LANCER_HYPERSMART.cmd`.
2. Laisser tourner 10-20 minutes.
3. Verifier que `logs\logs a envoyer` (accent dans le vrai chemin Windows) se met a jour toutes les quelques secondes/minutes.
4. Si PnL negatif, analyser en priorite:
   - trades ouverts par `FUSION_PAPER_ENTRY`;
   - raisons `EDGE_REMAINING_TOO_LOW`, `LIQUIDITY_TOO_LOW`, `COPY_DEGRADATION_TOO_HIGH`;
   - sorties SL/TP vs sorties leader;
   - age reel du signal au moment d'entree.

