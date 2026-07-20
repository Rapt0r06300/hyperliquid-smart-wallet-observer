# Article X « Loop Engineering » (Roan @RohOnChain, 2M vues) — analyse piste par piste (20/07)

Protocole habituel : lecture INTEGRALE, chaque piste jugee sur son DIFFERENTIEL pour notre
venue/architecture, attention positive, verdicts francs. L'article est bien ecrit et sa
mecanique est saine — mais il decrit un systeme PILOTE PAR LLM ; le notre est un runtime
Python deterministe que l'agent AMELIORE entre les sessions. Ce n'est pas un detail.

| # | Piste de l'article | Chez nous | Verdict |
|---|---|---|---|
| 1 | Automation/heartbeat (cron, /loop) | LANCER + 4 boucles collecteurs + superviseur auto-relance + moteur pollant | DEJA_LA (plus robuste : auto-guerison journalisee) |
| 2 | SKILL.md = manuel + « lessons learned » | CLAUDE.md + memoire + docstrings d'incident ; nos lecons deviennent des TESTS-CLIQUETS | DEJA_LA_EN_PLUS_FORT (un markdown peut etre ignore, un test rouge jamais) |
| 3 | STATE.md survit entre les runs | runtime/data/*.json, manifeste de session, ledger append-only | DEJA_LA |
| 4 | Verifier / maker-checker separe | pipeline de portes (deny-by-default), promotion_gate, audit 173 controles, parite live<->backtest, PBO | DEJA_LA (structurel plutot que statistique) |
| 5 | Worktrees / isolation parallele | modes LIVE/BACKTEST/REPLAY/TEST_FIXTURE (regle dure), shards par PID | DEJA_LA |
| 6 | Connectors qui ENVOIENT les ordres (auto_mode broker) | INTERDIT — paper only, 0 ordre reel, ligne non negociable | SKIP_SECURITE |
| 7 | Stop conditions verifiables (« jamais l'agent dit que c'est fini ») | religion locale : verdicts INSUFFISANT/REJETE aux barres pre-ecrites, canaris | DEJA_LA |
| 8 | 🌟 « chaque perte ecrit une lecon, chaque lecon devient une regle » | existait A LA MAIN (mes autopsies). **PORTE (COPY_ADAPTED)** : `ops/lecons_du_ledger.py` — registre des causes connues (ATTENDU / REPARE+commit date), chaque perte classee CHAQUE MATIN : expliquee ✔ / REGRESSION 🔴 (cause reparee qui revient) / INEXPLIQUEE 🔴 (autopsie due). Section 6 du rapport quotidien. | **IMPLEMENTE** |
| 9 | /goal : iterer la recherche jusqu'a condition externe (ex. gate passe) | le replay A/B + promotion_gate existent ; la BOUCLE qui itere les configs jusqu'au verdict n'est pas cablee | GARDE -> tache dediee |

Difference de fond assumee : l'article met un LLM DANS la boucle d'execution. Nous, jamais —
le runtime est deterministe et teste ; l'agent ecrit du code et des tests ENTRE les sessions.
Sa boucle d'auto-amelioration est neanmoins la bonne idee, et elle est maintenant automatique
cote DETECTION (le maillon qui peut rater une nuit) tout en restant humaine cote REGLE
(une lecon = une autopsie + un correctif + un test, pas une ligne de markdown auto-generee).

Securite : 0 ordre reel · 0 argent reel · 0 cle privee · 0 signature · 0 depot/retrait.
