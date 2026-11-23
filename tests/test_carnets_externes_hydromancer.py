"""Lecteur des carnets externes à la minute (Hydromancer) : jamais causal, jamais au-delà de la tolérance.

Verrouille :
- seuls les fichiers EXTERNAL_VALIDATED du manifeste sont lus (un fichier rejeté n'existe pas pour le labo) ;
- l'heure est celle du BLOC ; le carnet rendu est marqué non causal (il ne peut pas devenir une preuve SAFE) ;
- ``carnet_a`` respecte la tolérance et le côté demandé, et regarde le jour voisin près de minuit ;
- un carnet croisé ou à un seul côté n'est jamais rendu comme un prix.
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.backtesting import carnets_externes_hydromancer as H  # noqa: E402
from hl_observer.backtesting.fenetres_de_signal import predicats_de_rejouabilite  # noqa: E402

MINUIT = int(dt.datetime(2026, 11, 10, tzinfo=dt.timezone.utc).timestamp() * 1000)


def _niveaux(px: float, pas: float) -> list[dict]:
    return [{"px": f"{px + i * pas:.2f}", "sz": "1.5", "n": 2} for i in range(6)]


def _jour(root: Path, jour: str, lignes: list[tuple[str, int, float, float]], statut: str = "EXTERNAL_VALIDATED") -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq

    cle = f"orderbooks_perps/orderbooks_perps_{jour}.parquet"
    chemin = root / H.DOSSIER / cle
    chemin.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.table({
        "coin": [c for c, *_ in lignes], "dex": ["hyperliquid"] * len(lignes),
        "time": pa.array([t * 1000 for _, t, *_ in lignes], pa.timestamp("us")),
        "block_time_ms": [t for _, t, *_ in lignes], "block_number": pa.array([1] * len(lignes), pa.uint64()),
        "bids": [_niveaux(b, -0.1) if b else [] for *_, b, _a in lignes],
        "asks": [_niveaux(a, 0.1) if a else [] for *_, _b, a in lignes],
    }), chemin)
    man_path = root / H.DOSSIER / "MANIFESTE.json"
    man = json.loads(man_path.read_text(encoding="utf-8")) if man_path.exists() else {"fichiers": {}}
    man["fichiers"][cle] = {"statut": statut}
    man_path.write_text(json.dumps(man), encoding="utf-8")


def test_le_carnet_rendu_est_marque_non_causal_et_date_du_bloc(tmp_path):
    _jour(tmp_path, "2026-11-10", [("BTC", MINUIT + 60_000, 100.0, 100.5)])
    c = H.CarnetsHydromancer(tmp_path).carnet_a("BTC", MINUIT + 65_000)
    assert c["exchange_ts_ms"] == MINUIT + 60_000 and c["ecart_ms"] == -5_000
    assert c["bid"] == 100.0 and c["ask"] == 100.5 and len(c["bids5"]) == 5
    non_causal, safe_causal = predicats_de_rejouabilite(c)
    assert non_causal and not safe_causal                                         # jamais une preuve SAFE


def test_tolerance_et_cote_sont_respectes(tmp_path):
    _jour(tmp_path, "2026-11-10", [("BTC", MINUIT + 60_000, 100.0, 100.5), ("BTC", MINUIT + 120_000, 101.0, 101.5)])
    h = H.CarnetsHydromancer(tmp_path)
    assert h.carnet_a("BTC", MINUIT + 95_000)["exchange_ts_ms"] == MINUIT + 120_000   # le plus proche
    assert h.carnet_a("BTC", MINUIT + 95_000, cote="avant", tolerance_ms=60_000)["exchange_ts_ms"] == MINUIT + 60_000
    assert h.carnet_a("BTC", MINUIT + 95_000, cote="avant", tolerance_ms=30_000) is None   # 35 s : trop loin
    assert h.carnet_a("BTC", MINUIT + 200_000) is None
    assert h.carnet_a("ETH", MINUIT + 60_000) is None


def test_pres_de_minuit_le_jour_voisin_est_consulte(tmp_path):
    _jour(tmp_path, "2026-11-09", [("BTC", MINUIT - 10_000, 99.0, 99.5)])
    _jour(tmp_path, "2026-11-10", [("BTC", MINUIT + 50_000, 100.0, 100.5)])
    assert H.CarnetsHydromancer(tmp_path).carnet_a("BTC", MINUIT + 5_000)["exchange_ts_ms"] == MINUIT - 10_000


def test_un_fichier_rejete_ou_un_carnet_casse_n_est_jamais_rendu(tmp_path):
    _jour(tmp_path, "2026-11-10", [("BTC", MINUIT + 60_000, 100.0, 100.5)], statut="EXTERNAL_REJECTED")
    _jour(tmp_path, "2026-11-11", [("BTC", MINUIT + 86_460_000, 100.0, 0.0),           # un seul côté
                                   ("ETH", MINUIT + 86_460_000, 101.0, 100.0)])         # croisé
    h = H.CarnetsHydromancer(tmp_path)
    assert h.jours == ["2026-11-11"]
    assert h.carnet_a("BTC", MINUIT + 60_000) is None
    assert h.carnet_a("BTC", MINUIT + 86_460_000) is None and h.carnet_a("ETH", MINUIT + 86_460_000) is None
