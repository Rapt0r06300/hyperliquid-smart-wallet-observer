# Audit du coeur d'execution paper canonique - 2026-07-29

## Verdict

Le chemin d'execution local est maintenant explicite et unique :

```text
PaperExecutionIntent
  -> CausalMarketSnapshot
  -> ExecutionPlan
  -> ExecResult
  -> PositionMutation
  -> LedgerEvent
  -> EquityEvent
```

Le coeur est pur et autonome. Il n'importe ni client reseau, ni modele de
signature, ni cle, ni endpoint d'ecriture. Les strategies conservent leurs
propres contrats d'admission et leurs ledgers, mais leur prix de fill passe par
le meme `execute_paper_intent`.

## Causes racines corrigees

1. `PaperEngine` appelait directement `simulate_execution`, tandis que
   `PaperSimConnector` possedait une autre orchestration et un pre-walk du
   carnet.
2. Aucun objet immuable ne reliait l'intention, le snapshot causal, le fill, la
   mutation de position et l'evenement comptable.
3. Une premiere version du nouveau coeur importait les modeles de strategie et
   creait une boucle d'import. Le contrat bas niveau est maintenant autonome.
4. L'ancien test de latence cherchait textuellement l'appel supprime au lieu de
   verifier le nouveau chemin canonique.

## Preuve runtime

Commande :

```text
python tools/audit_canonical_paper_execution.py
  --output runtime/audit/v2_paper_core/canonical_paper_execution.json
```

Entree mesuree :

- coin : `HYPE` ;
- action : `OPEN LONG`, donc execution `BUY` ;
- notional demande : `100 USDC` ;
- carnet L2 etiquete `RECORDED_REAL` ;
- snapshot causal immuable.

Resultat :

- coeur direct : accepte ;
- `PaperEngine` : accepte ;
- `PaperSimConnector` : accepte ;
- prix de fill commun : `100.0600059997` ;
- notional rempli commun : `100 USDC` ;
- cout net : `6.00059997 bps` ;
- frais : `4.5 bps` ;
- slippage mesure : `1.499925 bps` ;
- `parity=true` ;
- `paper_only=true` ;
- `real_execution=false`.

Le fichier de preuve runtime n'est pas versionne, car il appartient aux
artefacts de session. Le script reproductible, lui, est versionne.

## Tests

Les tests du coeur, des chemins voisins, du ledger et du PnL ont donne :

```text
76 passed
```

Ils couvrent notamment :

- determinisme des identifiants ;
- parite du fill entre trois chemins ;
- mapping `OPEN LONG -> BUY` et `CLOSE LONG -> SELL` ;
- absence d'execution reelle ;
- couts, latence, fills partiels et comptabilite existante ;
- absence de double comptage du PnL.

Commit code : `8cfcb62`.

