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

RACINE = Path(__file__).resolve().parents[1]


def _env_lanceur(nom: str) -> float | None:
    texte = (RACINE / "LANCER_HYPERSMART.cmd").read_text(encoding="utf-8", errors="ignore")
    m = re.search(r'set "%s=([0-9.]+)"' % re.escape(nom), texte)
    return float(m.group(1)) if m else None


def test_le_carry_historique_ne_se_reactive_pas_par_le_lanceur():
    """Copy-Vault only: the retired carry feeder has no live paper admission."""
    launcher = (RACINE / "LANCER_HYPERSMART.cmd").read_text(encoding="utf-8")
    assert 'set "HYPERSMART_CARRY_DISABLED=1"' in launcher
    assert 'set "HYPERSMART_FUNDING_ARB_PAPER=0"' in launcher
    assert _env_lanceur("HYPERSMART_CARRY_MAX_BREAK_EVEN_H") is None


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
