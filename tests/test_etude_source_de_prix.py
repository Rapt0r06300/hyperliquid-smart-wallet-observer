"""LA SOURCE DE PRIX DEMANDÉE DOIT ÊTRE LA SOURCE UTILISÉE — et un repli ne doit jamais être muet.

LE DÉFAUT, MESURÉ LE 17/11/2026. Le choix de la source de prix de l'étude de copiabilité s'écrivait :

```python
price="mids" if "--prix" in (argv or sys.argv) and args.prix == "mids" else "bougies"
```

Les prix OBSERVÉS n'étaient donc utilisés que si l'opérateur tapait explicitement `--prix mids`.
En omettant l'option — pourtant documentée comme le DÉFAUT — l'étude retombait **en silence** sur
des bougies 5 min récupérées après coup : péremption 360 s au lieu de 120 s, provenance
rétrospective au lieu d'observée, alors que **112 729 points observés sur 408 coins** dormaient au
coffre. Le défaut annoncé mentait, et il mentait vers la source de MOINDRE provenance — l'inverse
de fail-closed.

CE QUE CELA COÛTAIT, mesuré avant/après sur le MÊME corpus figé (réplication 350 USD) :

| mesure                      | bougies 5 min | allMids observés |
|-----------------------------|--------------:|-----------------:|
| net USD/jour                |        -0,967 |           -0,185 |
| net bps/jour sur capital    |       -27,629 |           -5,284 |
| IC 95 %                     | [-2,77;+0,63] |   [-1,31;+0,81]  |
| points de prix              |         6 832 |          112 729 |

La valorisation grossière **surestimait la perte d'un facteur 5** et fabriquait une queue de
pertes extrêmes (le pire leader passait de -21,06 à -8,94 USD/jour). Le verdict reste `MORE_DATA` :
5 journées distinctes mesurées pour 20 requises. Rien n'est prouvé ici, et le sens de l'erreur
n'excuse pas l'erreur.
"""
from __future__ import annotations

import gzip
import importlib.util
import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
if str(RACINE / "src") not in sys.path:
    sys.path.insert(0, str(RACINE / "src"))

_spec = importlib.util.spec_from_file_location(
    "etude_copiabilite", RACINE / "tools" / "etude_copiabilite.py")
EC = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(EC)

T0 = 1_790_000_000_000


def _shard_allmids(tmp_path: Path, n: int) -> list[dict]:
    chemin = tmp_path / "allmids.jsonl.gz"
    with gzip.open(chemin, "wt", encoding="utf-8") as fh:
        for i in range(n):
            fh.write(json.dumps({"ts_ms": T0 + i * 6_000,
                                 "mids": {"BTC": 100.0 + i * 0.01, "ETH": 50.0}}) + "\n")
    return [{"path": str(chemin)}]


def test_la_source_OBSERVEE_est_utilisee_quand_elle_est_demandee(tmp_path):
    shards = {"allmids": _shard_allmids(tmp_path, 2_000), "candle": []}
    panel, tier, refus = EC._panneau_de_prix(tmp_path, shards, price="mids",
                                             stale_ms=120_000, identity={})
    assert refus is None
    assert "observés" in tier
    assert panel.provenance == "HYPERLIQUID_ALLMIDS_OBSERVED"
    assert panel.stale_ms == 120_000, "la peremption observee est 3x plus stricte que les bougies"


def test_un_panneau_OBSERVE_trop_pauvre_REFUSE_au_lieu_de_se_replier(tmp_path):
    """Le repli change la provenance ET la péremption : il doit être demandé, jamais pris."""
    shards = {"allmids": _shard_allmids(tmp_path, 10), "candle": []}
    panel, tier, refus = EC._panneau_de_prix(tmp_path, shards, price="mids",
                                             stale_ms=120_000, identity={})
    assert panel is None
    assert refus["status"] == "UNMEASURABLE"
    assert refus["points_observes"] == 10
    # le refus doit NOMMER le repli explicite, sinon l'operateur est bloque sans issue
    assert "--prix prints" in refus["reason"]
    assert "360" in refus["reason"] and "120" in refus["reason"], (
        "le refus doit dire ce que le repli changerait : la peremption")


def test_les_bougies_restent_disponibles_mais_DEMANDEES(tmp_path):
    shards = {"allmids": [], "candle": []}
    panel, tier, refus = EC._panneau_de_prix(tmp_path, shards, price="prints",
                                             stale_ms=120_000, identity={})
    # aucune bougie sur disque dans ce tmp : le refus est explicite, pas un panneau vide
    assert panel is None
    assert refus["status"] == "UNMEASURABLE"
    assert "bougies absentes" in refus["reason"]


def test_le_CLI_ne_RENIFLE_plus_la_ligne_de_commande():
    """Le défaut exact : `"--prix" in sys.argv` faisait dépendre la PROVENANCE de la frappe."""
    import inspect

    # On inspecte le DISPATCH, pas tout le module : le docstring du correctif cite volontairement
    # la ligne fautive, et un test qui confond la prose et le code n'atteste rien.
    dispatch = inspect.getsource(EC.main)
    assert '"--prix" in (argv or sys.argv)' not in dispatch, (
        "la provenance des prix ne doit pas dependre de la presence d'un argument")
    assert dispatch.count("price=args.prix") >= 2, (
        "les deux etudes (replication-350 et positions) doivent passer la source demandee")


def test_la_peremption_des_bougies_est_PLUS_LARGE_et_c_est_mesurable():
    """Ce qui justifie de préférer l'observé : une bougie 5 min est périmée jusqu'à 360 s."""
    from hl_observer.backtesting import copy_vault_copiability as cop

    panel = cop.build_candle_panel(
        [("BTC", T0, 100.0), ("BTC", T0 + 300_000, 101.0)], interval_ms=300_000)
    assert panel.stale_ms == 300_000 + 60_000
    assert panel.provenance == "HYPERLIQUID_CANDLE_CLOSE_RETROSPECTIVE"
    # et la cloture n'est publiee qu'a la FIN de la bougie : aucune avance d'information
    assert int(panel.ts[0]) == T0 + 300_000
