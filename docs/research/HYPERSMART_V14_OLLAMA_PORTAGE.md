# HyperSmart V14 - Ollama local AI portage

## Sources/patterns portes

- OctoBot: accepte des modeles locaux Ollama pour personnalisation et couts locaux.
- TradingAgents: provider `ollama`, endpoint local `http://localhost:11434/v1`, modele configurable.
- Chainstack web3 AI trading agent: Ollama pour inference locale, confidentialite, zero cout API.
- Manifold bot: check local `http://127.0.0.1:11434/api/tags` et verification qu'un modele est present.
- Awesome OpenClaw: pattern `ollama pull llama3.1` et endpoint OpenAI-compatible local.
- FreqAI/Freqtrade-like: un modele peut noter/filtrer des candidats sur des features, mais ne
  doit pas inventer une entree ni bypasser le risk engine.

## Portage HyperSmart

HyperSmart utilise Ollama comme couche IA locale:

- `tools/diagnose_ollama.ps1` verifie installation, API locale et modeles.
- `tools/install_ollama_optional.ps1` installe Ollama via winget et pull un modele optionnel.
- `src/hl_observer/research/ollama_client.py` centralise `/api/generate`, `/v1/chat/completions`,
  `OLLAMA_BASE_URL`, `OLLAMA_MODEL`, timeout, JSON mode et fallback.
- `src/hl_observer/research/ollama_status.py` expose un statut local.
- `src/hl_observer/research/ollama_advisor.py` analyse les pertes/refus de simulation en francais.
- `src/hl_observer/research/ollama_signal_rater.py` note un candidat en JSON:
  `ai_score`, `confidence`, `veto_recommended`, `reasons`, `adjustments`, `missing_data`.
- `src/hl_observer/research/explain_cli.py` enrichit `runtime/ml/explanations_latest.json`.
- `LANCER_HYPERSMART.cmd` configure `HYPERSMART_V13_OLLAMA_*` et les alias `OLLAMA_*`.

## Passe Codex 2026-06-28

Statut local verifie:

- Ollama installe via `tools/install_ollama_optional.ps1`.
- Modele local tire: `llama3.2:latest`.
- Preflight `run_ollama_preflight()` OK:
  - `native_generate_ok=True`;
  - `openai_compatible_configured=True`;
  - `paper_only=True`;
  - `hot_path=False`;
  - `can_create_trade=False`.
- `runtime/ml/explanations_latest.json` regenere depuis
  `logs/logs a envoyer/simulation_snapshot_latest.json`.
- Copie envoyable creee: `logs/logs a envoyer/hypersmart_ia_explanations.json`.

Correctif important: `src/hl_observer/research/local_llm_explainer.py`
filtre maintenant les sorties Ollama. Si le modele invente un actif, oublie le
symbole observe, parle de conseil financier ou implique un profit garanti, le
dashboard/logs reviennent automatiquement a l'explication deterministe.

Tests de garde-fou ajoutes:

- hallucination d'actif type `Bitcoin Cash (ZEC)` rejetee;
- mauvais symbole rejete;
- Ollama conserve `context_only=True`, `hot_path=False`;
- Ollama ne peut pas creer de trade.

## Etat local installe

Au moment de cette passe:

```text
ollama version: 0.30.11
modele: llama3.2:latest
endpoint natif: http://127.0.0.1:11434/api/generate
endpoint OpenAI-compatible: http://127.0.0.1:11434/v1/chat/completions
```

## Garde-fous

- Ollama n'est jamais le createur d'une entree.
- Ollama peut noter et recommander un veto conservateur, jamais transformer un refus en acceptation.
- Ollama ne cree pas de `PaperIntent` et ne modifie pas le wallet.
- Ollama ne peut pas ouvrir/fermer une position reelle ou paper directement.
- Aucune cle, signature, wallet connect, ordre reel.
- Si Ollama est absent, HyperSmart degrade vers des regles deterministes.

## Variables

```powershell
setx HYPERSMART_V13_OLLAMA_ENABLED 1
setx HYPERSMART_V13_OLLAMA_HOST http://127.0.0.1:11434
setx HYPERSMART_V13_OLLAMA_MODEL llama3.2
setx OLLAMA_BASE_URL http://127.0.0.1:11434
setx OLLAMA_MODEL llama3.2
setx HYPERSMART_V14_OLLAMA_MIN_AI_SCORE 0.62
setx HYPERSMART_V14_OLLAMA_MIN_CONFIDENCE 0.55
```

## Commandes utiles

```powershell
powershell -ExecutionPolicy Bypass -File tools\diagnose_ollama.ps1
powershell -ExecutionPolicy Bypass -File tools\install_ollama_optional.ps1 -Model llama3.2
ollama list
```

## Ce que l'IA aide a faire

- expliquer pourquoi une entree a ete refusee;
- synthetiser pourquoi une session perd de l'argent;
- noter un candidat avec score/confiance;
- recommander un veto si le signal est vieux, peu liquide, trop degrade ou mal documente;
- produire des suggestions de tests/backtests et de seuils.

## Ce que l'IA ne fait pas

- aucune creation de position;
- aucune promesse de PnL;
- aucune cle;
- aucune signature;
- aucun ordre reel;
- aucune decision non tracee.

## Tests passes

```powershell
$env:PYTHONPATH='src'
python -m pytest -q tests\test_v14_ollama_integration.py tests\test_v13_calibration_explainer.py
# 14 passed

python -m pytest -q tests\test_v14_portage_framework_modules.py tests\test_v14_ollama_integration.py tests\test_v14_wallet_mirror_runtime.py tests\test_v12_connectors_research.py tests\test_v13_costs_features_optim.py tests\test_v13_calibration_explainer.py
# 50 passed

python -m hyper_smart_observer.app.main --safety-check
# Safety check: OK

python -m hyper_smart_observer.app.main --audit-safety
# OK, no exchange path, no signature, no operational order, no LLM hot-path
```
