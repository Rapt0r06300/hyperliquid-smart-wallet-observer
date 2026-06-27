# Stratégie — Market Making simulé (paper-only)

- **Hypothèse** : un déséquilibre net du carnet (OBI) prédit une dérive directionnelle courte exploitable en quotant autour du mid.
- **Signal** : imbalance bid/ask = (bid_depth − ask_depth)/(bid_depth+ask_depth) au-delà d'un seuil (≥ 0.15).
- **Filtres** : profondeur suffisante (DEPTH_TOO_LOW sinon), spread borné, mid disponible, edge net positif après frais ; fill maker modélisé (queue position → FILLED/PARTIAL/MISSED).
- **Edge attendu** : capture du rebate maker + petite dérive ; sensible à la position dans la file (probabilité de fill).
- **Invalidations** : carnet équilibré (pas de signal), queue trop profonde (MISSED), rebate indisponible (MAKER_REBATE_UNAVAILABLE), volatilité trop élevée.
- **Sécurité** : 100 % simulé, aucun ordre posté réellement (build/sign jamais envoyés). Read-only.
