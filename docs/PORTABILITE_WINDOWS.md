# Portabilite Windows de HyperSmart

## Cible supportee

Le paquet portable cible **Windows 10/11 x64**. Il embarque sa propre copie
officielle de CPython et toutes les dependances necessaires au moteur
Hyperliquid read-only, au dashboard, a la simulation paper locale, au laboratoire
de recherche et aux tests locaux.

Il n'est pas honnete de promettre le meme binaire sur Windows ARM, macOS et Linux.
Le code Python reste multiplateforme en grande partie, mais les lanceurs et ce
runtime embarque sont actuellement testes pour Windows x64.

## Demarrage sur un autre PC

1. Extraire entierement l'archive `HyperSmart_Portable_Windows_x64_*.zip`.
2. Conserver `portable_runtime/` a cote du reste du projet.
3. Double-cliquer sur `LANCER_HYPERSMART.cmd`.

Python n'a pas besoin d'etre installe sur le PC cible. Le lanceur execute d'abord
`tools/portable_env.cmd`, qui place `portable_runtime/python/python.exe` en tete
du `PATH` de cette session uniquement. Tous les chemins applicatifs sont derives
du dossier du lanceur. Le runtime desactive aussi le site utilisateur Python :
un paquet installe ailleurs sur le PC ne peut donc pas masquer une dependance
manquante dans l'archive.

Une connexion Internet reste necessaire pour lire les donnees publiques
Hyperliquid. Ollama reste facultatif et externe au paquet : son absence ne doit
pas bloquer le moteur.

## Construction

Depuis le dossier projet :

```powershell
LANCER_HYPERSMART.cmd portable-install
LANCER_HYPERSMART.cmd portable-check
LANCER_HYPERSMART.cmd portable-build
```

`portable-build` cree l'archive sur le Bureau, jamais dans le projet. Le script :

- utilise un staging temporaire ;
- embarque le runtime Python relocalisable ;
- teste les imports et la CLI depuis le staging ;
- refuse une destination situee dans le projet ;
- verifie l'archive finale ;
- affiche son SHA256.

## Pourquoi les 160+ Go de runtime ne sont pas copies

Au moment de l'audit, les ordres de grandeur etaient :

| Zone | Taille observee |
|---|---:|
| `src + tools + tests + docs` | environ 70 Mo |
| `data/` | environ 26 Go |
| `runtime/` | environ 135 Go |
| `logs/` | environ 6 Go |

Les bases SQLite et JSONL de ces dossiers peuvent etre actives et verrouillees.
Les copier pendant le fonctionnement peut produire un snapshot incoherent.
L'archive portable demarre donc avec un runtime local propre. Cela rend le
programme portable sans mentir sur l'integrite de l'historique.

Pour transporter l'historique, arreter d'abord proprement HyperSmart, puis copier
separement les donnees choisies sur un support suffisamment grand. Ne jamais
copier une base SQLite active. Le modele et les rapports historiques ne sont pas
necessaires au premier demarrage du bot portable.

## Fichiers de portabilite

- `requirements-portable.txt` : dependances du paquet autonome ;
- `tools/install_portable_runtime.ps1` : installation officielle CPython ;
- `tools/portable_env.cmd` : selection relative de Python ;
- `tools/portable_runtime.py` : diagnostic et smoke test ;
- `tools/create_portable_bundle.ps1` : staging, ZIP et verification ;
- `portable_runtime/portable_runtime_manifest.json` : provenance du runtime.

Le runtime embarque est construit depuis la distribution officielle CPython
3.14.2 x64. L'installateur verifie avant extraction le SHA256
`F05E28D161C6B15AF64A7CB7F08B4A22B3A6B03EEE71BAEE24EA557B3BDD5798`.

## Limites et securite

- environnement cible : Windows x64 ;
- aucun `.env`, secret, fichier de cle ou base active n'est inclus ;
- aucune archive imbriquee n'est incluse ;
- aucun ordre reel n'est ajoute par la portabilite ;
- le mode marche reste read-only et la simulation reste locale ;
- le PC cible doit disposer de suffisamment d'espace disque et autoriser les
  connexions sortantes publiques Hyperliquid.

Sécurité : 0 ordre réel · 0 argent réel · 0 clé privée · 0 signature · 0 dépôt/retrait.
