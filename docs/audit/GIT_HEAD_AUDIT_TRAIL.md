# GIT_HEAD_AUDIT_TRAIL

SHA de reprise (reference) : `8e899a20cd05d7b0c689a447f086b0bdae9d18ca`

Ce registre atteste que le travail se poursuit par des COMMITS tracables APRES le SHA de reprise,
et qu'aucun HEAD n'est declare pret sans commits reels derriere lui. Le detail horodate des commits
(SHA + objet) est tenu dans `TACHES_HYPERSMART_V6_COMPLET.md` (sections AVANCEMENT) et dans
l'historique git : `git log 8e899a20..HEAD`. La preuve PUBLIQUE de ces commits suit le push GitHub
(POUSSER-GITHUB-FORCE.cmd) ; la CI liee au HEAD est verrouillee par AUD-042.

Invariant (garde-fou test) : ce registre nomme le SHA de reprise et pointe le journal des commits ;
il rougit s'il est vide ou si le SHA de reprise disparait.
