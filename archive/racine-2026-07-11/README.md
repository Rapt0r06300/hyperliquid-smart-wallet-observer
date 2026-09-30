# Archive de la racine — 2026-07-11

Ces fichiers encombraient la racine du projet. **Rien n'a ete supprime** : tout est ici, et
l'historique git est conserve (`git log --follow archive/racine-2026-07-11/<fichier>`).

## Pourquoi ils sont partis
- `_go.*`, `_scendb3m.*`, `_sc150_copy.txt`, `_replay_sample.*`, `_replay_4h.*`, `_replay_open.py`,
  `LANCER_REPLAY_OUVERT.cmd`, `STOP_REPLAY.cmd`, `SUIVRE_REPLAY_4H.cmd` :
  pilotes **jetables** du run de replay 4h. **Ce run est termine.** Le moteur de replay lui-meme
  vit dans `src/hl_observer/backtesting/` et n'a jamais dependu de ces scripts.
- `patch_tests.py` : script one-shot de patch de tests.
- `CODEX_GOAL.txt` : remplace par `OBJECTIF.md`.
- `docker-compose.yml` : le projet tourne en local, aucun conteneur.
- `x` : fichier de 1 octet, sans usage.

## Ce qui est RESTE a la racine (et pourquoi)
`LANCER_HYPERSMART.cmd` (le lanceur) · `TEST-AUDIT-complet.cmd` (l'audit) ·
`CREER_ARCHIVE_PROPRE.cmd` (utilise ET teste par `tests/test_hypersmart_archive_hygiene.py`) ·
`whale_cache.db` (lu par `dydx_v4/whale_watchlist.py`) · `CLAUDE.md` / `OBJECTIF.md` / `AGENTS.md` /
`README.md` / `PORTFOLIO*.md` (doc) · `pyproject.toml` / `requirements.txt` / `ruff.toml` / `mypy.ini`
(config) · `.env.example` / `.gitignore` / `.gitattributes`.

Si un de ces fichiers te manque, il est ici : rien n'est perdu.
