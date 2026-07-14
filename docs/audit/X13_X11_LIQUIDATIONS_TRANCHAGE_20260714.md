# X-13 tranché + X-11 branché — la carte des liquidations (2026-07-14)

## X-13 : « la chasse aux liquidations est-elle IMPOSSIBLE sur Hyperliquid ? » — NON. Possible.

Verdict rendu **sur pièces**, pas sur opinion :

1. **La donnée existe et on la reçoit déjà** : `clearinghouseState` (appel déjà fait,
   `rest_info_client.py`) rend `liquidationPx` pour chaque position de chaque wallet suivi.
   `market/liquidation_map.py` (livré le 13/07) la parse en refusant d'inventer
   (pas de `liquidationPx` → ligne écartée).
2. **Les liquidations RÉALISÉES sont identifiables** : `position_delta_engine.detect_liquidation`
   lit le champ `liquidation` des fills réels (jamais inféré de la taille).
3. **L'instrument de mesure est prêt** : `backtesting/liquidation_cascade.py` — markout sur le
   MID (le bid-ask bounce a déjà fabriqué deux faux edges), ≥ 20 événements minimum, un markout
   négatif TUE la piste au lieu d'être arrondi vers le haut.

**Donc X-13 ne devient PAS une zone morte.** La piste #530/X-11 reste ouverte — avec ses limites
écrites AVANT la mesure :

- **carte BORGNE** : on ne voit que les wallets qu'on suit → borne basse, jamais image fidèle ;
- **backstop liquidator** HL : absorbe une partie du flux hors carnet, invisible ;
- **le couteau qui tombe** : l'edge n'existe que si le rebond dépasse la continuation
  (question empirique) ;
- **la concurrence** : si c'était gratuit, ce serait déjà ramassé.

## X-11 : le chaînon manquant est BRANCHÉ

Le module lui-même le disait : « l'instrument existe, la mesure PAS — aucun historique ».
L'observer construisait la carte à chaque observation… **et la jetait**.

Livré aujourd'hui :
- `market/liquidation_recorder.py` — persiste chaque snapshot de grappes dans une base SQLite
  DÉDIÉE (`runtime/data/liquidation_map.sqlite3`, séparée : le bloat a déjà tué un run de 48 h),
  estampillé `session_id` (#286). Refuse les grappes illisibles. Résumé honnête :
  `AUCUN_HISTORIQUE_LA_MESURE_EST_IMPOSSIBLE` tant qu'il n'y a rien.
- Câblé dans `mainnet_readonly_observer/observer.py` (jamais bloquant pour l'observation).
- Lecteur : `python -m hl_observer.market.liquidation_recorder --report`.

**Critère de passage à la mesure** (pas de promesse) : quand `--report` montre plusieurs jours
d'historique multi-coins, lancer `liquidation_cascade` ; ≥ 20 événements ; markout MID négatif
= piste morte, on l'enterre avec le chiffre.

## Sécurité
Lecture seule de bout en bout : on parse une réponse qu'on recevait déjà, on écrit un fichier
local. **0 ordre réel, 0 clé, 0 signature.**
