"""dataset — primitives PURES d'intégrité des jeux de données capturés (pépites 258, 260-265, 278).

Rétention des événements au même timestamp (cache→disk→replay), couverture première/dernière observation,
matrice de couverture par coin×channel, heatmap des trous, versionnage canonique (nouveau parser → nouvelle
version, jamais de modification silencieuse), reproductibilité raw→canonical par hash, corpus golden du parser,
checksum de chunk (distinguer trou de marché de corruption disque). 0 réseau, 0 ordre réel.
"""
