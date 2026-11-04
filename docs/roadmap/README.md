# Registre local de la roadmap Alina Smart Flow

`ALINA_ROADMAP_3120.md` et `ALINA_ROADMAP_3120.json` sont générés depuis le
fichier source fourni par l'utilisateur avec `tools/import_alina_roadmap_3120.py`.
Ils stabilisent les 3 120 numéros, IDs, titres, priorités et lignes source.

Ce registre est distinct d'Agiflow et ne remplace pas les specs canoniques du
dépôt. Il ne déclare aucune tâche terminée. Un statut `VERIFIED_DONE` exige un
reçu append-only dans `runtime/roadmap/ALINA_ROADMAP_3120.receipts.jsonl` avec
SHA exact, commande, code retour nul, artifact/preuve et résultat vérifiable.

Pour régénérer le registre depuis le fichier reçu :

```powershell
python tools/import_alina_roadmap_3120.py "C:\chemin\vers\ALINA_ROADMAP_3120.md"
```

Pour calculer l'avancement réel :

```powershell
python tools/alina_roadmap_progress.py --code-sha <sha-40-caracteres>
```
