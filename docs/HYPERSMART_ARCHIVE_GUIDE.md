# HyperSmart Archive Guide

Objectif: creer une archive source propre sans base SQLite active.

## Regles

- Ne jamais archiver `logs/`.
- Ne jamais archiver `data/`.
- Ne jamais archiver `*.sqlite3`, `*.sqlite3-wal`, `*.sqlite3-shm`, `*.db`, `*.log`.
- Ne jamais zipper une DB active.
- Utiliser le bouton racine `CREER_ARCHIVE_PROPRE.cmd`, ou
  `tools/create_clean_archive.ps1` / `tools/create_clean_archive.py`.
- Ne jamais creer de ZIP/7Z/RAR a la racine du projet.
- L'archive propre doit etre creee sur le Bureau utilisateur.

## Diagnostic

```powershell
python -m hyper_smart_observer.app.main --runtime-check
python -m hyper_smart_observer.app.main --runtime-clean-report
.\tools\find_locked_runtime_files.ps1
```

Le script de diagnostic n'arrete aucun processus. Il montre seulement les processus suspects et rappelle l'usage possible de Sysinternals Handle.

## Archive propre

```powershell
.\tools\create_clean_archive.ps1
```

Ou en double-clic Windows:

```text
CREER_ARCHIVE_PROPRE.cmd
```

L'archive inclut source, docs, tests, outils et exemples de configuration. Elle exclut les fichiers runtime.

Le script PowerShell ne zippe jamais directement la racine. Il cree un dossier de staging temporaire, copie uniquement les chemins versionnables (`src/`, `hyper_smart_observer/`, `config/`, `docs/`, `tests/`, `tools/`, `README.md`, `AGENTS.md`, `requirements.txt`, `pyproject.toml`, `.env.example`, `CREER_ARCHIVE_PROPRE.cmd`), puis genere `Projet_invest_clean_YYYYMMDD_HHMMSS.zip` sur le Bureau.

Apres creation, le zip est relu et refuse si une entree contient `logs/`, `data/`, `.env`, SQLite, WAL/SHM, DB, log ou archive imbriquee. Ainsi, `logs/hl_observer.sqlite3` peut rester verrouille par un processus: le script ne doit jamais le lire ni le copier.

Le script refuse explicitement tout `OutputDir` situe dans le projet. Cette
regle evite les archives sales et les archives imbriquees.

## Commandes CLI utiles

```powershell
python -m hyper_smart_observer.app.main --runtime-check
python -m hyper_smart_observer.app.main --runtime-clean-report
python -m hyper_smart_observer.app.main --archive-audit
python -m hyper_smart_observer.app.main --create-clean-archive --archive-output-desktop
```
