# CCXT Universe Scout — Design

## But

Étendre la découverte de marchés d’Alina avec CCXT, sans utiliser CCXT dans le hot path ni donner une fausse impression d’exploitabilité temps réel.

## Architecture

`CCXTUniverseScout` charge uniquement les marchés publics des venues configurées, via une fabrique injectable. Chaque marché devient un enregistrement canonique (`venue`, symbole exchange, base, quote, type, spot/perp/future, actif, linéaire/inverse, settle, taille de contrat, timestamp, source). Un échec reste isolé à sa venue, avec timeout et tentatives bornées.

Le résultat agrège les marchés par coin, expose les seuils multi-venues, le coverage, les statuts/erreurs et le diff contre le snapshot JSON précédent. Le snapshot est remplacé atomiquement seulement après un scan global terminé.

## Frontière native

Le registre natif explicite reste `hyperliquid`, `binance`, `bybit`, `okx`. Un marché CCXT sur une autre venue est `DISCOVERY_ONLY`; il ne peut jamais alimenter directement `NativeVenueCoordinator`, Cross-Venue ou Lead-Lag. Un candidat n’est `NATIVE_ELIGIBLE` que pour ses venues possédant un collecteur natif.

## Interface

Une commande `discover-ccxt-universe` écrit/affiche le JSON du scout. Les venues par défaut sont limitées à des connecteurs CCXT publics utiles et peuvent être remplacées dans la configuration. Aucune clé, aucun endpoint privé, aucune signature et aucun ordre.

## Vérification

Cinq tests mockés couvrent la normalisation d’un perp, l’agrégation multi-venues, la détection d’un nouveau marché, l’isolation d’une panne de venue et `DISCOVERY_ONLY` sans collecteur natif.
