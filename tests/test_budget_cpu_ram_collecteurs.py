"""Budget CPU et mesure RAM des collecteurs (19/11/2026).

L'opérateur a autorisé **jusqu'à 60 % de ses cœurs** et demandé le minimum de RAM.

POURQUOI UNE AFFINITÉ ET PAS SEULEMENT UNE PRIORITÉ. Les collecteurs tournaient en priorité
``IDLE`` : ils prennent tous les cœurs quand la machine est libre, mais sont affamés dès que
l'opérateur travaille — leur débit s'écroule au pire moment. Réserver une PART des cœurs donne
les deux garanties à la fois : ils travaillent vraiment sur leur part, et ne touchent jamais le
reste, donc la machine reste réactive.

LA RÈGLE FAIL-SAFE GARDÉE ICI : on ne relève la priorité **que si** l'affinité a été posée.
Relever la priorité sans avoir borné les cœurs rendrait la machine moins réactive — exactement
ce que l'opérateur ne demande pas.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
if str(RACINE / "src") not in sys.path:
    sys.path.insert(0, str(RACINE / "src"))

from hl_observer.ops import bounded_collection as BC  # noqa: E402
from hl_observer.ops import superviseur_collecteurs as S  # noqa: E402


# --------------------------------------------------------------------------- part des cœurs


def test_fraction_par_defaut_est_celle_autorisee() -> None:
    assert BC.fraction_coeurs({}) == 0.6
    assert BC.FRACTION_COEURS_DEFAUT == 0.6


def test_fraction_reglable_par_environnement() -> None:
    assert BC.fraction_coeurs({BC.VAR_FRACTION_COEURS: "0.25"}) == 0.25
    assert BC.fraction_coeurs({BC.VAR_FRACTION_COEURS: "0,25"}) == 0.25  # virgule française


def test_fraction_illisible_ou_hors_bornes_ne_casse_rien() -> None:
    assert BC.fraction_coeurs({BC.VAR_FRACTION_COEURS: "beaucoup"}) == 0.6
    assert BC.fraction_coeurs({BC.VAR_FRACTION_COEURS: "0"}) == 0.0      # désactivé
    assert BC.fraction_coeurs({BC.VAR_FRACTION_COEURS: "-1"}) == 0.0
    assert BC.fraction_coeurs({BC.VAR_FRACTION_COEURS: "7"}) == 0.0


def test_neuf_coeurs_sur_seize() -> None:
    """Le cas de la machine de l'opérateur : 16 cœurs, 60 % => 9."""
    coeurs = BC.coeurs_autorises(total=16, environnement={})
    assert len(coeurs) == 9
    assert coeurs == (7, 8, 9, 10, 11, 12, 13, 14, 15)


def test_les_premiers_coeurs_restent_libres() -> None:
    """Les cœurs du bas portent l'interface : ce sont ceux que l'opérateur sent en premier."""
    coeurs = BC.coeurs_autorises(total=16, environnement={})
    assert 0 not in coeurs and 6 not in coeurs


def test_aucune_affinite_quand_elle_n_apporte_rien() -> None:
    assert BC.coeurs_autorises(total=16, environnement={BC.VAR_FRACTION_COEURS: "1.0"}) == ()
    assert BC.coeurs_autorises(total=1, environnement={}) == ()
    assert BC.coeurs_autorises(total=16, environnement={BC.VAR_FRACTION_COEURS: "0"}) == ()


def test_au_moins_un_coeur_si_la_fraction_est_minuscule() -> None:
    assert len(BC.coeurs_autorises(total=16, environnement={BC.VAR_FRACTION_COEURS: "0.01"})) == 1


# --------------------------------------------------------------------------- application


class _FauxProcessus:
    def __init__(self, pid: int = 4242) -> None:
        self.pid = pid


class _FauxPsutil:
    BELOW_NORMAL_PRIORITY_CLASS = 16384

    def __init__(self, *, echec_affinite: bool = False, echec_priorite: bool = False) -> None:
        self.echec_affinite = echec_affinite
        self.echec_priorite = echec_priorite
        self.affinite: list[int] | None = None
        self.priorite: int | None = None

    def Process(self, pid):  # noqa: N802 - imite l'API psutil
        return self

    def cpu_affinity(self, coeurs):
        if self.echec_affinite:
            raise OSError("acces refuse")
        self.affinite = list(coeurs)

    def nice(self, valeur):
        if self.echec_priorite:
            raise OSError("acces refuse")
        self.priorite = valeur


def test_affinite_posee_et_priorite_relevee() -> None:
    faux = _FauxPsutil()
    audit = BC.appliquer_budget_cpu(_FauxProcessus(), psutil_mod=faux,
                                    environnement={}, total_coeurs=16)
    assert len(faux.affinite or []) == 9
    assert faux.priorite == _FauxPsutil.BELOW_NORMAL_PRIORITY_CLASS
    assert audit["priorite"] == "BELOW_NORMAL"
    assert len(audit["coeurs"]) == 9


def test_sans_affinite_la_priorite_reste_idle() -> None:
    """LA règle fail-safe : pas de cœurs bornés => pas de priorité relevée."""
    faux = _FauxPsutil(echec_affinite=True)
    audit = BC.appliquer_budget_cpu(_FauxProcessus(), psutil_mod=faux,
                                    environnement={}, total_coeurs=16)
    assert faux.priorite is None, "la priorite a ete relevee SANS borner les coeurs"
    assert audit["priorite"] == "IDLE"
    assert "affinite refusee" in audit["raison"]


def test_priorite_refusee_garde_l_affinite() -> None:
    faux = _FauxPsutil(echec_priorite=True)
    audit = BC.appliquer_budget_cpu(_FauxProcessus(), psutil_mod=faux,
                                    environnement={}, total_coeurs=16)
    assert len(faux.affinite or []) == 9        # le gain de cœurs est conservé
    assert audit["priorite"] == "IDLE"
    assert len(audit["coeurs"]) == 9


def test_processus_sans_pid_ne_leve_pas() -> None:
    audit = BC.appliquer_budget_cpu(object(), psutil_mod=_FauxPsutil(),
                                    environnement={}, total_coeurs=16)
    assert audit["raison"] == "processus sans pid"
    assert audit["priorite"] == "IDLE"


def test_fraction_nulle_ne_touche_a_rien() -> None:
    faux = _FauxPsutil()
    audit = BC.appliquer_budget_cpu(_FauxProcessus(), psutil_mod=faux,
                                    environnement={BC.VAR_FRACTION_COEURS: "0"}, total_coeurs=16)
    assert faux.affinite is None and faux.priorite is None
    assert audit["raison"] == "aucune affinite demandee"


# --------------------------------------------------------------------------- RAM mesurée


def test_plafond_rss_par_defaut_et_reglable() -> None:
    assert S.plafond_rss_mo({}) == 700.0
    assert S.plafond_rss_mo({S.VAR_PLAFOND_RSS: "250"}) == 250.0
    assert S.plafond_rss_mo({S.VAR_PLAFOND_RSS: "illisible"}) == 700.0


class _Memoire:
    def __init__(self, rss: int) -> None:
        self.rss = rss


class _FauxProc:
    def __init__(self, pid: int, ligne: list[str], rss: int) -> None:
        self.info = {"pid": pid, "cmdline": ligne, "memory_info": _Memoire(rss)}


class _PsutilProcessus:
    def __init__(self, procs, moi: int) -> None:
        self._procs = procs
        self._moi = moi

    def process_iter(self, _champs=None):
        return list(self._procs)

    def Process(self, pid):  # noqa: N802
        return self

    def parents(self):
        return []


def test_rss_est_attribue_au_bon_collecteur() -> None:
    faux = _PsutilProcessus([
        _FauxProc(10, ["python", "tools/collecter_bbo.py"], 120 * 1048576),
        _FauxProc(11, ["python", "tools/collecter_allmids.py"], 30 * 1048576),
    ], moi=99)
    mesure = S.rss_par_collecteur(psutil_mod=faux, mon_pid=99)
    assert mesure["bbo-collector"] == 120.0
    assert mesure["allmids-collector"] == 30.0


def test_le_mesureur_ne_se_compte_jamais_lui_meme() -> None:
    """Piège connu : un filtre dont le motif est dans sa PROPRE ligne de commande se compte."""
    faux = _PsutilProcessus([
        _FauxProc(99, ["python", "-c", "audit de tools/collecter_bbo.py"], 500 * 1048576),
    ], moi=99)
    assert S.rss_par_collecteur(psutil_mod=faux, mon_pid=99) == {}


def test_plusieurs_processus_du_meme_collecteur_s_additionnent() -> None:
    faux = _PsutilProcessus([
        _FauxProc(10, ["python", "tools/collecter_bbo.py"], 40 * 1048576),
        _FauxProc(12, ["python", "tools/collecter_bbo.py"], 60 * 1048576),
    ], moi=99)
    assert S.rss_par_collecteur(psutil_mod=faux, mon_pid=99)["bbo-collector"] == 100.0


def test_sans_psutil_la_mesure_rend_vide_sans_lever() -> None:
    class _Rien:
        def process_iter(self, _champs=None):
            raise AssertionError("ne doit pas etre appele")

    assert S.rss_par_collecteur(psutil_mod=_PsutilProcessus([], moi=os.getpid())) == {}


def test_etat_collecteurs_expose_la_ram_et_le_depassement(tmp_path: Path) -> None:
    etats = S.etat_collecteurs(tmp_path)
    assert etats, "le registre ne doit pas etre vide"
    for e in etats:
        assert "rss_mo" in e and "trop_gros" in e and "plafond_rss_mo" in e
        assert e["trop_gros"] is False or e["rss_mo"] is not None
