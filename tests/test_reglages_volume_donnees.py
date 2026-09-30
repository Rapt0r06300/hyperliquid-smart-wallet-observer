"""VOLUME DE DONNÉES (20/07, décision de Flo) — plus de positions, JAMAIS d'incohérence.

L'argument de Flo est juste : « un replay A/B se fait sur des données ». Le plafond
break-even passe donc de 120 h à 235 h dans le lanceur (fenêtre d'admission doublée).

MAIS il y a un piège que ces tests rendent impossible : un break-even au-dessus de
l'ÂGE MAX (336 h) fabrique des positions expulsées par SORTIE_AGE **avant d'avoir
amorti leur entrée** — une perte garantie par construction, du churn déguisé en volume.
Le cliquet : plafond BE ≤ 0,7 × âge max, pour amortir ET engranger avant l'expulsion.
"""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

from hl_observer.funding.carry_position_lifecycle import AGE_MAX_H_DEFAUT

RACINE = Path(__file__).resolve().parents[1]


def _env_lanceur(nom: str) -> float | None:
    texte = (RACINE / "LANCER_HYPERSMART.cmd").read_text(encoding="utf-8", errors="ignore")
    m = re.search(r'set "%s=([0-9.]+)"' % re.escape(nom), texte)
    return float(m.group(1)) if m else None


def test_le_plafond_du_lanceur_est_ELARGI_mais_COHERENT():
    """La demande de Flo (plus d'admissions) ET la physique du carry (amortir avant l'âge)."""
    be = _env_lanceur("HYPERSMART_CARRY_MAX_BREAK_EVEN_H")
    assert be is not None, "le lanceur doit fixer HYPERSMART_CARRY_MAX_BREAK_EVEN_H"
    assert be >= 235.0, "fenetre d'admission elargie (decision volume-de-donnees du 20/07)"
    assert be <= 0.7 * AGE_MAX_H_DEFAUT, (
        "CLIQUET : BE %.0f h > 0,7 x age max (%.0f h) -> les positions seraient expulsees "
        "par SORTIE_AGE avant d'avoir amorti : perte garantie par construction. On n'achete "
        "pas du volume de donnees avec du churn." % (be, AGE_MAX_H_DEFAUT))


def test_le_feeder_HONORE_l_env_du_lanceur(monkeypatch):
    """Mention != porte : l'env doit etre LU par le scanner, pas seulement ecrit au lanceur."""
    monkeypatch.setenv("HYPERSMART_CARRY_MAX_BREAK_EVEN_H", "235")
    spec = importlib.util.spec_from_file_location(
        "feeder_env_test", RACINE / "tools" / "ecrire_carry_spot_inputs.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    assert m.MAX_BREAK_EVEN_H == 235.0


def test_une_valeur_illisible_retombe_sur_le_defaut_SUR(monkeypatch):
    monkeypatch.setenv("HYPERSMART_CARRY_MAX_BREAK_EVEN_H", "n_importe_quoi")
    spec = importlib.util.spec_from_file_location(
        "feeder_env_test2", RACINE / "tools" / "ecrire_carry_spot_inputs.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    assert m.MAX_BREAK_EVEN_H == 120.0, "fail-safe : jamais un plafond infini par accident"
