# Scan de mécanismes + contrôle aléatoire — "trouver le meilleur", fait honnêtement (2026-07-10)

> ⚠️ **Aucune promesse.** On classe plusieurs familles de stratégies sur les vrais prix (hors-échantillon
> + coûts réels), on prend "le meilleur", et on le compare au **meilleur pur hasard**. `mechanism_zoo.py`
> (testé). But : montrer *pourquoi* "chercher le meilleur parmi beaucoup" est un piège statistique.

## Classement (15 coins, split 70/30, coût 6 bps, rangé par TRAIN)

| Mécanisme | TRAIN net | TEST net (OOS) |
|---|---|---|
| **buy & hold** | −$29 | **+$18** |
| breakout 40/40 | −$180 | −$128 |
| momentum 40/40 | −$285 | −$150 |
| reversion z2.5 | −$289 | −$123 |
| breakout 20/20 | −$317 | −$126 |
| reversion z2.0 | −$350 | −$138 |
| reversion z1.5 | −$392 | −$159 |
| momentum 20/20 | −$470 | −$275 |
| momentum 40/20 | −$495 | −$223 |

## Contrôle : 50 stratégies ALÉATOIRES
- **0 / 50** sont positives sur le train — trader au hasard perd *systématiquement* (chaque trade paie le spread).
- Meilleur hasard : train −$210 → **test −$96**. Médiane test −$107, max −$40.

## Les 3 leçons (chiffrées)

1. **Tout mécanisme de trading actif perd** ici (momentum, breakout, réversion) — sur le train *et* le
   test. Le "classement du meilleur au pire" range simplement des perdants.
2. **Le seul "positif" est buy & hold (+$18) — et ce n'est pas un edge.** C'est de l'**exposition** au
   marché (beta) dans une fenêtre qui a un peu monté ; il perdrait dans une fenêtre baissière. Il "gagne"
   uniquement parce qu'il **trade le moins** (zéro friction).
3. **Le hasard prouve le fond** : 0/50 positif → l'acte de trader *est* un coût. Sans edge réel, plus
   tu trades, plus tu perds.

## Le piège des comparaisons multiples

« Il faut trouver le meilleur » est l'intuition la plus naturelle — et la plus dangereuse. Si tu testes
assez de stratégies, l'une aura l'air gagnante **par chance**. La seule défense est celle qu'on applique :
juger en **hors-échantillon** et se comparer au **hasard**. Ici, le meilleur mécanisme (OOS +$18, et
c'est du buy&hold) ne se distingue **pas** d'un edge réel — il n'y en a pas à trouver.

## Verdict
Recherche menée jusqu'au bout et honnêtement : copy, calibrage, fraîcheur, maker, grid, funding (éco),
réversion, momentum, breakout, buy&hold, **+ contrôle aléatoire**. Le résultat est **unanime et
désormais méta-prouvé** : sur ce marché, en retail, il n'y a pas d'edge net exploitable après coûts.
Le mieux qu'on puisse faire, c'est *ne pas trader* — ce qui, honnêtement, est la conclusion la plus
précieuse qu'un système de recherche puisse produire.

## Sécurité
✅ 0 ordre réel · 0 argent · 0 clé · 0 signature. Lecture seule, paper-only.
