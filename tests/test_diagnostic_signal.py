"""Le module extrait tient DEBOUT SEUL, et le labo n'en garde pas une copie qui derive.

POURQUOI CE FICHIER (22/11/2026). `diagnostic_signal.py` est ne d'une extraction :
`copy_vault_local_lab.py` avait franchi son plafond epingle (5 018 lignes contre 4 971) et la
regle du depot interdit d'agrandir une dette historique. Le labo RE-EXPORTE les trois noms
pour ne casser aucun appelant.

Une re-export est exactement le genre d'endroit ou deux verites apparaissent sans qu'on le
voie : il suffit qu'un jour quelqu'un recopie la constante dans le labo << pour aller plus
vite >> et les deux chemins repondent des choses differentes, chacun teste de son cote. On
verifie donc ici que ce sont les MEMES objets, pas des valeurs egales par hasard.

On verifie aussi que le module s'importe SANS le labo. Si l'import inverse se glissait
(le module lisant la constante dans le labo), on aurait un cycle : l'extraction aurait
deplace le probleme au lieu de le resoudre.
"""
from __future__ import annotations

import importlib
import subprocess
import sys
from pathlib import Path

from hl_observer.backtesting import diagnostic_signal as DS

RACINE = Path(__file__).resolve().parents[1]
JOUR_MS = 86_400_000
DEBUT = 1_794_528_000_000


def test_le_module_s_importe_SANS_le_labo():
    """Un import inverse ferait un cycle : l'extraction n'aurait rien resolu."""
    code = (
        "import sys; "
        "import hl_observer.backtesting.diagnostic_signal as d; "
        "charges = [m for m in sys.modules if 'copy_vault_local_lab' in m]; "
        "print(d.MINIMUM_SIGNAL_UTC_DAYS, charges)"
    )
    fini = subprocess.run(
        [sys.executable, "-c", code], cwd=str(RACINE),
        capture_output=True, text=True, errors="replace", timeout=180,
    )
    assert fini.returncode == 0, fini.stderr[-400:]
    assert fini.stdout.split()[0] == "6"
    assert "[]" in fini.stdout, f"le labo a ete charge : {fini.stdout!r}"


def test_le_labo_RE_EXPORTE_les_memes_objets_et_pas_des_copies():
    """Deux verites pour une grandeur, c'est une divergence qui attend son jour."""
    labo = importlib.import_module("hl_observer.backtesting.copy_vault_local_lab")
    assert labo._MINIMUM_SIGNAL_UTC_DAYS is DS.MINIMUM_SIGNAL_UTC_DAYS
    assert labo._diagnostic_du_split is DS.diagnostic_du_split
    assert labo._signal_coverage is DS.signal_coverage


def test_les_quatre_motifs_du_diagnostic_sont_distincts():
    """Le motif doit separer MA faute de conception d'un vrai trou de donnees."""
    # Fenetre de 4 h : elle ne PEUT pas porter six jours UTC -> erreur de decoupe.
    etroite = DS.diagnostic_du_split([DEBUT + i * 600_000 for i in range(24)], seuil_jours=6)
    assert etroite["motif"] == "FENETRE_PLUS_ETROITE_QUE_L_UNITE_DE_DECOUPE"
    assert etroite["jours_possibles_dans_la_fenetre"] == 1

    # Fenetre de 8 jours mais du signal sur deux journees -> TROU de donnees.
    trouee = ([DEBUT + i * 600_000 for i in range(5)]
              + [DEBUT + 7 * JOUR_MS + i * 600_000 for i in range(5)])
    d = DS.diagnostic_du_split(trouee, seuil_jours=6)
    assert d["motif"] == "JOURS_UTC_INSUFFISANTS_DANS_LA_FENETRE"
    assert d["jours_possibles_dans_la_fenetre"] == 8 != d["jours_distincts"]

    # Huit journees pleines : la fenetre suffit ET le signal est la -> la purge seule reste.
    pleine = DS.diagnostic_du_split([DEBUT + i * (JOUR_MS // 3) for i in range(24)],
                                    seuil_jours=6)
    assert pleine["motif"] == "SPLIT_VIDE_APRES_PURGE"

    # Rien de lisible n'est PAS << pas assez de jours >>.
    assert DS.diagnostic_du_split([], seuil_jours=6)["motif"] == "AUCUN_HORODATAGE_LISIBLE"


def test_un_horodatage_non_entier_ne_compte_pas_pour_un_jour():
    """`"1794528000000"` accepte ferait croire a une journee de signal inexistante."""
    d = DS.diagnostic_du_split([str(DEBUT), None, True, -5, 0], seuil_jours=6)
    assert d["jours_distincts"] == 0
    assert d["motif"] == "AUCUN_HORODATAGE_LISIBLE"


def test_la_couverture_rend_la_LISTE_des_journees_pas_seulement_leur_nombre():
    """Sans la liste, `agregation_tranches.unir_les_jours` lisait zero partout et le seuil
    des six journees etait infranchissable -- constate a la premiere conduite reelle."""
    c = DS.signal_coverage([DEBUT, DEBUT + 7 * JOUR_MS])
    assert c["distinct_utc_days"] == 2
    assert len(c["utc_days"]) == 2
    assert all(len(j) == 10 and j[4] == "-" for j in c["utc_days"]), c["utc_days"]
    assert c["minimum_utc_days_required"] == DS.MINIMUM_SIGNAL_UTC_DAYS
    assert c["signal_span_hours"] == 168.0


def test_la_couverture_d_un_signal_vide_ne_fabrique_pas_de_bornes():
    """Des bornes a zero vaudraient 1970 et fausseraient toute mesure d'etendue."""
    c = DS.signal_coverage([])
    assert c["signal_count"] == 0
    assert c["signal_start_ms"] is None
    assert c["signal_end_ms"] is None
    assert c["signal_span_hours"] is None
    assert c["utc_days"] == []
