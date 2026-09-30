import json

from hl_observer.research import advise_json_from_summary, ollama_status, run_ollama_preflight
from hl_observer.research.local_llm_explainer import explain
from hl_observer.research.ollama_advisor import OllamaAdvisorConfig
from hl_observer.research.ollama_client import OllamaClientConfig, config_from_env, generate
from hl_observer.research.ollama_signal_rater import OllamaSignalRaterConfig, rate_signal_candidate


class _FakeResponse:
    def __init__(self, payload: dict, status: int = 200):
        self.payload = payload
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def test_ollama_config_accepts_github_style_env(monkeypatch):
    monkeypatch.setenv("HYPERSMART_V13_OLLAMA_ENABLED", "1")
    monkeypatch.delenv("HYPERSMART_V13_OLLAMA_HOST", raising=False)
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11434")
    monkeypatch.setenv("OLLAMA_MODEL", "llama3.2")

    cfg = config_from_env()

    assert cfg.enabled is True
    assert cfg.host == "http://localhost:11434"
    assert cfg.model == "llama3.2"
    assert cfg.native_host.endswith("11434")
    assert cfg.openai_host.endswith("11434/v1")


def test_ollama_generate_native_stream_false(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout=None):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return _FakeResponse({"response": "analyse offline"})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    cfg = OllamaClientConfig(enabled=True, host="http://127.0.0.1:11434", model="llama3.2", api_style="native")

    result = generate("diagnostic", system="system", config=cfg)

    assert result.text == "analyse offline"
    assert result.used_ollama is True
    assert result.endpoint == "native"
    assert captured["url"].endswith("/api/generate")
    assert captured["body"]["stream"] is False
    assert captured["body"]["model"] == "llama3.2"


def test_ollama_explainer_disabled_never_hot_path(monkeypatch):
    monkeypatch.delenv("HYPERSMART_V13_OLLAMA_ENABLED", raising=False)

    out = explain({"coin": "HYPE", "side": "LONG", "reason": "STALE_SIGNAL"})

    assert out["llm_used"] is False
    assert out["context_only"] is True
    assert out["hot_path"] is False
    assert out["source"] == "regles"


def test_ollama_explainer_rejects_hallucinated_asset_or_profit(monkeypatch):
    import hl_observer.research.local_llm_explainer as explainer

    monkeypatch.setattr(explainer, "ollama_available", lambda *args, **kwargs: True)
    monkeypatch.setattr(
        explainer,
        "_ollama_generate",
        lambda *args, **kwargs: "Vendre le Bitcoin Cash (ZEC) pour realiser un profit.",
    )

    out = explainer.explain(
        {"coin": "ZEC", "side": "SHORT", "reason": "EDGE_OK_FOR_LOCAL_SIMULATION"},
        use_llm=True,
    )

    assert out["llm_used"] is False
    assert out["source"] == "regles"
    assert "Bitcoin Cash" not in out["text"]
    assert "profit" not in out["text"].lower()


def test_ollama_explainer_rejects_wrong_coin(monkeypatch):
    import hl_observer.research.local_llm_explainer as explainer

    monkeypatch.setattr(explainer, "ollama_available", lambda *args, **kwargs: True)
    monkeypatch.setattr(
        explainer,
        "_ollama_generate",
        lambda *args, **kwargs: "Trade BTC LONG ecarte car le signal etait trop vieux.",
    )

    out = explainer.explain({"coin": "HYPE", "side": "LONG", "reason": "STALE_SIGNAL"}, use_llm=True)

    assert out["llm_used"] is False
    assert out["source"] == "regles"
    assert "HYPE" in out["text"]


def test_ollama_advisor_structured_payload_is_advisory_only(monkeypatch):
    def fake_urlopen(request, timeout=None):
        body = json.loads(request.data.decode("utf-8"))
        assert body["format"] == "json"
        return _FakeResponse(
            {
                "response": json.dumps(
                    {
                        "diagnosis": "trop de signaux tardifs",
                        "recommended_adjustments": ["reduire taille"],
                        "missing_data": ["depth"],
                        "tests_to_run": ["backtest frais"],
                        "risk_notes": ["paper only"],
                    }
                )
            }
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    cfg = OllamaAdvisorConfig(enabled=True, host="http://127.0.0.1:11434", model="llama3.2", api_style="native")

    payload = advise_json_from_summary({"net_pnl_usdc": -8, "reason_counts": {"STALE_SIGNAL": 10}}, config=cfg)

    assert payload["used_llm"] is True
    assert payload["mode"] == "ollama"
    assert payload["safety"] == "offline_research_only_no_action"
    assert "reduire taille" in payload["recommended_adjustments"]


def test_ollama_status_uses_common_client(monkeypatch):
    def fake_urlopen(_url, timeout=None):
        return _FakeResponse({"models": [{"name": "llama3.2:latest"}]})

    monkeypatch.setenv("HYPERSMART_V13_OLLAMA_ENABLED", "1")
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    status = ollama_status()

    assert status.enabled is True
    assert status.api_available is True
    assert status.models == ("llama3.2:latest",)
    assert status.hot_path is False
    assert status.paper_only is True


def test_ollama_preflight_is_paper_only(monkeypatch):
    def fake_urlopen(request_or_url, timeout=None):
        url = getattr(request_or_url, "full_url", str(request_or_url))
        if url.endswith("/api/tags"):
            return _FakeResponse({"models": [{"name": "llama3.2:latest"}]})
        return _FakeResponse({"response": "OK"})

    monkeypatch.setenv("HYPERSMART_V13_OLLAMA_ENABLED", "1")
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    preflight = run_ollama_preflight()

    assert preflight.ok is True
    assert preflight.native_generate_ok is True
    assert preflight.paper_only is True
    assert preflight.can_create_trade is False
    assert preflight.hot_path is False


def test_ollama_signal_rater_returns_veto_not_entry(monkeypatch):
    def fake_urlopen(request, timeout=None):
        body = json.loads(request.data.decode("utf-8"))
        assert body["format"] == "json"
        return _FakeResponse(
            {
                "response": json.dumps(
                    {
                        "ai_score": 0.31,
                        "confidence": 0.74,
                        "veto_recommended": True,
                        "reasons": ["signal trop vieux"],
                        "adjustments": ["attendre consensus frais"],
                        "missing_data": [],
                    }
                )
            }
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    cfg = OllamaSignalRaterConfig(enabled=True, api_style="native", min_ai_score=0.62)

    rating = rate_signal_candidate(
        {"coin": "HYPE", "side": "LONG", "edge_remaining_bps": 4, "signal_age_ms": 30_000},
        config=cfg,
    )

    assert rating.used_llm is True
    assert rating.veto_recommended is True
    assert rating.can_create_trade is False
    assert rating.hot_path is False
    assert rating.paper_only is True
