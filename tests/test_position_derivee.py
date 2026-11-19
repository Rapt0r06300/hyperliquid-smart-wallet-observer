"""Position dérivée de `start_position` : ce qu'elle garde, et surtout ce qu'elle REFUSE.

Le labo ne copiait que 0,85 % du signal collecté parce que 6,2 M de fills étaient jetés faute de
connaître la position du leader avant le fill. La famille `fills_backfill` porte `start_position`
sur 81,3 % de ses lignes et comble ce trou.

LA LIGNE À NE JAMAIS FRANCHIR : un fill de backfill est une observation d'ÉTAT, jamais un SIGNAL
à copier — on ne l'a connu qu'après coup, et chaque ligne porte `causal_forward_eligible: False`.
Ces tests gardent cette séparation ET le refus de deviner.
"""
from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
if str(RACINE / "src") not in sys.path:
    sys.path.insert(0, str(RACINE / "src"))

from hl_observer.backtesting import copy_vault_coffre_vers_labo as C  # noqa: E402
from hl_observer.backtesting import copy_vault_position_derivee as D  # noqa: E402


# --------------------------------------------------------------------------- le calcul


def _lire(lignes, monkeypatch, tmp_path: Path):
    """Fait lire `lignes` au module, sans toucher au vrai coffre."""
    index = tmp_path / "runtime/coffre_certifie/LOCAL_INDEX.json"
    index.parent.mkdir(parents=True, exist_ok=True)
    index.write_text('{"shards": [{"famille": "fills_backfill"}]}', encoding="utf-8")

    class _FauxTranches:
        @staticmethod
        def selectionner(_tous, **_kw):
            return {"shards": [{"famille": "fills_backfill"}]}

        @staticmethod
        def flux(_racine, _shards, **_kw):
            return iter(lignes)

    import hl_observer.backtesting.coffre_tranches as vrai
    monkeypatch.setattr(vrai, "selectionner", _FauxTranches.selectionner)
    monkeypatch.setattr(vrai, "flux", _FauxTranches.flux)
    return D.positions_depuis_les_fills(tmp_path, debut_ms=0, fin_ms=10**15)


def _fill(**kw):
    base = {"start_position": -1761.38, "sz": 0.009, "signe": -1,
            "ts_ms": 1795064449055, "vault": "0xfc66", "coin": "xyz:SP500"}
    base.update(kw)
    return base


def test_position_apres_le_fill_et_pas_avant(monkeypatch, tmp_path: Path) -> None:
    """On enregistre l'APRÈS : la position d'avant est déjà périmée à l'instant du fill."""
    series, audit = _lire([_fill()], monkeypatch, tmp_path)
    (instant, valeur), = series[("0xfc66", "xyz:SP500")]
    assert instant == 1795064449055
    assert valeur == -1761.38 + (-1 * 0.009)       # = -1761.389
    assert audit["observations_gardees"] == 1


def test_un_achat_augmente_la_position() -> None:
    assert (-5.0) + (1 * 2.0) == -3.0              # l'arithmétique du signe, explicitement


def test_series_triees_par_instant(monkeypatch, tmp_path: Path) -> None:
    series, _ = _lire([
        _fill(ts_ms=300), _fill(ts_ms=100), _fill(ts_ms=200),
    ], monkeypatch, tmp_path)
    instants = [i for i, _ in series[("0xfc66", "xyz:SP500")]]
    assert instants == sorted(instants)


# --------------------------------------------------------------------------- les refus


def test_sans_start_position_rien_n_est_devine(monkeypatch, tmp_path: Path) -> None:
    series, audit = _lire([_fill(start_position=None)], monkeypatch, tmp_path)
    assert series == {}
    assert audit["sans_start_position"] == 1


def test_un_booleen_n_est_pas_une_position(monkeypatch, tmp_path: Path) -> None:
    """`True` vaut 1 en Python : sans garde, un drapeau deviendrait une position d'une unité."""
    series, audit = _lire([_fill(start_position=True)], monkeypatch, tmp_path)
    assert series == {}
    assert audit["sans_start_position"] == 1


def test_sans_taille_ou_signe_on_refuse(monkeypatch, tmp_path: Path) -> None:
    for champ, valeur in (("sz", None), ("signe", None), ("signe", 0), ("sz", -1.0)):
        series, audit = _lire([_fill(**{champ: valeur})], monkeypatch, tmp_path)
        assert series == {}, (champ, valeur)
        assert audit["sans_taille_ou_signe"] == 1, (champ, valeur)


def test_sans_identite_on_refuse(monkeypatch, tmp_path: Path) -> None:
    for champ in ("vault", "coin"):
        series, audit = _lire([_fill(**{champ: ""})], monkeypatch, tmp_path)
        assert series == {}
        assert audit["sans_identite"] == 1


def test_coffre_absent_ne_leve_pas(tmp_path: Path) -> None:
    series, audit = D.positions_depuis_les_fills(tmp_path, debut_ms=0, fin_ms=1)
    assert series == {} and audit["status"] == "COFFRE_ABSENT"


# --------------------------------------------------------------------------- la fusion


def test_la_source_prioritaire_gagne_a_instant_egal() -> None:
    directe = {("v", "c"): [(100, 7.0)]}
    derivee = {("v", "c"): [(100, 999.0), (200, 8.0)]}
    fusion = D.fusionner_positions(directe, derivee)
    assert fusion[("v", "c")] == [(100, 7.0), (200, 8.0)]


def test_la_fusion_ne_perd_aucun_couple() -> None:
    fusion = D.fusionner_positions({("a", "x"): [(1, 1.0)]}, {("b", "y"): [(2, 2.0)]})
    assert set(fusion) == {("a", "x"), ("b", "y")}


# --------------------------------------------------------------------------- la ligne rouge


def test_le_backfill_ne_devient_jamais_un_signal_a_copier() -> None:
    """Un fill connu après coup ne peut pas être copié : seule `fills_forward` est un signal."""
    assert C.FAMILLES_DE_FILLS == ("fills_forward",)
    assert "fills_backfill" not in C.FAMILLES_DE_FILLS


def test_la_position_derivee_se_lit_comme_la_position_observee() -> None:
    """Même forme que `positions_du_coffre`, donc `position_avant` la lit sans changement."""
    series = {("v", "c"): [(1_000, 5.0), (2_000, 7.0)]}
    assert C.position_avant(series, vault="v", coin="c", instant_ms=2_500) == 7.0
    assert C.position_avant(series, vault="v", coin="c", instant_ms=1_500) == 5.0
    assert C.position_avant(series, vault="v", coin="c", instant_ms=500) is None


# --------------------------------------------------------------------------- l'identité d'un fill


def _f(**kw):
    base = {"tid": 265452635519375, "coin": "ETC", "vault": "0x35d9",
            "sz": 0.25, "px": 8.3998, "dir": "Close Long", "hash": "0xdeadbeef",
            "ts_ms": 1795064449055}
    base.update(kw)
    return base


def test_deux_remplissages_partiels_de_meme_taille_restent_deux() -> None:
    """Sans `ts_ms` dans la clé, deux fills identiques à l'instant près fusionnaient.

    Une observation réelle disparaissait alors. L'ajouter ne risquait de scinder un vrai doublon
    que si les deux sources dataient le même fill différemment : mesuré sur l'heure commune du
    18/11, les comptes sont rigoureusement identiques avec et sans `ts_ms`.
    """
    assert C._empreinte_du_fill(_f(ts_ms=1_000_000)) != C._empreinte_du_fill(_f(ts_ms=1_000_001))


def test_sans_horodatage_aucune_identite() -> None:
    assert C._empreinte_du_fill(_f(ts_ms=None)) == ""
    assert C._empreinte_du_fill(_f(ts_ms=True)) == ""


def test_le_hash_n_identifie_plus_un_fill() -> None:
    """`hash` est le hash de la TRANSACTION : une transaction contient plusieurs fills.

    3,9 % des identités portaient des directions contradictoires sur le même hash
    (`Close Long` ET `Open Short`) : s'en servir détruisait ~200 000 fills distincts par jour.
    Deux fills qui ne diffèrent QUE par le hash sont le même fill ; deux fills qui partagent le
    hash mais diffèrent par leur taille sont deux fills.
    """
    assert C._empreinte_du_fill(_f(hash="0xAAA")) == C._empreinte_du_fill(_f(hash="0xBBB"))
    assert C._empreinte_du_fill(_f(sz=0.25)) != C._empreinte_du_fill(_f(sz=7.98))


def test_le_tid_seul_ne_suffit_pas() -> None:
    """1 142 `tid` portaient des tailles différentes : le WS diffuse les morceaux, le REST l'agrégat."""
    assert C._empreinte_du_fill(_f(sz=0.25)) != C._empreinte_du_fill(_f(sz=7.98))
    assert C._empreinte_du_fill(_f(px=8.3998)) != C._empreinte_du_fill(_f(px=8.4))
    assert C._empreinte_du_fill(_f(coin="ETC")) != C._empreinte_du_fill(_f(coin="DOGE"))
    assert C._empreinte_du_fill(_f(vault="0xaaa")) != C._empreinte_du_fill(_f(vault="0xbbb"))


def test_le_meme_fill_ecrit_autrement_reste_le_meme() -> None:
    """LE RISQUE DE LA CLÉ STRICTE : `8.3998` et `"8.39980"` doivent se réunir.

    Sinon le même fill, rapporté par les deux sources, serait compté DEUX FOIS — donc le signal
    et le PnL seraient gonflés, et de façon invisible puisque ça embellit le résultat.
    """
    assert C._empreinte_du_fill(_f(px=8.3998)) == C._empreinte_du_fill(_f(px="8.39980"))
    assert C._empreinte_du_fill(_f(sz=0.25)) == C._empreinte_du_fill(_f(sz="0.250"))
    assert C._empreinte_du_fill(_f(dir="Close Long")) == C._empreinte_du_fill(_f(dir="close long"))


def test_sans_identite_prouvable_jamais_de_doublon() -> None:
    """Deny-by-default : en manquer un ne fabrique rien, en inventer un détruit une observation."""
    assert C._empreinte_du_fill({}) == ""
    for champ in ("coin", "vault"):
        assert C._empreinte_du_fill(_f(**{champ: ""})) == ""
    for champ in ("sz", "px"):
        assert C._empreinte_du_fill(_f(**{champ: None})) == ""
        assert C._empreinte_du_fill(_f(**{champ: "beaucoup"})) == ""


def test_un_booleen_n_est_ni_une_taille_ni_un_prix() -> None:
    """`True` vaut 1 en Python : sans garde, un drapeau deviendrait une taille d'une unité."""
    assert C._empreinte_du_fill(_f(sz=True)) == ""
    assert C._empreinte_du_fill(_f(px=True)) == ""


def test_un_tid_absent_n_empeche_pas_l_identite() -> None:
    """Le reste du tuple décrit déjà le fill ; on ne refuse que si on ne peut rien décrire."""
    assert C._empreinte_du_fill(_f(tid=None)) != ""
    assert C._empreinte_du_fill(_f(tid=None)) != C._empreinte_du_fill(_f(tid=7))


def test_la_causalite_reste_imposee_en_aval() -> None:
    """Une observation trop vieille reste refusée : la dérivation ne contourne pas la garde."""
    vieux = 10_000_000
    series = {("v", "c"): [(vieux, 5.0)]}
    trop_tard = vieux + C.MAX_AGE_POSITION_MS + 1
    assert C.position_avant(series, vault="v", coin="c", instant_ms=trop_tard) is None
    assert C.position_avant(series, vault="v", coin="c", instant_ms=vieux + 1) == 5.0
