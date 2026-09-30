# Audit de la preuve lead-lag gelee - 2026-07-29

## Verdict

`DONE` pour le bloc 9 de la roadmap V2.

Commit de code : `7f750fc` (`fix(lead-lag): make frozen evidence consumable`).

Le producteur offline et le lecteur runtime partagent maintenant exactement le
meme contrat versionne. Un fichier contenant seulement des coins, horizons et
un edge positif ne peut plus autoriser un signal.

## Contrat implemente

- schema `hypersmart.lead_lag_frozen_evidence.v2` ;
- identite SHA-256 du dataset et du pipeline ;
- timestamp de gel UTC durable ;
- coins tests et coins de controle distincts ;
- horizons demandes, observables et non observables ;
- edge net et taille d'echantillon par horizon ;
- cout aller-retour executable ;
- stabilite par periode ;
- intervalle bootstrap par blocs ;
- comparaison au placebo ;
- controles non gagnants ;
- PBO et DSR ;
- frequence des evenements ;
- regimes et IC, ou statut `UNMEASURABLE` explicite ;
- comptage global et idempotent de chaque frontiere temporelle testee ;
- promotion uniquement si tous les criteres requis passent ;
- validation deny-by-default dans le lecteur runtime.

Le chemin officiel `ANALYSER_BACKTESTS_REPLAYS.cmd` appelle maintenant le stage
`lead_lag_shadow` via `hl_observer.ops.lead_lag_evidence`. La preuve n'est donc
plus limitee a un test unitaire.

## Tests

- `49 passed` sur lead-lag, horodatage causal, integration paper et lanceur
  historique ;
- Ruff : `All checks passed` sur le nouveau contrat, le producteur, le stage
  officiel et les tests associes ;
- test producteur-vers-consommateur : le JSON ecrit par `geler_config` est lu
  directement par `signaux_lead_lag` sans traduction intermediaire ;
- test de regression : l'ancien fichier de parametres incomplet est refuse ;
- test global trials : cinq horizons creent cinq essais, un second gel n'en
  duplique aucun.

## Preuve runtime locale

Commande d'analyse :

```powershell
$env:PYTHONPATH='src'
.\portable_runtime\python\python.exe -m hl_observer.ops.lead_lag_evidence `
  --root . `
  --output runtime/audit/v2_lead_lag/lead_lag_shadow.json
```

La tape locale mesure environ `60.6 MB`. Le run a observe cinq coins avec une
cadence HL mesurable et une mediane par coin de `7129.28 ms`.

Verdict :

- statut recherche : `NEED_MORE_DATA` ;
- detail : `aucun horizon observable (HL trop lent / peu de data)` ;
- horizons 50/100/250/500/1000 ms : non mesurables avec cette tape ;
- promotion : `REJECTED`.

Apres gel, le lecteur runtime retourne :

```text
CONFIG_INCOMPLETE / EVIDENCE_NOT_PROMOTED
```

Il n'invente donc ni edge, ni signal, ni PnL.

Rapports runtime :

- `runtime/audit/v2_lead_lag/lead_lag_shadow.json`
- `runtime/audit/v2_lead_lag/lead_lag_shadow_frozen.json`

## Limites honnetes

- la tape actuelle ne permet pas d'evaluer le lead-lag sub-seconde ;
- une source plus dense peut rendre certains horizons observables, mais devra
  repasser tous les controles ;
- l'IC reste non mesurable avec des chocs seulement directionnels ;
- aucun resultat n'autorise une activation automatique.

## Securite

Recherche locale et lecture seule. Aucun ordre reel, aucune route `/exchange`,
aucune cle privee et aucune signature.
