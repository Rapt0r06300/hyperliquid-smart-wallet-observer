# CROSS-VENUE FUNDING — protocole 72 h : **EN ATTENTE D'ÉCHÉANCE**

> **Statut : `MEASUREMENT_IN_PROGRESS`. Aucun verdict n'est écrit ici, et aucun ne doit
> l'être avant l'échéance.** Ce fichier existe pour **figer les critères MAINTENANT**, afin
> qu'ils ne puissent pas être réécrits une fois les résultats connus.

## État de la mesure (2026-07-21, 16 h)

| élément | valeur mesurée |
|---|---|
| série | `runtime/data/dispersion_venues.jsonl` |
| étendue couverte | **48,5 h** sur 72 h |
| **échéance restante** | **~23,5 h** |
| coins suivis | 38 |
| points d'écart de prix exploitables | 912 |
| cadence | passée de 300 s à **60 s** le 21/07 (×5) |

## Critères figés AVANT le résultat (ne pas modifier)

Le protocole conclura `VALIDATED` **si et seulement si** les cinq conditions tiennent
simultanément à l'échéance :

1. **couverture** : ≥ 60 h de série continue, trous cumulés < 10 % ;
2. **volume** : ≥ 2 000 observations d'écart de funding exploitables ;
3. **edge net** : le différentiel de funding, **après** frais des deux venues, spread des
   deux jambes et coût de portage, reste **positif en moyenne** ;
4. **stabilité** : positif sur **les deux moitiés temporelles** de la fenêtre, séparément ;
5. **comparabilité** : même sous-jacent, mêmes conventions de règlement — un écart mesuré
   entre deux instruments qui ne sont pas le même actif ne compte pas
   (loi `couverture_meme_actif`).

Verdicts possibles : `VALIDATED` · `PROMISING_NEEDS_MORE_DATA` · `REJECTED_NEGATIVE_NET` ·
`REJECTED_UNSTABLE` · `INCONCLUSIVE_DATA_GAPS` · `PROTOCOL_INVALID`.

## Faiblesse connue du protocole, déclarée maintenant

L'horodatage **exact** du début n'a pas été figé dans un fichier de protocole au lancement :
les 48,5 h sont déduites de l'étendue du fichier de données, pas d'une déclaration initiale.
Si la série a connu un redémarrage non tracé, la fenêtre réelle peut différer. C'est une
limite du protocole, écrite ici pour ne pas être découverte après coup.

**Conséquence** : si à l'échéance la couverture ne peut pas être prouvée continue, le verdict
sera `INCONCLUSIVE_DATA_GAPS`, pas un résultat.

**Sécurité : 0 ordre réel · 0 argent réel · 0 clé privée · 0 signature · 0 dépôt/retrait.**
