"""RESEARCH_PARALLEL_V1 — laboratoire de recherche ISOLÉ (Flo 25/07).

Un processus séparé qui ajoute des pistes de recherche EN PARALLÈLE, sans jamais toucher aux stratégies
actuelles (RAW/OOS/MAIN) ni au moteur principal. Tout est cloisonné sous `runtime/research_lab/` : data,
ledgers, positions, rapports, logs, run_id/config_hash/heartbeat/PID propres. Append-only, archives
compressées, aucune donnée valide supprimée. 0 /exchange, 0 clé, 0 signature, 0 ordre réel.

Règle d'or : une panne ou une surcharge du labo NE DOIT JAMAIS ralentir ni arrêter le moteur principal.
Le superviseur isole chaque plugin (try/except par plugin) ; le labo tourne dans un process séparé lancé
par UNE ligne réversible de l'autopilot. Après ça, tout nouveau module passe par le REGISTRE de plugins.
"""
