# Pourquoi la reproduction EXACTE d'un wallet échoue (cadre d'honnêteté copy-trading)

(Inspiré de prediction-market-backtesting — "Why Exact Reproduction Fails".)

Copier un leader **à l'identique est impossible**, et c'est normal. On le reconnaît
ouvertement plutôt que de maquiller les chiffres :

1. **Latence** — on voit le fill du leader avec un délai (~11 s médian en WS public). On entre
   donc à un prix différent. Plus le signal est vieux, plus on "chasse" un mouvement déjà parti.
2. **Slippage & spread** — notre taille traverse le carnet ; le prix d'exécution diffère du sien.
3. **File d'attente (queue)** — un ordre passif ne se remplit pas forcément ; la position dans la
   file change le résultat.
4. **Frais & dégradation de copie** — frais des deux côtés + dégradation : l'edge net se réduit.
5. **Taille/allocation** — on ne réplique pas exactement sa taille ; l'allocation dérive
   (mesurée par `copy_fidelity/balance_replication`).

**Conséquence pratique :** on ne promet jamais le même PnL que le leader. On mesure la
**fidélité de copie** et l'**edge net après tous les coûts**, et on refuse (NO_TRADE) quand la
reproduction serait trop dégradée. Objectif : moins de trades, mais plus propres.
