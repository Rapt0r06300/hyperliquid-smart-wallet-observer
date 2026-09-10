# Constitution technique — Alina SmartFlow

> Autorité active pour la roadmap technique cumulative V5/776+.
> Cette constitution ne remplace jamais `SECURITY.md` et ne peut pas assouplir un gate machine du HEAD exact.

## 1. Précédence documentaire

En cas de contradiction, appliquer cet ordre strict :

1. `SECURITY.md` ;
2. `docs/HYPERSMART_CONSTITUTION.md` ;
3. scope et contrats machine du HEAD exact, notamment `schema/active_scope.json`, tests, gates, manifests et registres générés ;
4. règles opératoires actives des agents : `AGENTS.md` et `docs/CODEX_GOAL_RUNBOOK.md` ;
5. lois mesurées : `docs/LOIS_MESUREES.md` ;
6. état descriptif courant : `docs/CURRENT_STATE.md` ;
7. documents historiques, reprises et anciennes roadmaps.

Un document de rang inférieur ne peut ni autoriser une action interdite par un rang supérieur, ni transformer une observation historique en vérité courante.

## 2. Invariants immuables

Alina SmartFlow est officiellement **paper/read-only**. Les invariants suivants sont non négociables :

- `HL_ENABLE_MAINNET_EXECUTION=0` ;
- `HL_ENABLE_TESTNET_EXECUTION=0` ;
- aucune soumission d'ordre réel sur mainnet ou testnet ;
- aucun `/exchange` opérationnel ;
- aucune signature de transaction ;
- aucune clé privée, seed phrase, mnemonic, wallet-connect d'action, dépôt ou retrait ;
- aucun argent réel requis pour développer, tester ou certifier la roadmap technique ;
- aucune donnée synthétique ou fixture présentée comme preuve économique réelle ;
- aucun skip, xfail, exclusion, baisse de couverture, seuil ou gate destiné à fabriquer du vert ;
- `main` est l'unique branche persistante de livraison ;
- un résultat inconnu, stale, incomplet ou non mesurable échoue fermé.

## 3. Scope actif

Les familles économiques actives sont Copy-Vault, Lead-Lag et Cross-Venue/Dislocation. **Carry est historique et non actif.** Une ancienne documentation ne peut pas le réactiver implicitement.

La roadmap technique cumulative V5/776+ est distincte de la mission économique : son Done dépend de l'implémentation, du câblage, des tests et des preuves techniques de ses exigences. Atteindre +4 USD, 3×4 USD ou un PnL positif n'est pas un critère de clôture de cette roadmap technique.

## 4. Contrat agents et parallélisme

Deux plans d'exécution coexistent sans se confondre :

- **Discovery économique** : `docs/CODEX_GOAL_RUNBOOK.md` impose un contrôleur LLM unique pour une même campagne/expérience afin de conserver reproductibilité, attribution des essais et séparation des preuves.
- **Roadmap technique V5/776+** : les sous-agents sont autorisés pour des tâches indépendantes d'audit, code, tests, CI et review. Ils doivent avoir des surfaces disjointes, des checkpoints durables et un writer unique lors de l'intégration sur `main`.

Aucun agent ne peut étendre ses permissions par interprétation d'un document historique.

## 5. Documents historiques et superseded

`CLAUDE.md` est conservé pour provenance historique/compatibilité. Ses addenda relatifs à un `testnet_executor`, à une exécution testnet ou à d'anciennes architectures ne constituent **aucune autorité active**.

Sont également historiques par défaut, sauf référence explicite d'un contrat machine courant : anciens documents `OBJECTIF*`, `ETAT*`, reprises datées, anciennes roadmaps, plans de migration et rapports attachés à un SHA antérieur.

Les informations historiques peuvent servir de preuve de provenance, jamais de permission d'exécution.

## 6. Gate d'autorité documentaire

Le module `hl_observer.ops.document_authority` vérifie automatiquement :

- la présence des documents actifs requis ;
- les marqueurs constitutionnels de sécurité et de précédence ;
- la classification explicite de `CLAUDE.md` comme historique ;
- l'absence de directives d'activation d'exécution réelle dans les documents opératoires actifs.

La suite pytest contient une régression sur le dépôt courant et doit échouer fermée si ce contrat dérive.
