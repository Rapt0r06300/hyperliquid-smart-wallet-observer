# Recherche externe pour le moteur de découverte (27/11/2026)

Exa était indisponible : son compte n'a plus de crédit (erreur 402), et rien n'a été acheté. La recherche est passée par Tavily et TinyFish.

## Sources lues en entier

### 1. Copie sur Hyperliquid : les effondrements de leaders

**Référence.** *The Limits of Behavioral Early Warning for Copy-Trading Blow-Ups: A Pre-Registered, Full-Universe On-Chain Study (Hyperliquid)*, arXiv 2611.27988v1.

**Méthode.** L'étude part du classement public complet (37 895 adresses) et le gèle au 2025-06-01, sans filtre de survie. Un seuil de « leader digne d'être copié » en garde 10 395. Un détecteur est pré-enregistré, réglé sur une partie de l'échantillon, puis lu une seule fois sur une partie scellée.

**Ce que nous en retenons :**
- **Les signes de comportement ne préviennent presque jamais un effondrement.** Ils précèdent la chute du capital chez 9 % des leaders qui s'effondrent ; 69 % s'effondrent sans aucun signe progressif. Une simple coupure sur la courbe de capital (perte maximale) prévient aussi tôt. C'est une piste à tester chez nous : un « copy-stop » sur le capital du leader, en famille `vault_portfolio`. Elle n'a que 16 jours d'historique aujourd'hui.
- **65 % des chutes de capital apparentes sont des RETRAITS, pas des pertes.** Toute étude sur la courbe de capital d'un vault doit séparer les flux des résultats, sinon elle confond un déposant qui part avec un leader qui perd.
- **L'API publique plafonne l'historique de fills à 10 000 par adresse.** Les épisodes REST de backfill d'un vault très actif peuvent donc manquer le début de son histoire. C'est un biais possible, à mesurer par vault : nombre de fills, et date du plus ancien.

### 2. Le bilan des déposants

**Référence.** Bitquery, *Hyperliquid Vaults: 64% of Wallets Down, HLP Up $140.7M*, situation au 20/11/2026.

**Chiffres clés :**
- 45 275 portefeuilles ont déposé dans des vaults de traders ; 64 % sont en perte, pour −32,3 M$ au total.
- HLP a rapporté +140,7 M$ à ses 94 626 déposants.
- 17 929 portefeuilles ont essayé les deux : 91 % gagnent avec HLP, 62 % perdent avec les traders.
- Les leaders eux-mêmes ont perdu 55,9 M$ sur leur propre mise.

**Lecture.** Ces chiffres confirment, sur l'univers complet, notre verdict du 22/11 (dépôt en vault perdant ; HLP seul prometteur, +230 bps). Ils confirment aussi le premier chiffre du moteur : copier sans filtre ne paie pas les coûts.

## Sources vues seulement par extraits de recherche

Ces sources n'ont **pas** été lues en entier et ne fondent aucune décision :
- *Beyond Anonymous Order Flow: Wallet Identity as a Feature for Short-Horizon Return Prediction* (ACM, Hyperliquid). La page a refusé l'accès automatisé. Son idée, le leader comme capteur du flux d'ordres plutôt que comme modèle à recopier, a orienté la grammaire : suivre ET contrer.
- *An Empty Region of Technical Strategy Space: 18,630 Pre-Registered Variants* (SSRN 7594361). Il explique pourquoi le N du DSR compte TOUS les essais.
- *Who Counts the Trials? A Committed Trial Ledger for Enforcing the DSR* (SSRN 7187319). Il justifie le registre append-only et la pré-inscription avant mesure.
- Deux études arXiv sur les cascades de liquidation (2607.27070, et *Misguided Price Discovery*). Elles signalent que les cascades « endogènes » montrent un ralentissement critique et pas les chocs exogènes. Notre famille `liquidation` couvre 412 jours : c'est une piste à formaliser, pas encore une cellule.

## Ce qui en découle pour le labo

- **Fait :** le juge compte tous les essais et pré-enregistre ; le leader est traité comme un capteur (suivre et contrer).
- **À faire, mesures :**
  1. Plafond de 10 000 fills : compter les épisodes par vault et dater le plus ancien.
  2. Copy-stop sur le capital du leader, flux séparés, quand `vault_portfolio` aura au moins 30 jours.
  3. Dimension « cascade » à partir de la famille `liquidation`.
- **Écarté :** surveiller le comportement d'un leader pour prévenir son effondrement. L'étude 1 le réfute sur l'univers complet.
