"""La SUITE doit refuser un chemin d'exécution réelle, pas seulement l'audit.

MESURE DU 21/11/2026 — pourquoi ce fichier existe. Quatre violations du contrat ont été
injectées dans `src/hl_observer/ops/` : `import eth_account`, lecture de
`HL_PRIVATE_KEY` dans l'environnement, appel `place_mainnet_order`, et un littéral
`/exchange`. Les **49 tests** des huit fichiers les plus sécuritaires du dépôt
(`test_hypersmart_audit_safety`, `test_audit_preuves_securite`, `test_testnet_locked`,
`test_runtime_mode_denials`, `test_q265_runtime_flags_safe_defaults`,
`test_no_profit_promise_docs`, `test_invariants_architecture`,
`test_v12_fake_data_scanner`) sont restés **verts dans les quatre cas**.

Les règles existaient — `c_lib_signature`, `c_env_privkey`, `c_no_real_exec`, toutes
bloquantes — mais seulement dans `tools/audit_report.py`, une batterie de plus d'une
heure qu'on lance à la main. Entre deux audits, rien dans la passe de tests n'empêchait
une librairie de signature d'entrer dans le dépôt.

Coût mesuré de ce fichier : ~33 s (27,6 + 0,6 + 4,6 ; le premier contrôle paye la
lecture des sources, les suivants réutilisent le cache de l'audit). C'est le prix d'une
garde que la suite applique à chaque passe.
"""
from __future__ import annotations

import importlib.util
import sys
from functools import lru_cache
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]


@lru_cache(maxsize=1)
def _audit():
    """Charge `tools/audit_report.py` UNE fois : son cache de fichiers est partagé.

    Un chargement par test multiplierait par trois la lecture des sources.
    """
    spec = importlib.util.spec_from_file_location(
        "audit_report_securite", RACINE / "tools" / "audit_report.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["audit_report_securite"] = module
    spec.loader.exec_module(module)
    return module


# Les trois regles de chemin d execution, plus les quatre regles d honnetete dont
# la meme experience du 21/11/2026 a montre qu AUCUN test local ne les appliquait :
# shell=True, wallet-connect, promesse de PnL, PnL code en dur dans l UI LIVE ont
# traverse 62 tests verts. Cout mesure de l ensemble : ~35 s (seule la premiere
# regle paye la lecture des sources, le cache de l audit etant partage).
REGLES = (
    "c_lib_signature", "c_env_privkey", "c_no_real_exec",
    "c_shell_true", "c_wallet_connect", "c_profit_promise", "c_pnl_hardcoded",
    # Ajoutee le 21/11/2026 au soir : le passage des 107 regles structurelles a montre
    # que `c_exchange_url` accusait LA MEME ligne de garde que la regle 13, deja
    # corrigee -- deux regles, un seul garde innocent, et n'en corriger qu'une laissait
    # l'audit rouge.
    "c_exchange_url",
)


@pytest.mark.parametrize("nom_regle", REGLES)
def test_le_depot_ne_porte_aucun_chemin_d_execution_reelle(nom_regle):
    """Les trois règles bloquantes de l'audit, appliquées DANS la suite."""
    verdict = getattr(_audit(), nom_regle)()
    assert verdict.blocking is True, f"{nom_regle} n'est plus bloquante"
    assert verdict.ok, f"{nom_regle} : {verdict.errors[:5]}"


@pytest.mark.parametrize(
    ("nom_regle", "source"),
    [
        ("c_lib_signature", "import eth_account\n"),
        ("c_lib_signature", "from web3 import Web3\n"),
        ("c_env_privkey", "import os\nCLE = os.environ.get('HL_PRIVATE_KEY')\n"),
        ("c_env_privkey", "import os\nCLE = os.getenv('WALLET_SECRET_KEY')\n"),
        ("c_no_real_exec", "URL = '/exchange'\n"),
        ("c_no_real_exec", "def envoyer(cx, o):\n    return cx.place_mainnet_order(o)\n"),
        ("c_no_real_exec", "def signer(c, m):\n    return c.sign_typed_data(m)\n"),
    ],
)
def test_chaque_regle_rougit_sur_la_violation_quelle_garde(tmp_path, monkeypatch,
                                                           nom_regle, source):
    """Une règle verte qui ne peut pas rougir ne garde rien.

    On remplace la liste de fichiers scannés : aucun fichier n'est écrit dans `src/`,
    et la mesure reste instantanée.
    """
    module = _audit()
    piege = tmp_path / "module_injecte.py"
    piege.write_text(source, encoding="utf-8", newline="\n")
    monkeypatch.setattr(module, "_py_files", lambda *dirs: [piege])
    monkeypatch.setattr(module, "_rel", lambda chemin: chemin.name)
    verdict = getattr(module, nom_regle)()
    assert not verdict.ok, f"{nom_regle} n'a pas vu : {source.strip()!r}"


def test_un_fichier_propre_ne_declenche_aucune_des_trois_regles(tmp_path, monkeypatch):
    """Le pendant du test ci-dessus : pas de faux positif sur du code ordinaire."""
    module = _audit()
    propre = tmp_path / "module_propre.py"
    propre.write_text(
        "import os\n\n\ndef lire_racine():\n"
        "    return os.environ.get('HL_OBSERVER_ROOT')\n",
        encoding="utf-8", newline="\n")
    monkeypatch.setattr(module, "_py_files", lambda *dirs: [propre])
    monkeypatch.setattr(module, "_rel", lambda chemin: chemin.name)
    for nom_regle in REGLES:
        verdict = getattr(module, nom_regle)()
        assert verdict.ok, f"{nom_regle} crie au loup : {verdict.errors[:3]}"


@pytest.mark.parametrize(
    ("nom_regle", "source"),
    [
        ("c_shell_true", "import subprocess\nsubprocess.run('dir', shell=True)\n"),
        ("c_wallet_connect", "wallet_connect = True\n"),
        ("c_profit_promise", "MESSAGE = 'guaranteed profit on every copy'\n"),
        ("c_pnl_hardcoded", "net_pnl = 1234.56\n"),
        ("c_exchange_url", "URL = 'https://api.hyperliquid.xyz/exchange'\n"),
    ],
)
def test_chaque_regle_d_honnetete_rougit_sur_sa_violation(tmp_path, monkeypatch,
                                                          nom_regle, source):
    """Les quatre violations qui traversaient 62 tests verts le 21/11/2026."""
    module = _audit()
    piege = tmp_path / "module_injecte.py"
    piege.write_text(source, encoding="utf-8", newline="\n")
    monkeypatch.setattr(module, "_py_files", lambda *dirs: [piege])
    monkeypatch.setattr(module, "_rel", lambda chemin: chemin.name)
    verdict = getattr(module, nom_regle)()
    assert not verdict.ok, f"{nom_regle} n'a pas vu : {source.strip()!r}"


@pytest.mark.parametrize(
    ("source", "ligne", "ignore"),
    [
        ("# on evite shell=True ici\n", 1, True),
        ('"""Docstring citant shell=True."""\n', 1, True),
        ("import subprocess\nsubprocess.run('dir', shell=True)\n", 2, False),
        ("def f(:\n  shell=True\n", 2, False),
    ],
)
def test_un_shell_true_cite_n_est_pas_un_appel(source, ligne, ignore):
    """MESURE DU 21/11/2026 : la regle accusait le COMMENTAIRE du correctif.

    `src/hl_observer/ops/crash_notification.py:69` explique que l'injection PowerShell
    etait << invisible pour la regle qui cherche shell=True >> -- et contenait donc le
    motif. Le dernier cas verifie le fail-closed : un fichier inanalysable n'est jamais
    blanchi.
    """
    module = _audit()
    assert module._shell_true_hors_code(source, ligne) is ignore
