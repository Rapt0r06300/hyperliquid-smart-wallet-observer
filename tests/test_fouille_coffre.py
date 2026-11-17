"""LA MINE N'EST PAS TOUTE EXPLOITABLE — et ce qui ne l'est pas doit être DIT, pas laissé en limbe.

MESURE DU 16/11/2026. À côté du coffre scellé (162 286 723 lignes indexées) vit un **magasin de
ticks natifs** de 467 503 shards et **56,70 Go**, vérifié par SHA-256 et référencé EN PLACE — donc
absent de ``LOCAL_INDEX.json``, donc hors de portée du pont du labo. Sa composition décide de ce
qu'on peut en faire :

* 50,81 Go / 172 192 194 événements viennent de Binance, Bitget, Bybit, Gate : la constitution
  ferme la famille Cross-Venue (``DISABLED_BY_SCOPE``). Les lire pour Copy-Vault rouvrirait par un
  détour un scope fermé — même motif qui exclut déjà ``venue_book`` du pont de replay ;
* 5,89 Go / 41 265 015 événements sont Hyperliquid natif, déjà présents au coffre sous forme
  scellée et réduite (famille ``bbo``, qui porte déjà ``connection_id``) ;
* 12 flux sont vides : zéro observation, et c'est une information, pas un oubli.

Ces tests verrouillent la classification. Un magasin de 56 Go sans motif écrit est indiscernable
d'un oubli de câblage.
"""
from __future__ import annotations

import gzip
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
if str(RACINE / "src") not in sys.path:
    sys.path.insert(0, str(RACINE / "src"))

_spec = importlib.util.spec_from_file_location("fouille_coffre", RACINE / "tools" / "fouille_coffre.py")
FC = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(FC)

T0 = 1_790_000_000_000


def _index_ticks(tmp_path: Path, flux: list[dict]) -> None:
    chemin = tmp_path / FC.TICKS_RELPATH
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(json.dumps({
        "schema": "hypersmart.coffre_certifie.market_ticks_index.v1",
        "present": True, "shards_verifies": sum(f.get("shards_verifies", 0) for f in flux),
        "octets_verifies": sum(f.get("octets", 0) for f in flux),
        "anomalies": 0, "complet": False, "par_flux": flux,
    }), encoding="utf-8")


def test_les_ticks_D_UNE_AUTRE_VENUE_sont_exclus_avec_le_MOTIF_constitutionnel(tmp_path):
    _index_ticks(tmp_path, [
        {"source": "binance_usdm_public", "canal": "l2Book", "shards_verifies": 4_762,
         "octets": 20_010_000_000, "evenements": 53_089_918},
        {"source": "hyperliquid_mainnet_readonly", "canal": "bbo", "shards_verifies": 1_205,
         "octets": 3_690_000_000, "evenements": 29_852_717},
        {"source": "bybit_public_ws", "canal": "trades", "shards_verifies": 0,
         "octets": 0, "evenements": 0},
    ])
    annexe = FC.annexe_ticks(tmp_path)
    assert annexe["present"] is True
    motifs = annexe["par_motif"]
    assert motifs["DISABLED_BY_SCOPE:cross_venue"]["evenements"] == 53_089_918
    assert motifs["HYPERLIQUID_NATIF_NON_SCELLE"]["evenements"] == 29_852_717
    assert motifs["VIDE_AUCUNE_OBSERVATION"]["flux"] == 1
    # un flux vide ne doit JAMAIS etre compte comme une venue exclue : ce sont deux etats differents
    assert motifs["VIDE_AUCUNE_OBSERVATION"]["evenements"] == 0


def test_un_magasin_de_ticks_ABSENT_ne_fabrique_pas_un_zero(tmp_path):
    annexe = FC.annexe_ticks(tmp_path)
    assert annexe == {"present": False}


def test_un_index_de_ticks_ILLISIBLE_est_dit_et_non_ignore(tmp_path):
    chemin = tmp_path / FC.TICKS_RELPATH
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text("{ ceci n est pas du JSON", encoding="utf-8")
    assert FC.annexe_ticks(tmp_path)["raison"] == "INDEX_ILLISIBLE"


# ─────────────── le recensement d'une galerie : il lit, il compte, il ne devine pas ───────────────
def _shard_reel(tmp_path: Path, famille: str, nom: str, lignes: list[dict]) -> dict:
    rel = f"runtime/coffre_certifie/local/shards/{famille}/{nom}.jsonl.gz"
    chemin = tmp_path / rel
    chemin.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(chemin, "wt", encoding="utf-8") as fh:
        for l in lignes:
            fh.write(json.dumps(l) + "\n")
    from hl_observer.backtesting import coffre_tranches as TR
    champ = TR.horloge_de(famille)
    instants = [l[champ] for l in lignes if champ in l]
    return {"famille": famille, "shard": rel,
            "sha256": hashlib.sha256(chemin.read_bytes()).hexdigest(),
            "octets": chemin.stat().st_size, "deposes": len(lignes),
            "coins": sorted({str(l.get("coin")) for l in lignes if l.get("coin")}),
            "ts_min_ms": min(instants) if instants else None,
            "ts_max_ms": max(instants) if instants else None}


def test_le_recensement_lit_les_CARNETS_que_l_ancien_trancheur_jetait(tmp_path):
    """Preuve de bout en bout du correctif d'horloge : un carnet n'a pas de ``ts_ms``."""
    carnets = [{"coin": "BTC", "exchange_ts_ms": T0 + i * 1_000,
                "received_at_ms": T0 + i * 1_000 + 15,
                "bids5": [[1.0, 1.0]], "asks5": [[1.1, 1.0]]} for i in range(6)]
    entree = _shard_reel(tmp_path, "book_l2", "l2", carnets)
    mesure = FC.mesurer_galerie(tmp_path, [entree], ["book_l2"],
                                {"debut_ms": T0, "fin_ms": T0 + 10_000}, coins=None)
    assert mesure["lignes_lues"] == 6
    assert mesure["lignes_par_famille"] == {"book_l2": 6}
    assert mesure["coins"] == ["BTC"]
    assert mesure["lignes_sans_horloge"] == 0
    assert mesure["instant_min"] == T0
    assert len(mesure["lignes_par_jour"]) == 1


def test_une_galerie_HORS_de_la_fenetre_rend_zero_ligne_sans_refus(tmp_path):
    """Zero ligne parce qu'il n'y en a pas N'EST PAS zero ligne parce qu'on a echoue a lire."""
    entree = _shard_reel(tmp_path, "funding_history", "f",
                         [{"coin": "BTC", "ts_ms": T0, "funding": 0.0001}])
    mesure = FC.mesurer_galerie(tmp_path, [entree], ["funding_history"],
                                {"debut_ms": T0 + 10**9, "fin_ms": T0 + 2 * 10**9}, coins=None)
    assert mesure["lignes_lues"] == 0
    assert mesure["shards_refuses"] == []
    assert mesure["shards_lus"] == 0, "un shard hors fenetre n'est meme pas ouvert"
