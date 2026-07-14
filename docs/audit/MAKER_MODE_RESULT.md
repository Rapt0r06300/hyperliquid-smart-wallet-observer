# Mode MAKER — résultat MESURÉ (2026-07-10)

> ⚠️ **Aucune promesse de PnL.** Simulation paper, fills déterminés par les **vrais chemins de prix**
> enregistrés (`maker_fill.py`, testé). 0 ordre réel. Tranche : `edge≥40 + frais≤10s`, sortie #1.

## Ce qu'on a construit
Une entrée **maker** (ordre limite passif) où le remplissage n'est **pas deviné** : on regarde si le
prix réel vient toucher la limite dans une fenêtre. Ça **mesure** le vrai taux de remplissage ET la
sélection adverse (est-ce qu'on rate les gagnants ?).

## Résultat

| | Taker (réf.) | Maker offset 5 bps |
|---|---|---|
| **TRAIN** | −$357 | **+$71** (fill 92 %) — *mais* les trades manqués valaient +$3.66 vs +$0.14 remplis |
| **TEST (OOS)** | −$8.7 | **−$117** (fill **16 %**) — remplis à −$1.45, manqués à +$0.42 |

## Verdict honnête : le maker ne sauve PAS la stratégie

Sur le **hors-échantillon** (le seul juge qui compte) :
- **Taux de remplissage réel = 16 %.** La plupart des ordres passifs ne se remplissent jamais.
- **Sélection adverse confirmée** : les trades qu'on remplit sont les **perdants** (le prix est revenu
  nous toucher = il partait contre nous), les gagnants (qui filent tout de suite) nous **échappent**.
- Résultat maker OOS = **−$117**, soit **PIRE** que le taker (−$9).

Le +$71 du train était (encore) un mirage : l'OOS le réfute, exactement comme pour tous les autres
réglages testés. **Les astuces d'exécution ne créent pas l'edge qui manque.** Le désavantage du
copy-trading (on voit le trade du leader trop tard) est **structurel**, pas un problème d'exécution.

## Ce que ça vaut

On a **mesuré** — pas deviné — que ce levier ne marche pas, **sans risquer un centime**. C'est un
vrai résultat : une piste éliminée proprement. Le bot fait exactement ce qu'un système honnête doit
faire : refuser de se mentir. **Zéro promesse de PnL a été tenue, aucune n'a été maquillée.**
