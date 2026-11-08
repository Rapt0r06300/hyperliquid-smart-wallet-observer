# Nœud Hyperliquid local — fills de TOUS les users, gratuit

> **Pourquoi** : un nœud Hyperliquid écrit en continu `node_fills_by_block` = **tous les fills de tous
> les users**, sans aucun cap (contrairement au WS limité à ~10 users/IP) et **sans coût** (on lit les
> fichiers que NOTRE machine écrit). C'est le levier n°1 pour densifier les jours scoreables du labo.
> **PAPER / lecture seule** : le nœud n'émet aucun ordre, ne détient aucune clé.

C'est la seule pièce des « 100 idées » que **tu** dois lancer (logiciel libre, mais installation côté toi).
Mon lecteur `tools/ingester_node_fills.py` est **déjà prêt** et attend juste le dossier de données.

## 1. Installer le nœud (gratuit, open-source)

Dépôt officiel : `https://github.com/hyperliquid-dex/node`.

**Linux (recommandé — un nœud tourne mieux sous Linux).** Si tu es sous Windows, utilise **WSL2**
(`wsl --install` dans PowerShell admin, puis Ubuntu).

```bash
# 1. Récupérer le binaire du nœud (voir les Releases du dépôt officiel pour la dernière version)
curl -L -o ~/hl-visor https://binaries.hyperliquid.xyz/Mainnet/hl-visor
chmod +x ~/hl-visor

# 2. Configurer le réseau mainnet
echo '{"chain": "Mainnet"}' > ~/visor.json

# 3. Lancer en demandant l'écriture des fills par bloc (la clé pour nous)
~/hl-visor run-non-validator --write-fills
```

> Vérifie toujours la commande exacte et le nom du flag dans le **README du dépôt officiel** : les noms
> peuvent changer de version en version. L'essentiel = activer l'écriture des **fills par bloc**
> (`node_fills_by_block`). Certaines versions écrivent aussi `--write-raw-book-diffs` (carnets L4).

## 2. Où atterrissent les données

Par défaut le nœud écrit sous `~/hl/data/`, avec un dossier du type :

```
~/hl/data/node_fills_by_block/hourly/<date>/<heure>
```

Chaque ligne est un bloc au format API (user + fills). Mon lecteur gère défensivement les variantes
de format (`events:[[user, fill]]`, `fills:[{user,...}]`, liste brute).

## 3. Ingérer dans le coffre / le labo

Une fois que le nœud a tourné un peu (quelques minutes suffisent pour voir des fills) :

```bash
cd "Projet invest"
export PYTHONPATH=src

# Tous les users captés par le nœud -> tape
python tools/ingester_node_fills.py --node-dir ~/hl/data/node_fills_by_block

# …ou filtré sur nos leaders suivis
python tools/ingester_node_fills.py \
  --node-dir ~/hl/data/node_fills_by_block \
  --leaders-file config/copy_vault_leaders.json
```

Sortie : `runtime/data/node_fills_tape.jsonl` (source `NODE_FILLS`, dédupliqué par identité).

Puis, comme pour les autres flux :
1. **Certifier** → `Certificateur Coffre Fort.cmd` (range dans le coffre certifié tier LOCAL).
2. **Réconcilier** (voir `tools/reconcilier_sources.py`) pour mesurer ce que le nœud ajoute vs WS/poll :
   ```bash
   python tools/reconcilier_sources.py \
     --source ws=runtime/data/vault_fills_live.jsonl \
     --source node=runtime/data/node_fills_tape.jsonl \
     --explorer-users runtime/data/explorer_users_decouverts.json
   ```
   → te dit combien de fills le nœud capte que la lane WS a **ratés** (trous), et quels leaders actifs
   restent sans fill.
3. **Enrichir** (`tools/enrichir_fills.py`) pour attacher le contexte marché à chaque fill.

## 4. Notes pratiques (gratuit = ressources locales)

- **Disque** : un nœud consomme de l'espace (fills + éventuels carnets). Surveille `~/hl/data` ;
  purge les vieux dossiers horaires une fois ingérés si besoin.
- **Réseau/CPU** : un nœud non-validateur reste raisonnable, mais laisse-le tourner en continu pour
  couvrir le maximum de blocs. Un `cron`/service qui relance l'ingestion toutes les heures suffit.
- **Rien à pousser** : les données du nœud ne vont JAMAIS sur GitHub (code seul). Elles restent locales
  et passent par le coffre certifié.

## 5. Sécurité (invariants)

- **Non-validateur** : pas de stake, pas de clé de signature, pas d'ordre — lecture pure du réseau.
- Les tapes produites sont marquées `source="NODE_FILLS"` : source de **mesure** (densifie les jours),
  jamais détournée en signal « live » causal côté labo.
- PAPER / lecture seule préservé de bout en bout.
