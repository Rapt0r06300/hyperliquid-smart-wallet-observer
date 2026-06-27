# Activer le firehose — en clair, sans jargon

## D'abord : tu n'en as PAS besoin pour que le bot marche

Le bot fonctionne **déjà sans** le firehose : tu lances `LANCER_HYPERSMART.cmd`,
il découvre des wallets et prend des décisions. Le firehose est un **turbo
optionnel** : il sert à voir **tous** les mouvements de **tous** les wallets en
direct (des milliers à la seconde) au lieu de quelques-uns.

👉 Mon conseil honnête : **commence sans**. N'attaque le firehose que si tu es à
l'aise avec un serveur, ou prêt à payer un service. Ce n'est pas obligatoire.

## C'est quoi un « node » (en une phrase)

Un node, c'est **un ordinateur spécial qui possède tout l'historique de dYdX et
le diffuse en direct**. Le firehose lit ce flux. Sans node, pas de flux — et
**ça, c'est une exigence de dYdX**, pas une limite de notre logiciel.

## La partie pas-cliquable (la vérité)

Avoir un node, c'est la **seule étape vraiment technique**, et aucun fichier ne
peut la faire à ta place. Deux façons :

- **A) Louer un serveur (VPS) et y installer le node.** Technique (Linux, en
  ligne de commande), quelques heures de synchronisation, plusieurs dizaines de
  Go d'espace. Guide officiel : https://docs.dydx.xyz/nodes/running-node/setup
  Il faut lancer le node avec l'option **`--grpc-streaming-enabled=true`**.
- **B) Un service de node dédié (payant).** Certains fournisseurs gèrent le node
  pour toi et te donnent une adresse. Note : dYdX **déconseille** les nodes
  publics gratuits pour le streaming, donc c'est généralement un service payant.

Dans les deux cas, tu obtiens au final **une adresse** du type `1.2.3.4:9090`.

## La partie cliquable (ce que j'automatise pour toi)

Une fois que tu as cette adresse :

1. **Double-clique sur `ACTIVER_FIREHOSE.cmd`**.
2. Il installe les outils Python tout seul.
3. Il te demande l'adresse de ton node → tu la colles.
4. Il lance le bot avec le firehose **activé automatiquement**.

C'est tout. Plus rien à faire au runtime : à chaque lancement via ce fichier, le
firehose s'active.

## Comment savoir que ça marche

Dans la page de simulation, regarde le panneau **« État du scan »** (en bas à
droite) : tu verras la ligne **« Firehose node : X fills · Y wallets · Z
consensus »** monter en direct. Si elle bouge, c'est gagné.

## En résumé

| Étape | Qui le fait | Difficulté |
|-------|-------------|------------|
| Faire tourner le bot (sans firehose) | `LANCER_HYPERSMART.cmd` | ⭐ facile |
| Avoir un node (adresse) | toi (VPS ou service payant) | ⭐⭐⭐ technique |
| Activer le firehose une fois le node prêt | `ACTIVER_FIREHOSE.cmd` | ⭐ facile |

Sécurité : tout reste **lecture seule / paper**. On lit le flux du node, on ne
signe rien, aucun ordre réel, aucune clé.
