# PROTOCOLE — dispersion de funding entre venues (dernière piste ouverte)

**Écrit le 2026-07-19, AVANT la première donnée.** C'est tout l'objet de ce fichier : fixer le
critère de rejet pendant qu'on ignore encore le résultat. Un seuil décidé après coup n'est pas
un seuil, c'est une justification.

---

## Pourquoi cette piste, et elle seule

Tout le reste est mort, tué par nos propres mesures :

| Piste | Verdict mesuré |
|---|---|
| Copy-trading | −7,97 bps hors échantillon (24 133 signaux) · **reconfirmé le 19/07** par le replay A/B : les deux bras massivement perdants, 2 gates sur 6 |
| Market making | 0/29 |
| Funding perp↔perp, **même** venue | 0/120 |
| Lead-lag BTC→alts | 0/66 |
| Liquidations | inmesurable : le leaderboard = gros comptes peu leveragés, 6 positions sur 697 dans le rayon de 10 % |
| Carry delta-neutre | seul positif — mais **0,82 %/an** au plancher de funding, **sous le cash** |

La dispersion **entre venues** réunit trois conditions qu'aucune autre ne remplit :

1. **un mécanisme réel** — Hyperliquid et Binance ne cotent pas le même funding, et rien ne les
   force à converger : les capitaux ne circulent pas instantanément entre deux venues ;
2. **aucune réfutation** — nous ne l'avons jamais mesurée. Le « 0/120 » portait sur perp↔perp
   **au sein de la même venue**, ce qui est une question différente ;
3. **du code déjà écrit et testé** — `cross_venue_funding`, `cross_venue_position`,
   `multi_venue_funding`, `venue_adapter`, `funding_reconciliation`. Jamais alimentés.

⚠️ **Ce n'est pas une raison d'y croire.** C'est une raison de la *tester*, ce qui n'est pas
pareil. Les cinq autres pistes avaient aussi un mécanisme plausible.

---

## Le critère de rejet, fixé maintenant

La dispersion doit franchir **trois barres**. Une seule ratée = piste enterrée, comme les autres.

### Barre 1 — la dispersion doit dépasser son coût
Un carry cross-venue, c'est **quatre jambes** (ouvrir sur deux venues, fermer sur deux venues),
soit environ **22 bps** l'aller-retour.

> **Rejet si** la dispersion médiane nette, sur les coins observés, ne permet pas d'amortir
> l'entrée en **moins de 168 h (7 jours)**.
>
> Traduction : à 11 bps d'entrée, il faut au moins **0,065 bps/h** de dispersion tenue.

### Barre 2 — elle doit battre notre propre référence
Le carry mono-venue rapporte **0,82 %/an** au plancher. Une piste plus complexe, avec du capital
immobilisé sur deux venues et un risque de transfert, doit faire nettement mieux — sinon elle est
**dominée** par ce qu'on a déjà.

> **Rejet si** le rendement annualisé net est inférieur à **2 %/an**, soit ~2,4× le carry actuel.

### Barre 3 — elle doit persister
Une dispersion qui existe une heure puis disparaît n'est pas capturable : le temps d'ouvrir les
quatre jambes, elle s'est refermée.

> **Rejet si** la dispersion se maintient au-dessus du seuil **moins de 60 %** du temps observé,
> sur au moins **72 h** de données et **5 coins**.

---

## Ce qu'on ne fera pas

* **Aucune exécution réelle.** Lecture seule sur les deux venues, 0 clé, 0 signature. Hyperliquid
  reste la seule venue des décisions paper ; Binance n'est qu'une **source de prix**.
* **Pas de recherche du meilleur coin après coup.** On mesure la médiane de l'univers observé.
  Choisir le gagnant a posteriori, c'est la malédiction du vainqueur (H-181), déjà payée ici.
* **Pas de déplacement des barres.** Si le résultat tombe juste en dessous, la réponse est
  « rejeté », pas « arrondissons ».

---

## Si les trois barres tombent

On l'exploite, en paper, avec le cycle de vie déjà écrit (`cross_venue_position`).

## Si une seule barre échoue

On l'enterre, avec sa tombe et son motif — comme le market making, le lead-lag et le reste.

Et alors la conclusion honnête sera : **ce bot ne produit pas de PnL positif en paper sur les
angles accessibles.** Ce sera un résultat, pas un échec. C'est même le plus utile des deux : il
protège d'un chiffre maquillé qu'on montrerait à quelqu'un qui compte dessus.

*Sécurité : lecture seule. 0 ordre réel · 0 argent réel · 0 clé privée · 0 signature · 0 dépôt/retrait.*
