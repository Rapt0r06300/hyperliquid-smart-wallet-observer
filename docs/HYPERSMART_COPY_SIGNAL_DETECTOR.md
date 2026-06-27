# HyperSmart Copy Signal Detector

Le detector observe des deltas leader et fabrique des `SignalCandidate`
research-only. Un candidat accepte signifie seulement "eligible a une simulation
paper mock USDC locale", jamais une recommandation.

Classification position:

- `0 -> >0`: `OPEN_LONG`;
- `0 -> <0`: `OPEN_SHORT`;
- taille qui augmente dans le meme sens: `INCREASE`;
- taille qui baisse dans le meme sens: `REDUCE`;
- `>0 -> 0`: `CLOSE_LONG`;
- `<0 -> 0`: `CLOSE_SHORT`;
- flip long/short: `UNKNOWN` pour ce batch.

Regle edge:

`edge_remaining_bps` est obligatoire. Si l'edge est absent, negatif ou sous le
seuil, le signal est refuse avec `EDGE_UNMEASURABLE` ou
`EDGE_REMAINING_TOO_LOW`.

Couts inclus:

- retard;
- spread;
- slippage;
- fees;
- liquidite;
- adverse selection;
- crowding;
- funding.

Les sorties/reductions sans position paper correspondante deviennent
`NO_MATCHING_PAPER_POSITION_FOR_CLOSE`.
