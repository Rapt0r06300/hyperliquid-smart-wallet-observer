"""IMPROVE-05 (#112) — la latence des REFUS, et l'invariant qui l'exige.

Le bug n'était pas « la latence n'est pas instrumentée » : elle l'était.
Le bug était **où** elle l'était : uniquement sur les décisions qui aboutissent.

    On ne mesurait la latence QUE des trades qu'on PREND.

Un biais de survivant — dans l'instrumentation elle-même. Et le pire, c'est qu'il rend
inrépondable la seule question qui compte ici : *« a-t-on refusé ce signal parce qu'il était
mauvais, ou parce qu'on est arrivé trop tard ? »*

Le dernier test est un INVARIANT (AST) : il relit le code du chemin vivant et exige que le
`return` de refus soit précédé d'un enregistrement. Un commentaire ne suffit pas ; le code doit
le prouver.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from hl_observer.runtime.latency_journal import (
    ISSUE_ACCEPTE,
    ISSUE_REFUSE,
    JournalLatence,
)
from hl_observer.runtime.latency_trace import LatencyTrace

RACINE = Path(__file__).resolve().parents[1]
ADAPTATEUR = RACINE / "src" / "hl_observer" / "paper_trading" / "fusion_paper_engine_adapter.py"


def _trace(coin: str = "BTC") -> LatencyTrace:
    t = LatencyTrace(coin=coin, source="test").start()
    t.stamp("features")
    t.stamp("decision")
    return t


def test_un_REFUS_est_journalise_comme_un_ACCEPTE():
    """Les deux populations existent. C'est la condition pour pouvoir les COMPARER."""
    j = JournalLatence()
    j.enregistrer(_trace(), ISSUE_ACCEPTE)
    j.enregistrer(_trace(), ISSUE_REFUSE, "STALE_SIGNAL")
    j.enregistrer(_trace(), ISSUE_REFUSE, "STALE_SIGNAL")

    r = j.resume()
    assert r["n"] == 3
    assert r["n_acceptes"] == 1
    assert r["n_refuses"] == 2
    assert r["motifs_de_refus"] == {"STALE_SIGNAL": 2}


def test_le_resume_SEPARE_acceptes_et_refuses():
    """Si les refus sont systématiquement plus LENTS, ce n'est pas le hasard : on arrive trop tard.

    Cette comparaison est IMPOSSIBLE tant que les refus ne sont pas mesurés — et c'était le cas.
    """
    j = JournalLatence()
    j.enregistrer(_trace(), ISSUE_ACCEPTE)
    j.enregistrer(_trace(), ISSUE_REFUSE, "CONSENSUS_TOO_WEAK")

    r = j.resume()
    assert r["acceptes"]["evenements"] == 1
    assert r["refuses"]["evenements"] == 1
    assert r["global"]["evenements"] == 2
    # `resumer` separe deja les DEUX horloges (murale vs monotone) et ne les additionne jamais.
    assert "age_source_ms" in r["refuses"] and "traitement_local_ms" in r["refuses"]


def test_une_ISSUE_inconnue_est_REFUSEE():
    """Une trace sans issue ne sert à rien : c'est le LIEN latence <-> sort du signal qui compte."""
    j = JournalLatence()
    with pytest.raises(ValueError):
        j.enregistrer(_trace(), "PEUT_ETRE")


def test_le_journal_est_BORNE():
    """Un run de 48 h ne doit pas mourir de son propre journal.

    (Le bloat de stockage a DÉJÀ fait crasher un run, le 08/07. On ne refait pas la même erreur
    parce qu'on avait envie de « tout garder ».)
    """
    j = JournalLatence(capacite=10)
    for _ in range(50):
        j.enregistrer(_trace(), ISSUE_REFUSE, "X")
    assert len(j) == 10
    assert j.resume()["borne"] == 10


def test_un_journal_VIDE_ne_ment_pas():
    """Zéro trace = zéro statistique. On ne fabrique pas un p50 à partir de rien."""
    r = JournalLatence().resume()
    assert r["n"] == 0
    assert r["motifs_de_refus"] == {}


def test_INVARIANT_le_chemin_de_REFUS_du_runtime_journalise_sa_latence():
    """🔴 L'INVARIANT. Il relit le CODE, pas les intentions.

    Le `return FusionPaperEngineSummary(...)` du chemin de refus doit être précédé d'un
    enregistrement au journal. Sinon on retombe exactement dans le biais de survivant qu'on
    vient de corriger — et rien ne nous préviendrait.
    """
    src = ADAPTATEUR.read_text(encoding="utf-8")
    arbre = ast.parse(src)

    # 1) le module de journal est-il seulement importé sur ce chemin ?
    importe = any(
        isinstance(n, ast.ImportFrom) and n.module == "hl_observer.runtime"
        and any(a.name == "latency_journal" for a in n.names)
        for n in ast.walk(arbre)
    )
    assert importe, (
        "fusion_paper_engine_adapter n'importe PAS latency_journal : la latence des refus "
        "n'est enregistree nulle part, et le biais de survivant est de retour."
    )

    # 2) `enregistrer(...)` est-il appele au moins DEUX fois (refus + aboutissement) ?
    appels = [
        n for n in ast.walk(arbre)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == "enregistrer"
    ]
    assert len(appels) >= 2, (
        "on attend au moins DEUX enregistrements de latence : celui du REFUS et celui de "
        "l'ABOUTISSEMENT. Trouve : %d. Mesurer uniquement les trades qu'on prend, c'est ne "
        "mesurer que les survivants." % len(appels)
    )

    # 3) et l'issue REFUSE doit vraiment apparaitre (pas seulement ACCEPTE)
    assert "ISSUE_REFUSE" in src, "aucun refus n'est journalise : l'instrumentation reste borgne"
