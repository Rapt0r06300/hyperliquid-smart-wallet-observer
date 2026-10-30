# Audit des dépendances interdites Copy-Vault

Audit local, déterministe et lecture seule. Aucun paquet n'a été installé et aucun service externe n'a été appelé.

- HEAD local : `39747a53d9ac8698f61065ac4a44919488c36e3f`
- Branche : `main`
- Modules atteignables depuis les quatre lanceurs canoniques : **321**
- Dépendances résolues dans l'environnement courant : **47**
- Fichiers de déclaration/hashés : **7**
- Pins exacts extraits des fichiers de dépendances : **87**
- Audit actif fail-closed : **OUI**

## Résultat actif

Les imports de capacité et les activations de configuration sont bloquants uniquement lorsqu'ils sont atteignables depuis la fermeture des lanceurs canoniques.

Aucun import interdit atteignable ni activation interdite dans les lanceurs canoniques.

## Capacités explicitement bornées

Ces imports sont conservés pour la découverte de marchés uniquement et restent non bloquants après vérification de leur frontière :
- `src/hl_observer/markets/ccxt_universe.py` → `ccxt` : optional discovery-only adapter; no order/execution path

## Présence de paquets sans reachability

Aucun paquet interdit installé n'a été détecté hors fermeture active.

## Constats historiques ou non canoniques

8 constat(s) restent documentés sur des outils/workflows non canoniques; ils ne sont pas traités comme une activation du chemin Copy-Vault actif.

## Empreintes de reproductibilité

| Fichier | Taille | SHA-256 |
|---|---:|---|
| `pyproject.toml` | 1771 | `daf3c2a18a1aa25679326d21dc60d51607255a6b104065d5aa5d527f7a97b1db` |
| `requirements-ci-bootstrap.txt` | 266 | `d711616a3a21d7eff8d303611dc3b926b1d5c9dc5e86a80418454f668c8dad99` |
| `requirements-ci-tools.txt` | 288 | `050e76ef3d8396fab1981041052847fc1f329e9cde8fed0d7f010a88424e77b8` |
| `requirements-portable.in` | 568 | `349fe5b93ede7adac8e7dccb7471b449607199a05354df38d32d26f08bf5bade` |
| `requirements-portable.txt` | 7036 | `7ae0745876ad93fecf19cc5ea3b3834f71470af3db5e9f42661f2ff03862ae5b` |
| `requirements-recherche.txt` | 1174 | `7c44494be33dfab8fd88259a03766363a3088a71e709534d0b45ae6f0c620e27` |
| `requirements.txt` | 652 | `935c8fbf4682cd0817eb7ed6e849645a49a0edb8e9e09a00c6ec92e42edb7d17` |
