"""MEGATEST — l'orchestrateur des 7 controles doit tenir debout tout seul (2026-07-12).

Ce test protege trois choses :

1. **Aucun outil fantome.** Si quelqu'un renomme ou supprime `tools/mesurer_spread_carnet.py`,
   MEGATEST le decouvrirait a 2 h du matin, en pleine mesure. Ici, il le decouvre en CI.
2. **Le rapport existe TOUJOURS.** MEGATEST.md est reecrit apres chaque section : Ctrl-C ou
   crash, le rapport contient ce qui a ete mesure. Un rapport absent est pire qu'un rapport
   partiel.
3. **Le verdict ne ment pas.** Un echec doit ressortir comme un echec, jamais comme un "—".

Aucun ordre reel. Aucun reseau. Ces tests ne lancent AUCUN des 7 outils : ils testent
l'orchestrateur, pas le marche.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MEGATEST_PY = ROOT / "tools" / "megatest.py"


def _charger():
    """Charge tools/megatest.py hors package.

    NOTE : il FAUT l'enregistrer dans sys.modules AVANT exec_module. Avec
    `from __future__ import annotations`, @dataclass resout ses annotations via
    `sys.modules[cls.__module__]` -- absent, il leve un AttributeError obscur.
    """
    spec = importlib.util.spec_from_file_location("megatest", MEGATEST_PY)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["megatest"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_megatest_existe_et_sImporte() -> None:
    assert MEGATEST_PY.exists(), "tools/megatest.py a disparu — MEGATEST.cmd ne marchera plus."
    _charger()


def test_TOUS_les_outils_orchestres_existent_vraiment() -> None:
    """LE test qui compte. Un outil renomme = MEGATEST casse en pleine nuit."""
    source = MEGATEST_PY.read_text(encoding="utf-8")
    attendus = [
        "tools/audit_report.py",
        "tools/pourquoi_zero_position.py",
        "tools/measure_funding_gate.py",
        "tools/mesurer_spread_carnet.py",
        "tools/mesurer_carry_neutre.py",
        "tools/diagnostic_spot_hyperliquid.py",
        "tools/consulter_memoire.py",
        "tools/mesurer_flux_market_making.py",
    ]
    for rel in attendus:
        assert rel in source, (
            "MEGATEST n'orchestre plus %s — un des 7 controles a ete PERDU dans la fusion." % rel
        )
        assert (ROOT / rel).exists(), (
            "MEGATEST reference %s, qui n'existe PAS sur le disque. "
            "La section sera marquee OUTIL_ABSENT au pire moment." % rel
        )


def test_le_verdict_remonte_les_ECHECS_et_ne_les_avale_pas() -> None:
    m = _charger()
    assert "🔴" in m._verdict_depuis_sortie(">>> AUCUN MARCHE NE SURVIT. Ce n'est pas une panne.")
    assert "🔴" in m._verdict_depuis_sortie("  ECHECS DETECTES - NE PAS COMMITER")
    assert "🔴" in m._verdict_depuis_sortie("VERDICT : VERDICT_MORT")
    assert "🟢" in m._verdict_depuis_sortie("    TOUT EST VERT. Commit autorise.")
    # Une sortie sans signal connu ne doit PAS etre maquillee en succes.
    assert m._verdict_depuis_sortie("blabla sans verdict") == "—"


def test_le_rapport_est_ecrit_meme_si_AUCUNE_section_na_tourne(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Ctrl-C a la seconde 1 : MEGATEST.md doit exister quand meme."""
    m = _charger()
    cible = tmp_path / "MEGATEST.md"
    monkeypatch.setattr(m, "RAPPORT", cible)

    sections = [
        m.Section("a", "Controle A", "pourquoi A", ["tools/a.py"], 10.0),
        m.Section("b", "Controle B", "pourquoi B", ["tools/b.py"], 10.0, reseau=True),
    ]
    m._ecrire(sections, reseau_ok=False, reseau_note="hors ligne", mode="rapide")

    assert cible.exists(), "MEGATEST.md doit exister meme avec 0 section executee."
    txt = cible.read_text(encoding="utf-8")
    assert "MEGATEST" in txt
    assert "Controle A" in txt and "Controle B" in txt
    assert "0 ordre reel" in txt, "La ligne de securite doit figurer dans CHAQUE rapport."
    assert "NON_LANCE" in txt, "Une section non lancee doit etre dite non lancee, pas masquee."


def test_une_section_en_ECHEC_apparait_dans_la_synthese(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    m = _charger()
    cible = tmp_path / "MEGATEST.md"
    monkeypatch.setattr(m, "RAPPORT", cible)

    ko = m.Section("x", "Controle qui casse", "pourquoi", ["tools/x.py"], 10.0)
    ko.statut = "ECHEC(code=1)"
    ko.code = 1
    ko.sortie = "boum"
    m._ecrire([ko], reseau_ok=True, reseau_note="ok", mode="rapide")

    txt = cible.read_text(encoding="utf-8")
    assert "section(s) en echec" in txt.lower(), "Un echec DOIT etre remonte en tete de rapport."
    assert "Controle qui casse" in txt


def test_un_MARCHE_qui_dit_NON_nest_PAS_un_echec_de_code() -> None:
    """LE test qui evite de bloquer un commit pour rien.

    `mesurer_carry_neutre.py` renvoie 2 quand aucun carry n'est viable. C'est une REPONSE
    MESUREE, pas une panne. Si MEGATEST la traitait comme un echec, il dirait « ne pas
    commiter » parce que le marche ne coopere pas -- absurde.

    Seul l'audit du CODE est bloquant.
    """
    m = _charger()

    marche = m.Section("carry", "Carry", "mesure de marche", ["tools/x.py"], 10.0, bloquant=False)
    marche.statut = "VERDICT(code=2)"
    assert not marche.en_echec, (
        "Un verdict de marche defavorable NE DOIT PAS bloquer un commit."
    )

    code = m.Section("audit", "Audit", "le code", ["tools/audit_report.py"], 10.0, bloquant=True)
    code.statut = "ECHEC(code=1)"
    assert code.en_echec, "Un audit qui echoue DOIT bloquer le commit."


def test_le_mode_ci_ne_garde_QUE_le_controle_bloquant() -> None:
    """--ci (ex-ci_local.cmd) : avant un commit, on veut le CODE. Pas la meteo du marche.

    Exiger le reseau pour pouvoir commiter serait absurde.
    """
    source = MEGATEST_PY.read_text(encoding="utf-8")
    assert "--ci" in source, "Le mode --ci (ex-ci_local.cmd) a disparu."
    assert "s.bloquant" in source, (
        "Le mode --ci ne filtre plus sur les sections bloquantes : il relancerait "
        "les mesures de marche (et le reseau) avant chaque commit."
    )


def test_le_rapport_ne_promet_JAMAIS_de_pnl(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Regle dure du projet : ne jamais promettre un PnL positif."""
    m = _charger()
    cible = tmp_path / "MEGATEST.md"
    monkeypatch.setattr(m, "RAPPORT", cible)
    m._ecrire([m.Section("a", "A", "p", ["tools/a.py"], 1.0)], True, "ok", "rapide")

    txt = cible.read_text(encoding="utf-8").lower()
    assert "aucun pnl positif" in txt, (
        "Le rapport doit rappeler explicitement qu'il ne promet aucun PnL."
    )
