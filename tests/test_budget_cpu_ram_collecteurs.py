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
    """CHANGÉ LE 21/11/2026 sur demande de l'opérateur : « non, les 16 cœurs à 50 % ».

    L'épinglage de 9 cœurs sur 16 (60 %, décision du 19/11) laissait 7 cœurs au repos
    pendant que 9 saturaient. La consigne est désormais un plafond d'INTENSITÉ : aucune
    affinité, donc les 16 cœurs disponibles, et la charge bornée par
    ``PLAFOND_CHARGE_CPU_DEFAUT``. Les deux réglages restent surchargeables.
    """
    assert BC.fraction_coeurs({}) == 1.0
    assert BC.FRACTION_COEURS_DEFAUT == 1.0


def test_fraction_reglable_par_environnement() -> None:
    assert BC.fraction_coeurs({BC.VAR_FRACTION_COEURS: "0.25"}) == 0.25
    assert BC.fraction_coeurs({BC.VAR_FRACTION_COEURS: "0,25"}) == 0.25  # virgule française


def test_fraction_illisible_ou_hors_bornes_ne_casse_rien() -> None:
    assert BC.fraction_coeurs({BC.VAR_FRACTION_COEURS: "beaucoup"}) == 1.0
    assert BC.fraction_coeurs({BC.VAR_FRACTION_COEURS: "0"}) == 0.0      # désactivé
    assert BC.fraction_coeurs({BC.VAR_FRACTION_COEURS: "-1"}) == 0.0
    assert BC.fraction_coeurs({BC.VAR_FRACTION_COEURS: "7"}) == 0.0


def test_les_seize_coeurs_restent_disponibles() -> None:
    """La machine de l'opérateur : 16 cœurs, aucun épinglage — c'est la consigne du 21/11."""
    assert BC.coeurs_autorises(total=16, environnement={}) == ()


def test_les_premiers_coeurs_restent_libres_quand_on_epingle() -> None:
    """Le mécanisme d'épinglage reste couvert : s'il est demandé, il épargne le bas.

    Les cœurs du bas portent l'interface : ce sont ceux que l'opérateur sent en premier.
    Ce test exerce donc une fraction EXPLICITE, puisque le défaut n'épingle plus rien.
    """
    coeurs = BC.coeurs_autorises(total=16, environnement={BC.VAR_FRACTION_COEURS: "0.6"})
    assert len(coeurs) == 9
    assert coeurs == (7, 8, 9, 10, 11, 12, 13, 14, 15)
    assert 0 not in coeurs and 6 not in coeurs


# ------------------------------------------------------------------ plafond d'intensité CPU


def test_le_plafond_de_charge_est_la_moitie_de_la_machine() -> None:
    """« Les 16 cœurs à 50 % » : huit cœurs de TRAVAIL étalés sur seize, pas huit saturés."""
    assert BC.PLAFOND_CHARGE_CPU_DEFAUT == 0.5
    assert BC.plafond_charge_cpu({}) == 0.5
    assert BC.coeurs_equivalents_autorises(total=16, environnement={}) == 8.0


def test_le_plafond_est_reglable_et_jamais_leve_par_erreur() -> None:
    """Un plafond illisible ou absurde ne doit pas devenir « pas de plafond »."""
    assert BC.plafond_charge_cpu({BC.VAR_PLAFOND_CHARGE_CPU: "0.25"}) == 0.25
    assert BC.plafond_charge_cpu({BC.VAR_PLAFOND_CHARGE_CPU: "0,75"}) == 0.75
    for absurde in ("beaucoup", "0", "-1", "7", ""):
        assert BC.plafond_charge_cpu({BC.VAR_PLAFOND_CHARGE_CPU: absurde}) == 0.5


def test_le_depassement_se_mesure_en_coeurs_pleins() -> None:
    """psutil rend 100 % par cœur plein : 8 cœurs autorisés = 800 % de cohorte."""
    assert BC.charge_cpu_depassee(799.0, total=16, environnement={}) is False
    assert BC.charge_cpu_depassee(801.0, total=16, environnement={}) is True
    assert BC.charge_cpu_depassee(0.0, total=16, environnement={}) is False
    # Mesure absurde => on respire (fail-closed), on ne pousse pas.
    assert BC.charge_cpu_depassee(-1.0, total=16, environnement={}) is True


def test_aucune_affinite_quand_elle_n_apporte_rien() -> None:
    assert BC.coeurs_autorises(total=16, environnement={BC.VAR_FRACTION_COEURS: "1.0"}) == ()
    assert BC.coeurs_autorises(total=1, environnement={}) == ()
    assert BC.coeurs_autorises(total=16, environnement={BC.VAR_FRACTION_COEURS: "0"}) == ()


def test_au_moins_un_coeur_si_la_fraction_est_minuscule() -> None:
    assert len(BC.coeurs_autorises(total=16, environnement={BC.VAR_FRACTION_COEURS: "0.01"})) == 1


# --------------------------------------------------------------------------- application

#: Le défaut n'épingle plus (consigne du 21/11 : les 16 cœurs à 50 %). Les tests qui
#: vérifient la POSE de l'affinité demandent donc explicitement une part de cœurs —
#: sinon ils ne vérifieraient que le nouveau défaut, et le mécanisme d'épinglage
#: cesserait d'être couvert le jour où quelqu'un le remet en service.
EPINGLE = {"HL_COLLECTEURS_FRACTION_COEURS": "0.6"}


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
                                    environnement=EPINGLE, total_coeurs=16)
    assert len(faux.affinite or []) == 9
    assert faux.priorite == _FauxPsutil.BELOW_NORMAL_PRIORITY_CLASS
    assert audit["priorite"] == "BELOW_NORMAL"
    assert len(audit["coeurs"]) == 9


def test_sans_affinite_la_priorite_reste_idle() -> None:
    """LA règle fail-safe : pas de cœurs bornés => pas de priorité relevée."""
    faux = _FauxPsutil(echec_affinite=True)
    audit = BC.appliquer_budget_cpu(_FauxProcessus(), psutil_mod=faux,
                                    environnement=EPINGLE, total_coeurs=16)
    assert faux.priorite is None, "la priorite a ete relevee SANS borner les coeurs"
    assert audit["priorite"] == "IDLE"
    assert "affinite refusee" in audit["raison"]


def test_priorite_refusee_garde_l_affinite() -> None:
    faux = _FauxPsutil(echec_priorite=True)
    audit = BC.appliquer_budget_cpu(_FauxProcessus(), psutil_mod=faux,
                                    environnement=EPINGLE, total_coeurs=16)
    assert len(faux.affinite or []) == 9        # le gain de cœurs est conservé
    assert audit["priorite"] == "IDLE"
    assert len(audit["coeurs"]) == 9


def test_processus_sans_pid_ne_leve_pas() -> None:
    audit = BC.appliquer_budget_cpu(object(), psutil_mod=_FauxPsutil(),
                                    environnement=EPINGLE, total_coeurs=16)
    assert audit["raison"] == "processus sans pid"
    assert audit["priorite"] == "IDLE"


def test_le_defaut_ne_touche_plus_a_l_affinite() -> None:
    """Consigne du 21/11 : les 16 coeurs disponibles, charge bornee ailleurs.

    Aucun epinglage n'est pose, et la priorite reste IDLE -- donc les collecteurs
    cedent le processeur des qu'une application normale le demande.
    """
    faux = _FauxPsutil()
    audit = BC.appliquer_budget_cpu(_FauxProcessus(), psutil_mod=faux,
                                    environnement={}, total_coeurs=16)
    assert faux.affinite is None and faux.priorite is None
    assert audit["raison"] == "aucune affinite demandee"
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


# ------------------------------------------------- plafond de COHORTE (50 % de la machine)


def test_le_plafond_de_cohorte_est_la_moitie_de_la_machine() -> None:
    """Consigne du 21/11/2026 : « 50 % cpu et 50 % memoire, moitie moitie ».

    Le plafond par collecteur (700 Mo) ne borne PAS le total : 20 familles a 700 Mo
    feraient 14 Go sans qu'aucune ne depasse sa part. Les deux plafonds servent donc a
    des choses differentes -- l'un contre une fuite isolee, l'autre contre la somme.
    """
    assert S.PLAFOND_RAM_COHORTE_FRACTION_DEFAUT == 0.5
    assert S.plafond_ram_cohorte_fraction({}) == 0.5
    # 31,9 Go de la machine de l'operateur, exprimes en Mo.
    assert S.plafond_ram_cohorte_mo(total_mo=32768.0, environnement={}) == 16384.0


def test_le_plafond_de_cohorte_est_reglable_et_jamais_leve_par_erreur() -> None:
    assert S.plafond_ram_cohorte_fraction({S.VAR_PLAFOND_RAM_COHORTE: "0.25"}) == 0.25
    assert S.plafond_ram_cohorte_fraction({S.VAR_PLAFOND_RAM_COHORTE: "0,8"}) == 0.8
    for absurde in ("illisible", "0", "-1", "3", ""):
        assert S.plafond_ram_cohorte_fraction({S.VAR_PLAFOND_RAM_COHORTE: absurde}) == 0.5


def test_le_depassement_de_cohorte_se_mesure_sur_la_somme() -> None:
    assert S.cohorte_au_plafond(16000.0, total_mo=32768.0, environnement={}) is False
    assert S.cohorte_au_plafond(16500.0, total_mo=32768.0, environnement={}) is True
    # Mesure absurde => on SIGNALE, on ne rassure pas.
    assert S.cohorte_au_plafond(-1.0, total_mo=32768.0, environnement={}) is True


def test_un_plafond_inconnu_ne_vaut_pas_voie_libre() -> None:
    """`None` dit « je ne sais pas » : l'appelant ne doit pas conclure que tout va bien."""
    assert S.plafond_ram_cohorte_mo(total_mo=0.0, environnement={}) is None
    assert S.cohorte_au_plafond(99999.0, total_mo=0.0, environnement={}) is None


# ------------------------------------------- moitie CPU : MESUREE, pas seulement declaree


class _Temps:
    def __init__(self, user: float, system: float) -> None:
        self.user = user
        self.system = system


class _ProcCpu:
    """Processus dont le temps CPU AVANCE entre deux echantillons."""

    def __init__(self, pid: int, ligne: str, consomme: float) -> None:
        self.info = {"pid": pid, "cmdline": ligne.split(" ")}
        self._consomme = consomme
        self._appels = 0

    def cpu_times(self):
        self._appels += 1
        return _Temps(self._consomme * (self._appels - 1), 0.0)


class _PsutilCpu:
    def __init__(self, procs) -> None:
        self._procs = procs

    def process_iter(self, _champs=None):
        return list(self._procs)

    def Process(self, pid):  # noqa: N802 - imite psutil
        raise RuntimeError("pas d'ancetres dans ce double")


def test_la_charge_cpu_est_mesuree_sur_deux_echantillons() -> None:
    """`cpu_percent()` rend 0.0 au premier appel : un plafond branche dessus ne
    declencherait JAMAIS. On mesure donc la difference de temps CPU consomme."""
    script = S.REGISTRE[0]["script"].replace(chr(92), "/").rsplit("/", 1)[-1]
    # Un processus qui consomme 0,2 s de CPU entre les deux echantillons.
    faux = _PsutilCpu([_ProcCpu(10101, "python.exe tools/%s --root ." % script, 0.2)])
    charge = S.charge_cpu_cohorte(psutil_mod=faux, mon_pid=1, intervalle_s=0.1)
    assert charge is not None
    assert charge > 100.0, charge      # 0,2 s de CPU en ~0,1 s => plus d'un coeur plein


def test_aucun_collecteur_vivant_ne_vaut_pas_zero() -> None:
    """`None` dit « non mesure ». Rendre 0.0 ferait croire a une collecte au repos."""
    assert S.charge_cpu_cohorte(psutil_mod=_PsutilCpu([]), mon_pid=1,
                                intervalle_s=0.05) is None
    assert S.cpu_au_plafond(None) is None


def test_le_plafond_cpu_se_compare_aux_coeurs_equivalents() -> None:
    """8 coeurs equivalents sur 16 = 800 % de cohorte, comme psutil les compte."""
    assert S.cpu_au_plafond(799.0, total_coeurs=16, environnement={}) is False
    assert S.cpu_au_plafond(801.0, total_coeurs=16, environnement={}) is True


def test_l_etat_publie_porte_les_deux_moities() -> None:
    """Un plafond invisible dans l'etat ne sert a personne : il doit etre RENDU."""
    from pathlib import Path as _Path
    etat = S.etat_collecteurs(_Path("."), profil="all")
    assert etat, "le registre ne decrit aucun collecteur"
    premier = etat[0]
    for champ in ("rss_cohorte_mo", "plafond_cohorte_mo", "cohorte_au_plafond",
                  "cpu_cohorte_pourcent", "plafond_cpu_pourcent", "cpu_au_plafond"):
        assert champ in premier, champ
    assert premier["plafond_cpu_pourcent"] > 0.0
