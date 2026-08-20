# Politique de sécurité — Alina SmartFlow

## Périmètre

Alina SmartFlow / HyperSmart est un moteur local de recherche et de simulation **paper/read-only** autour de données publiques de marché.

Les invariants suivants sont non négociables :

- aucune exécution d'ordre réel ;
- aucun `/exchange` opérationnel ;
- aucune signature de transaction ;
- aucune clé privée, seed phrase ou mnemonic ;
- `HL_ENABLE_MAINNET_EXECUTION=0` ;
- `HL_ENABLE_TESTNET_EXECUTION=0` dans le runtime officiel ;
- aucune donnée synthétique présentée comme preuve économique réelle.

## Signaler une vulnérabilité

Ne publiez pas de secret, token, donnée privée ni procédure d'exploitation sensible dans une issue publique.

Utilisez en priorité **GitHub Private Vulnerability Reporting / Security Advisory** sur ce dépôt. Le rapport doit préciser :

1. la surface concernée ;
2. le SHA ou la version ;
3. les conditions de reproduction ;
4. l'impact observé ;
5. une reproduction minimale ne nécessitant ni argent réel ni secret.

## Traitement

Une vulnérabilité qui pourrait introduire une surface d'exécution réelle, une fuite de secret, une falsification de PnL ou un contournement d'un garde-fou fail-closed est considérée bloquante.

Aucun correctif n'est déclaré terminé sans test de non-régression et passage des gates de sécurité correspondantes.
