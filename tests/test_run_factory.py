"""ALPHA FACTORY — pipeline FIX-01 : chaque famille est EXECUTEE (trial reel) ou BLOCKED precis ; jamais de crash."""

import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.research import factory_families as FAM  # noqa: E402
from hl_observer.research import run_factory as RF  # noqa: E402


def test_run_all_couvre_TOUTES_les_familles(tmp_path):
    out = RF.run_all(data_dir=str(tmp_path), registry_path=str(tmp_path / "r.jsonl"))
    # une ligne par famille du registre (execution ou BLOCKED), jamais un registre declaratif
    assert out["n_trials"] == out["n_familles"] == len(FAM.FAMILLES)
    assert set(out["familles_couvertes"]) == set(FAM.FAMILLES)
    # data absente -> les familles sortent BLOCKED_EXTERNAL / MORE_DATA, pas ERROR, pas DONE
    verdicts = {r["verdict"] for r in out["rows"]}
    assert "ERROR" not in verdicts
    assert "BLOCKED_EXTERNAL" in verdicts


def test_run_all_execute_reellement_la_population(tmp_path):
    recs = []
    for d in range(4):
        for coin in ("BTC", "ETH", "SOL"):
            recs.append({"adresse": "0xLOSE", "coin": coin, "side": "LONG",
                         "ts_ms": (10 + d) * 86_400_000, "mid_at_fill": 100.0, "mid_forward": 99.9})
    (tmp_path / "leader_fills_forward.jsonl").write_text(
        "\n".join(json.dumps(x) for x in recs), encoding="utf-8")
    out = RF.run_all(data_dir=str(tmp_path), registry_path=str(tmp_path / "r.jsonl"))
    pop = [r for r in out["rows"] if r["_famille"] == "copy_population"][0]
    # la famille a REELLEMENT tourne (trial mesure), pas un BLOCKED
    assert pop["verdict"] in ("KILL", "CANDIDAT") and "IDEA | CONFIG FROZEN" in out["table"]


def test_fix34_population_trial_porte_pf_es_reels(tmp_path):
    # population avec gagnants ET perdants indépendants -> le trial doit porter pf/es NUMÉRIQUES (pas UNMEASURABLE).
    recs = []
    plans = [("0xWIN1", 100.5, 0), ("0xWIN2", 100.5, 3000), ("0xLOSE1", 99.5, 6000), ("0xLOSE2", 99.5, 9000)]
    for adr, fwd, off in plans:
        for d in range(4):
            for ci, coin in enumerate(("BTC", "ETH", "SOL")):
                recs.append({"adresse": adr, "coin": coin, "side": "LONG",
                             "ts_ms": d * 86_400_000 + off + ci * 300, "mid_at_fill": 100.0, "mid_forward": fwd})
    (tmp_path / "leader_fills_forward.jsonl").write_text(
        "\n".join(json.dumps(x) for x in recs), encoding="utf-8")
    out = RF.run_all(data_dir=str(tmp_path), registry_path=str(tmp_path / "r.jsonl"))
    pop = [r for r in out["rows"] if r["_famille"] == "copy_population"][0]
    assert isinstance(pop["pf"], float) and isinstance(pop["es"], float)    # FIX-34 : pf/es mesurés
    assert isinstance(pop["net_bps"], float) and isinstance(pop["n_independent"], int) and pop["n_independent"] >= 2
    # invariant : un CANDIDAT ne peut JAMAIS afficher un net négatif (verdict et net cohérents)
    if pop["verdict"] == "CANDIDAT":
        assert pop["net_bps"] > 0


def test_fix34_population_gagnante_est_candidat_net_positif(tmp_path):
    # population 100% gagnante -> net positif -> CANDIDAT cohérent (verdict aligné sur le net)
    recs = []
    for adr, off in [("0xA", 0), ("0xB", 3000), ("0xC", 6000)]:
        for d in range(4):
            for ci, coin in enumerate(("BTC", "ETH", "SOL")):
                recs.append({"adresse": adr, "coin": coin, "side": "LONG",
                             "ts_ms": d * 86_400_000 + off + ci * 300, "mid_at_fill": 100.0, "mid_forward": 101.0})
    (tmp_path / "leader_fills_forward.jsonl").write_text(
        "\n".join(json.dumps(x) for x in recs), encoding="utf-8")
    out = RF.run_all(data_dir=str(tmp_path), registry_path=str(tmp_path / "r.jsonl"))
    pop = [r for r in out["rows"] if r["_famille"] == "copy_population"][0]
    assert pop["net_bps"] > 0 and pop["verdict"] == "CANDIDAT"


def test_fix36_gate_anti_overfit_depromeut_selon_le_nb_dessais(tmp_path):
    # FIX-36 : un edge MARGINAL (Sharpe faible) qui aurait ete CANDIDAT est DE-PROMU par le Deflated Sharpe,
    # et la barre monte avec le nombre GLOBAL d'essais (proba deflatee baisse). Un vainqueur parmi N tirages
    # de bruit n'est pas un champion.
    recs = []
    for k in range(26):                                  # >= MIN_TRADES(25) votes independants
        net = -10 + k                                    # edges -10..+15 : moyenne +2.5, Sharpe faible
        fwd = 100.0 * (1 + (net + 9) / 1e4)
        for day in range(4):
            for ci, coin in enumerate(("BTC", "ETH", "SOL")):
                recs.append({"adresse": "0xW%02d" % k, "coin": coin, "side": "LONG",
                             "ts_ms": day * 86_400_000 + k * 4000 + ci * 300, "mid_at_fill": 100.0, "mid_forward": fwd})
    (tmp_path / "leader_fills_forward.jsonl").write_text(
        "\n".join(json.dumps(x) for x in recs), encoding="utf-8")

    def _run(nb_essais):
        reg = tmp_path / ("r%d.jsonl" % nb_essais)
        reg.write_text("\n".join(json.dumps({"config_hash": "c%d" % i, "verdict": "KILL"})
                                 for i in range(nb_essais)) if nb_essais else "", encoding="utf-8")
        out = RF.run_all(data_dir=str(tmp_path), registry_path=str(reg))
        return [r for r in out["rows"] if r["_famille"] == "copy_population"][0]

    peu, beaucoup = _run(0), _run(50000)
    assert isinstance(peu["proba_deflatee"], float) and isinstance(beaucoup["proba_deflatee"], float)
    assert beaucoup["proba_deflatee"] < peu["proba_deflatee"]          # plus d'essais -> proba deflatee plus basse
    assert beaucoup["verdict"] == "MORE_DATA" and "anti-overfit" in (beaucoup.get("notes") or "")


def _serie_decay_et_fills(nfills=12):
    # Alpha qui DÉCROÎT avec l'âge du signal : un fill LONG BTC à T, prix Binance qui monte de +60 bps
    # linéairement sur [T, T+5s] puis plateau. Entrer tôt (age~0, hold 5s) capte +60 bps ; entrer tard
    # capte de moins en moins -> le net (−9 bps de coût) traverse 0 -> half_life/break_even MESURABLES.
    pts, fills = [], []
    for k in range(nfills):
        T = k * 120_000 + 30_000                       # épisodes espacés (aucun chevauchement de fenêtres)
        fills.append({"adresse": "0xDECAY", "coin": "BTC", "side": "LONG", "ts_ms": T})
        t = T - 2000
        while t <= T + 36_000:
            u = t - T
            p = 100.0 if u <= 0 else (100.0 * (1.0 + 0.006 * (u / 5000.0)) if u <= 5000 else 100.6)
            pts.append((t, p))
            t += 250
    return pts, fills


def test_fix39_anticipation_porte_une_courbe_decay_reelle(tmp_path):
    # FIX-39 : la famille anticipation (signaux discrets = fills + prix denses) DOIT porter une courbe de decay
    # RÉELLE (half_life / break_even / max_signal_age numériques) via run_all, et le gate no_trade doit être
    # cohérent avec la borne attachée. Jamais 0 fabriqué : ici la donnée existe -> valeurs mesurées.
    from hl_observer.research import alpha_decay as DEC
    pts, fills = _serie_decay_et_fills()
    (tmp_path / "bbo_synchro.jsonl").write_text(
        "\n".join(json.dumps({"coin": "BTC", "ts_ms": t, "bin_mid": p}) for t, p in pts), encoding="utf-8")
    (tmp_path / "leader_fills_forward.jsonl").write_text(
        "\n".join(json.dumps(f) for f in fills), encoding="utf-8")
    out = RF.run_all(data_dir=str(tmp_path), registry_path=str(tmp_path / "r.jsonl"))
    anti = [r for r in out["rows"] if r["_famille"] == "wallet_binance_anticipation"][0]
    # courbe de decay mesurée (pas UNMEASURABLE) : l'alpha décroît -> le net traverse 0
    assert isinstance(anti["half_life_ms"], float) and anti["half_life_ms"] > 0
    assert isinstance(anti["break_even_latency_ms"], float) and anti["break_even_latency_ms"] > 0
    assert isinstance(anti["max_signal_age_ms"], float)
    assert anti["half_life_ms"] < anti["max_signal_age_ms"]         # demi-vie avant la mort du signal
    assert isinstance(anti["decay_net_par_age_ms"], dict) and anti["decay_net_par_age_ms"]
    assert "decay: NO_TRADE au-dela" in (anti.get("notes") or "")
    # gate no_trade cohérent avec la borne attachée : au-delà du break-even -> NO_TRADE, avant -> tradeable
    courbe = {"max_signal_age_ms": anti["max_signal_age_ms"]}
    assert DEC.no_trade(anti["max_signal_age_ms"] + 1.0, courbe) is True
    assert DEC.no_trade(0.0, courbe) is False
    # FIX-39 « pour CHAQUE famille » : toute ligne porte un statut de decay (mesuré OU UNMEASURABLE, jamais absent)
    for r in out["rows"]:
        assert "max_signal_age_ms" in r and "half_life_ms" in r and "break_even_latency_ms" in r
    autres = [r for r in out["rows"] if r["_famille"] != "wallet_binance_anticipation"]
    assert autres and all(r["max_signal_age_ms"] == DEC.UNMEASURABLE for r in autres)   # honnête, jamais 0


def test_fix41_exits_famille_gele_une_regle_et_mesure_en_oos(tmp_path):
    # FIX-41 : la famille `exits` (câblée) construit des chemins de markout depuis fills+bbo, GÈLE une règle
    # d'exit sur la découverte et la mesure sur l'OOS -> trial réel (jamais BLOCKED quand la donnée existe).
    pts, fills = _serie_decay_et_fills()
    (tmp_path / "bbo_synchro.jsonl").write_text(
        "\n".join(json.dumps({"coin": "BTC", "ts_ms": t, "bin_mid": p}) for t, p in pts), encoding="utf-8")
    (tmp_path / "leader_fills_forward.jsonl").write_text(
        "\n".join(json.dumps(f) for f in fills), encoding="utf-8")
    out = RF.run_all(data_dir=str(tmp_path), registry_path=str(tmp_path / "r.jsonl"))
    ex = [r for r in out["rows"] if r["_famille"] == "exits"][0]
    assert ex["verdict"] != "BLOCKED_EXTERNAL"                 # famille câblée : elle PRODUIT un trial
    assert ex["verdict"] == "CANDIDAT" and isinstance(ex["net_bps"], float) and ex["net_bps"] > 0
    assert "GELEE" in ex["config_frozen"]                      # la règle a bien été gelée avant l'OOS
    assert "regle GELEE=" in (ex.get("notes") or "")


def test_fix52_feature_cache_reutilise_les_lectures_sans_changer_le_resultat(tmp_path):
    # FIX-52 : le cache de features IMMUABLE est réellement utilisé — exits réutilise le parse (bbo + fills) de
    # l'anticipation (hits > 0), et le résultat est IDENTIQUE avec ou sans cache (invariance numérique).
    pts, fills = _serie_decay_et_fills()
    (tmp_path / "bbo_synchro.jsonl").write_text(
        "\n".join(json.dumps({"coin": "BTC", "ts_ms": t, "bin_mid": p}) for t, p in pts), encoding="utf-8")
    (tmp_path / "leader_fills_forward.jsonl").write_text(
        "\n".join(json.dumps(f) for f in fills), encoding="utf-8")
    avec = RF.run_all(data_dir=str(tmp_path), registry_path=str(tmp_path / "r1.jsonl"), use_cache=True)
    sans = RF.run_all(data_dir=str(tmp_path), registry_path=str(tmp_path / "r2.jsonl"), use_cache=False)
    assert avec["cache"]["hits"] >= 2 and sans["cache"] is None      # lectures réutilisées entre familles
    proj = lambda out: [(r["_famille"], r["verdict"], r.get("net_bps")) for r in out["rows"]]   # noqa: E731
    assert proj(avec) == proj(sans)                                  # perf sans changer le résultat


def test_fix53_cache_fichier_reutilise_les_parses_entre_runs(tmp_path):
    # FIX-53 : un CacheParFichier persistant évite de RE-lire les JSONL entre runs tant qu'ils n'ont pas changé.
    from hl_observer.research import jsonl_stream as JS
    pts, fills = _serie_decay_et_fills()
    (tmp_path / "bbo_synchro.jsonl").write_text(
        "\n".join(json.dumps({"coin": "BTC", "ts_ms": t, "bin_mid": p}) for t, p in pts), encoding="utf-8")
    (tmp_path / "leader_fills_forward.jsonl").write_text(
        "\n".join(json.dumps(f) for f in fills), encoding="utf-8")
    cf = JS.CacheParFichier()
    a = RF.run_all(data_dir=str(tmp_path), registry_path=str(tmp_path / "r1.jsonl"), cache_fichier=cf)
    b = RF.run_all(data_dir=str(tmp_path), registry_path=str(tmp_path / "r2.jsonl"), cache_fichier=cf)
    assert cf.miss == 2 and cf.hits == 2               # 2 parses au 1er run, 0 relecture au 2e (fichiers inchangés)
    proj = lambda out: [(r["_famille"], r["verdict"], r.get("net_bps")) for r in out["rows"]]   # noqa: E731
    assert proj(a) == proj(b)                          # invariance inter-runs


def test_p13_reset_defaut_est_append_only_avec_dedup(tmp_path):
    reg = str(tmp_path / "r.jsonl")
    out1 = RF.run_all(data_dir=str(tmp_path), registry_path=reg)
    RF.run_all(data_dir=str(tmp_path), registry_path=reg)                 # 2e run IDENTIQUE
    # FIX-03 : append-only sans wipe, 2e run identique DEDUP -> pas de doublons
    assert len(RF.F.TrialRegistry(reg).load()) == out1["n_trials"]
