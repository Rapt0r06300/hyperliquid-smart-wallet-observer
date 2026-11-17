"""LE TUNNEL DOIT MESURER SUR LA SOURCE DU LABO — sinon les deux dénominateurs ne se parlent pas.

LE DÉFAUT, MESURÉ LE 17/11/2026. Le tunnel d'exécutabilité ne lisait que la **queue** des rubans
vivants, bornée par un budget d'octets. Conséquence mesurée sur les rubans réels :

```
400 Mo de carnets  ->  652 min couverts        120 Mo de fills  ->  3 jours couverts
HORS_FENETRE_DE_MESURE : 35 239 refus sur 43 793 signaux  =  80 %
```

Quatre cinquièmes du verdict décrivaient donc la taille d'un tampon de lecture, pas la donnée. Et
comme le labo mesure sur le COFFRE (6 988 954 lignes de carnets, 21 jours) tandis que le tunnel
mesurait sur le ruban, les deux chiffres n'étaient pas réconciliables.

APRÈS, même code de jugement, source = coffre certifié, fenêtre 13→17/11 :

```
88 131 signaux d'ouverture  ->  87 844 chaînes complètes  =  99,7 %
E_jugeable_dans_la_fenetre  =  100,0 %     HORS_FENETRE  =  0
31 leaders distincts, 31 avec chaîne complète
```

Ces tests verrouillent : même logique pour les deux sources, fenêtre qui devient une propriété des
données, et un shard refusé qui reste VISIBLE — sinon un tunnel « complet » pourrait l'être sur un
corpus silencieusement amoindri.
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

_spec = importlib.util.spec_from_file_location(
    "tunnel_executabilite", RACINE / "tools" / "tunnel_executabilite.py")
TU = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(TU)

T0 = 1_790_000_000_000


def _shard(tmp_path: Path, famille: str, nom: str, lignes: list[dict], *,
           horloge: str) -> dict:
    rel = f"runtime/coffre_certifie/local/shards/{famille}/{nom}.jsonl.gz"
    chemin = tmp_path / rel
    chemin.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(chemin, "wt", encoding="utf-8") as fh:
        for l in lignes:
            fh.write(json.dumps(l) + "\n")
    instants = [l[horloge] for l in lignes if horloge in l]
    return {"famille": famille, "shard": rel,
            "sha256": hashlib.sha256(chemin.read_bytes()).hexdigest(),
            "octets": chemin.stat().st_size, "deposes": len(lignes),
            "coins": sorted({str(l.get("coin")) for l in lignes if l.get("coin")}),
            "ts_min_ms": min(instants) if instants else None,
            "ts_max_ms": max(instants) if instants else None}


def _index(tmp_path: Path, entrees: list[dict]) -> None:
    chemin = tmp_path / "runtime" / "coffre_certifie" / "LOCAL_INDEX.json"
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(json.dumps({"schema": "x", "tier": "LOCAL", "shards": entrees}),
                      encoding="utf-8")


def _carnet(coin: str, recu: int) -> dict:
    return {"coin": coin, "received_at_ms": recu, "exchange_ts_ms": recu - 30,
            "bid": 100.0, "ask": 100.1, "bids5": [[100.0, 5.0]], "asks5": [[100.1, 5.0]]}


def _fill_ouverture(coin: str, recu: int, *, vault: str = "0xlead") -> dict:
    """Un fill d'OUVERTURE causal : les labels viennent du contrat de production."""
    return {"coin": coin, "received_at_ms": recu, "ts_ms": recu - 50, "vault": vault,
            "source": "LIVE_WS", "isSnapshot": False, "dir": "Open Long",
            "start_position": 0.0, "stable_event_id": f"{coin}-{recu}"}


def _monde(tmp_path: Path, *, n_signaux: int = 5) -> None:
    """Un coffre minuscule mais COMPLET : carnets couvrant référence, entrée et sortie."""
    base = T0
    carnets = []
    # un carnet toutes les 10 s sur 20 min : couvre signal, signal+60s et entree+300s
    for k in range(120):
        carnets.append(_carnet("BTC", base - 60_000 + k * 10_000))
    fills = [_fill_ouverture("BTC", base + i * 1_000) for i in range(n_signaux)]
    _index(tmp_path, [
        _shard(tmp_path, "book_l2", "l2", carnets, horloge="exchange_ts_ms"),
        _shard(tmp_path, "fills_forward", "ff", fills, horloge="ts_ms"),
    ])


def test_le_tunnel_mesure_la_chaine_COMPLETE_depuis_le_coffre(tmp_path):
    _monde(tmp_path, n_signaux=5)
    rapport = TU.mesurer(tmp_path, octets_fills=0, octets_carnets=0,
                         source=TU.SOURCE_COFFRE)
    etapes = rapport["etapes"]
    assert rapport["source"] == TU.SOURCE_COFFRE
    assert etapes["D_signal_d_ouverture"] == 5
    assert etapes["E_jugeable_dans_la_fenetre"] == 5, "aucun signal ne doit tomber hors fenetre"
    assert etapes["F_reference_pre_signal"] == 5
    assert etapes["G_carnet_d_entree"] == 5
    assert etapes["H_sortie_observee"] == 5
    assert rapport["motifs_de_refus"].get("HORS_FENETRE_DE_MESURE") is None


def test_la_fenetre_devient_une_PROPRIETE_DES_DONNEES_et_non_d_un_tampon(tmp_path):
    """Un signal hors de la couverture des carnets est « non mesuré », et c'est DIT."""
    base = T0
    carnets = [_carnet("BTC", base + k * 10_000) for k in range(60)]
    # un signal 10 jours APRES la fin des carnets : on ne peut pas le juger
    fills = [_fill_ouverture("BTC", base + 10 * 86_400_000)]
    _index(tmp_path, [
        _shard(tmp_path, "book_l2", "l2", carnets, horloge="exchange_ts_ms"),
        _shard(tmp_path, "fills_forward", "ff", fills, horloge="ts_ms"),
    ])
    rapport = TU.mesurer(tmp_path, octets_fills=0, octets_carnets=0, source=TU.SOURCE_COFFRE)
    assert rapport["etapes"]["D_signal_d_ouverture"] == 1
    assert rapport["etapes"].get("E_jugeable_dans_la_fenetre", 0) == 0
    assert rapport["motifs_de_refus"]["HORS_FENETRE_DE_MESURE"] == 1
    # et la fenetre publiee est celle des carnets REELS, pas celle d'un budget d'octets
    assert rapport["bornes_de_lecture"] == {"fenetre_demandee_ms": [None, None]}


def test_un_shard_REFUSE_reste_visible_dans_le_rapport(tmp_path):
    """Un tunnel « complet » sur un corpus amoindri serait un faux : le refus doit sortir."""
    _monde(tmp_path, n_signaux=3)
    index = tmp_path / "runtime" / "coffre_certifie" / "LOCAL_INDEX.json"
    charge = json.loads(index.read_text(encoding="utf-8"))
    for entree in charge["shards"]:
        if entree["famille"] == "book_l2":
            entree["sha256"] = "f" * 64          # empreinte qui ne correspond plus
    index.write_text(json.dumps(charge), encoding="utf-8")

    rapport = TU.mesurer(tmp_path, octets_fills=0, octets_carnets=0, source=TU.SOURCE_COFFRE)
    refuses = rapport["lecture"]["shards_refuses"]
    assert refuses, "un shard au SHA divergent doit etre REFUSE et DIT"
    assert refuses[0]["motif"] == "SHA_DIVERGENT"
    assert rapport["fenetre_carnets"]["lignes"] == 0


def test_les_deux_sources_appliquent_la_MEME_regle_de_jugement():
    """La logique d'étage ne doit exister qu'une fois : sinon les chiffres ne se comparent pas."""
    import inspect

    source = inspect.getsource(TU.mesurer)
    # une seule boucle de jugement, et elle itere sur `fills` quelle que soit l'origine
    assert source.count("for fill in fills:") == 1
    assert "D_signal_d_ouverture" in source
    # les deux sources ne font que FOURNIR les lignes
    assert "fills_du_coffre(" in source and "fills_du_ruban(" in source


def test_l_horloge_de_mesure_est_la_RECEPTION_et_c_est_declare(tmp_path):
    """Les shards se sélectionnent sur l'horloge d'index, la causalité se mesure à la réception."""
    _monde(tmp_path, n_signaux=2)
    rapport = TU.mesurer(tmp_path, octets_fills=0, octets_carnets=0, source=TU.SOURCE_COFFRE)
    horloges = rapport["horloges"]
    assert "received_at_ms" in horloges["mesure_causale"]
    assert "index" in horloges["selection_des_shards"]
    assert "INSEREE" in horloges["consequence"]
