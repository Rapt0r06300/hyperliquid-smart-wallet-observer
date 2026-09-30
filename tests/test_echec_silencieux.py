"""LE REGISTRE DES ÉCHECS AVALÉS + LE CLIQUET QUI EMPÊCHE LE SILENCE DE REVENIR.

CE QU'ON A TROUVÉ LE 2026-07-19 : **105 `except: pass`** dans `src/hl_observer`, dont 14 dans
`ui/routes.py`. Chacun est une panne qui ne remonte NULLE PART — ni log, ni compteur, ni trace.
C'est la même maladie que le `catch` vide du dashboard, celle qui laissait un panneau figé sur
« … » sans un mot et qui, vue de l'extérieur, s'appelait « l'UI est énormément buguée ».

CE QU'ON N'A PAS FAIT, ET POURQUOI : on n'a PAS supprimé l'avalement. Il est souvent délibéré et
juste — un panneau secondaire ne doit pas faire tomber la page, un journal qui échoue ne doit pas
casser une décision. Le défaut n'était pas d'avaler : c'était d'avaler **sans laisser de trace**.
Le comportement est donc identique ; seul un compteur a été ajouté.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from hl_observer.ops.echec_silencieux import MAX_SITES, noter, reinitialiser, resume

RACINE = Path(__file__).resolve().parents[1]
SRC = RACINE / "src" / "hl_observer"

# Exception volontaire très étroite : dans le worker autonome, l'écriture du
# fichier de statut est best-effort à l'intérieur d'un handler fatal qui imprime
# toujours ALINA_AUTONOMOUS_RESEARCH_NO_GO juste après. L'erreur principale ne
# disparaît donc jamais. Tout autre `except: pass` reste interdit.
VISIBLE_FATAL_FALLBACKS = {
    "ops/autonomous_research_job.py": "ALINA_AUTONOMOUS_RESEARCH_NO_GO",
}


@pytest.fixture(autouse=True)
def _propre():
    reinitialiser()
    yield
    reinitialiser()


# ------------------------------------------------------------------ le registre

def test_il_compte_par_site():
    noter("a.py:10"); noter("a.py:10"); noter("b.py:20")
    r = resume()
    assert r["total_echecs"] == 3 and r["n_sites"] == 2
    assert r["sites"][0]["site"] == "a.py:10" and r["sites"][0]["n"] == 2


def test_il_retient_le_TYPE_de_la_derniere_erreur():
    """« ×47 (dernier : KeyError) » est une piste. « rien » n'en est jamais une."""
    noter("x.py:1", KeyError("coin"))
    assert resume()["sites"][0]["dernier"] == "KeyError"


def test_il_ne_LEVE_JAMAIS():
    """Un enregistreur d'échecs qui plante serait une farce : il casserait le code qu'il observe.
    On lui envoie exprès n'importe quoi."""
    for mauvais in (None, 123, object(), b"\xff", "x" * 10_000):
        noter(mauvais)                       # type: ignore[arg-type]
    noter("ok", "pas une exception")         # type: ignore[arg-type]


def test_la_memoire_est_BORNEE():
    """Le bot tourne des jours : un registre qui grossit sans fin FINIRAIT par être le bug."""
    for i in range(MAX_SITES + 50):
        noter("site:%d" % i)
    assert resume()["n_sites"] <= MAX_SITES


def test_les_sites_deja_connus_continuent_de_compter_apres_saturation():
    for i in range(MAX_SITES):
        noter("s:%d" % i)
    noter("s:0"); noter("s:0")
    assert next(x for x in resume(MAX_SITES)["sites"] if x["site"] == "s:0")["n"] == 3


# ------------------------------------------------------------------ le cliquet

def _fallback_fatal_visible(rel: str, lines: list[str], handler: ast.ExceptHandler) -> bool:
    marker = VISIBLE_FATAL_FALLBACKS.get(rel)
    if not marker:
        return False
    end = int(getattr(handler, "end_lineno", 0) or 0)
    if end <= 0:
        return False
    # Le handler best-effort doit être immédiatement suivi du message fatal visible.
    window = "\n".join(lines[end : end + 12])
    return marker in window


def _sites_muets() -> list[str]:
    """Les `except ...: pass` réellement silencieux — repérés par AST, jamais par regex."""
    trouves = []
    for p in SRC.rglob("*.py"):
        if "__pycache__" in p.parts:
            continue
        rel = p.relative_to(SRC).as_posix()
        try:
            source = p.read_text(encoding="utf-8", errors="ignore")
            arbre = ast.parse(source)
        except SyntaxError:
            continue
        lines = source.splitlines()
        for n in ast.walk(arbre):
            if isinstance(n, ast.ExceptHandler) and len(n.body) == 1 and isinstance(n.body[0], ast.Pass):
                if _fallback_fatal_visible(rel, lines, n):
                    continue
                trouves.append("%s:%d" % (rel, n.body[0].lineno))
    return sorted(trouves)


def test_AUCUN_except_pass_ne_revient():
    """LE CLIQUET. 105 -> 0 silencieux le 19/07. Si quelqu'un en réintroduit un, ce test rougit.

    Un `except: pass` n'est pas un détail de style : c'est une panne rendue INVISIBLE. On peut
    parfaitement continuer à avaler l'erreur — mais en la COMPTANT (`_noter_echec(...)`) ou en
    garantissant un NO_GO visible juste après pour qu'elle laisse une piste au lieu d'un silence.
    """
    muets = _sites_muets()
    assert not muets, (
        "%d `except: pass` silencieux de retour — une panne y disparaîtra sans laisser de trace :\n    %s\n\n"
        "Remplace le `pass` par `_noter_echec(\"chemin:ligne\")` : même comportement (rien ne "
        "remonte, rien ne casse), mais un compteur qui monte est une piste." % (
            len(muets), "\n    ".join(muets[:15])))


def test_le_fallback_fatal_visible_est_le_seul_cas_tolere():
    lines = ["x"] * 20
    lines[8] = 'print("ALINA_AUTONOMOUS_RESEARCH_NO_GO")'
    handler = ast.ExceptHandler(type=None, name=None, body=[ast.Pass(lineno=7)])
    handler.end_lineno = 7
    assert _fallback_fatal_visible("ops/autonomous_research_job.py", lines, handler) is True
    assert _fallback_fatal_visible("ops/autonomous_research_guard.py", lines, handler) is False


def test_le_module_compteur_ne_s_auto_instrumente_pas():
    """`echec_silencieux` capture ses propres erreurs pour ne jamais lever — il ne doit pas
    s'appeler lui-même (récursion infinie le jour où il échoue)."""
    src = (SRC / "ops" / "echec_silencieux.py").read_text(encoding="utf-8")
    assert "_noter_echec" not in src
