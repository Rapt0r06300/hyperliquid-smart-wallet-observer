# HyperSmart Wallet Discovery

La discovery combine uniquement des sources locales ou explicitement read-only:

- imports manuels;
- wallets deja stockes;
- evenements explorer normalises;
- evenements WebSocket read-only;
- fills locaux.

Une adresse tronquee ou invalide ne cree pas de wallet exploitable. La discovery produit des candidats pour recherche, pas des ordres.
