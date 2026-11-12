"""M1 — le gouverneur de mémoire est VRAIMENT branché sur l'étape 1 du labo (celle qui pique à 16 Go).

C'est ce processus que le système a tué deux fois le 12/11. Un module de gouvernance non appelé ne sert
à rien : le projet a déjà payé cette leçon (« MENTION ≠ PORTE », 23/25 gardes « branchés » étaient morts).
Ces tests verrouillent donc le COMPORTEMENT *et* le CÂBLAGE :

1. la pression est contrôlée À INTERVALLE (pas à chaque message : lire la RAM coûte) ;
2. en ROUGE on souffle brièvement puis on CONTINUE (jamais de blocage, jamais d'abandon) ;
3. une surveillance cassée ou absente ne casse JAMAIS l'étape (fail-open) ;
4. ``MemoryError`` devient un message exploitable + code 3, pas une trace de pile ;
5. CANARI : ``main`` appelle réellement le surveillant et rattrape bien ``MemoryError``.
"""
from __future__ import annotations

import ast
import pickle
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))
sys.path.insert(0, str(RACINE / "src"))

OUTIL = RACINE / "tools" / "labo_materialiser_safe.py"


def _module():
    """Charge l'outil comme module (il n'est pas dans un paquet importable)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("labo_materialiser_safe_test", OUTIL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _GouverneurFactice:
    """Gouverneur injectable : on pilote le niveau renvoyé et on compte les respirations."""

    VERT, ORANGE, ROUGE = "VERT", "ORANGE", "ROUGE"
    CONTINUER, RALENTIR, REDUIRE, PAUSER = "CONTINUER", "RALENTIR", "REDUIRE", "PAUSER"

    def __init__(self, action="CONTINUER", niveau="VERT", respire=True):
        self._action, self._niveau, self._respire = action, niveau, respire
        self.appels_decision = 0
        self.appels_attente = 0

    def decision(self, **_k):
        self.appels_decision += 1
        return {"action": self._action, "niveau": self._niveau, "facteur": 1.0,
                "raison": "raison factice", "etat": {}}

    def journal_memoire(self, prefixe="memoire", **_k):
        return f"[{prefixe}] {self._niveau} | factice"

    def attendre_que_ca_respire(self, **_k):
        self.appels_attente += 1
        return {"niveau": self.VERT if self._respire else self.ROUGE, "tours": 1,
                "attendu_s": 1.0, "a_respire": self._respire}


class _GouverneurCasse:
    """Tout explose : l'étape doit continuer sans broncher."""

    PAUSER = "PAUSER"

    def decision(self, **_k):
        raise RuntimeError("gouverneur casse")

    def journal_memoire(self, *_a, **_k):
        raise RuntimeError("gouverneur casse")


class _Horloge:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def avancer(self, d):
        self.t += float(d)


# ------------------------------------------------------------------ contrôle à intervalle

def test_le_controle_ne_lit_pas_la_ram_a_chaque_message():
    """Point de performance : cette étape émet des milliers de lignes. Lire la RAM à chacune la
    ralentirait pour rien."""
    mod = _module()
    gouv, horloge, dits = _GouverneurFactice(), _Horloge(), []
    verifier = mod.surveillant_memoire(dits.append, gouverneur=gouv, horloge=horloge,
                                       intervalle_s=20.0)
    for _ in range(500):
        verifier()
    assert gouv.appels_decision == 0            # aucun contrôle : l'intervalle n'est pas écoulé
    horloge.avancer(21.0)
    verifier()
    assert gouv.appels_decision == 1            # un seul, une fois l'intervalle passé


def test_forcer_contourne_l_intervalle():
    mod = _module()
    gouv, dits = _GouverneurFactice(), []
    verifier = mod.surveillant_memoire(dits.append, gouverneur=gouv, horloge=_Horloge(),
                                       intervalle_s=999.0)
    verifier(forcer=True)
    assert gouv.appels_decision == 1
    assert any("factice" in d for d in dits)    # l'état mémoire est bien journalisé


# ------------------------------------------------------------------ comportement en ROUGE

def test_en_rouge_on_souffle_puis_on_CONTINUE():
    mod = _module()
    gouv, dits = _GouverneurFactice(action="PAUSER", niveau="ROUGE", respire=True), []
    verifier = mod.surveillant_memoire(dits.append, gouverneur=gouv, horloge=_Horloge(),
                                       dormir=lambda _s: None)
    d = verifier(forcer=True)
    assert gouv.appels_attente == 1
    assert d["action"] == "PAUSER"
    assert any("ca respire, on continue" in m for m in dits)


def test_si_ca_ne_respire_pas_on_continue_quand_meme_en_mode_degrade():
    """Non négociable : on ne bloque JAMAIS le pipeline indéfiniment pour de la RAM."""
    mod = _module()
    gouv, dits = _GouverneurFactice(action="PAUSER", niveau="ROUGE", respire=False), []
    verifier = mod.surveillant_memoire(dits.append, gouverneur=gouv, horloge=_Horloge(),
                                       dormir=lambda _s: None)
    verifier(forcer=True)
    assert any("on continue en mode degrade" in m for m in dits)


def test_en_vert_on_ne_souffle_pas():
    mod = _module()
    gouv, dits = _GouverneurFactice(action="CONTINUER", niveau="VERT"), []
    verifier = mod.surveillant_memoire(dits.append, gouverneur=gouv, horloge=_Horloge())
    verifier(forcer=True)
    assert gouv.appels_attente == 0


# ------------------------------------------------------------------ fail-open

def test_un_gouverneur_casse_ne_casse_pas_l_etape():
    mod = _module()
    dits = []
    verifier = mod.surveillant_memoire(dits.append, gouverneur=_GouverneurCasse(),
                                       horloge=_Horloge())
    assert verifier(forcer=True) is None                       # pas d'exception propagée
    assert any("surveillance memoire indisponible" in m for m in dits)


def test_sans_gouverneur_du_tout_l_etape_tourne():
    mod = _module()
    verifier = mod.surveillant_memoire(lambda _m: None, gouverneur=None, horloge=_Horloge())
    assert verifier(forcer=True) is None


# ------------------------------------------------------------------ MemoryError -> message exploitable

class _FauxLabModule:
    """Remplace le vrai labo : on choisit ce que fait la matérialisation."""

    def __init__(self, resultat=None, lever=None):
        self._resultat, self._lever = resultat, lever

    def materialize_safe_workspace(self, _recovery, _workspace, progress=None):
        if progress is not None:
            progress("message de progression")
        if self._lever is not None:
            raise self._lever
        return self._resultat


def test_memory_error_devient_un_message_exploitable_et_le_code_3(monkeypatch, tmp_path, capsys):
    mod = _module()
    monkeypatch.setitem(sys.modules, "hl_observer.backtesting.copy_vault_local_lab",
                        _FauxLabModule(lever=MemoryError("plus de RAM")))
    code = mod.main([str(tmp_path / "rec"), str(tmp_path / "ws"), str(tmp_path / "res.pkl")])
    assert code == mod.CODE_SORTIE_MEMOIRE == 3
    err = capsys.readouterr().err
    assert "MEMOIRE INSUFFISANTE" in err
    assert "Reduisez l'ampleur" in err
    assert "ce n'est pas un bug du code" in err          # l'appelant sait quoi faire
    assert not (tmp_path / "res.pkl").exists()           # rien d'écrit à moitié


def test_le_chemin_heureux_ecrit_le_resultat_atomiquement(monkeypatch, tmp_path):
    mod = _module()
    attendu = {"ok": True, "n": 42}
    monkeypatch.setitem(sys.modules, "hl_observer.backtesting.copy_vault_local_lab",
                        _FauxLabModule(resultat=attendu))
    sortie = tmp_path / "res.pkl"
    code = mod.main([str(tmp_path / "rec"), str(tmp_path / "ws"), str(sortie)])
    assert code == 0
    assert pickle.loads(sortie.read_bytes()) == attendu
    assert not sortie.with_name(sortie.name + ".tmp").exists()   # pas de .tmp laissé derrière


def test_mauvais_usage_renvoie_2(capsys):
    mod = _module()
    assert mod.main(["un seul argument"]) == 2
    assert "usage" in capsys.readouterr().err


# ------------------------------------------------------------------ CANARI de câblage

def test_CANARI_main_appelle_vraiment_le_surveillant_et_rattrape_MemoryError():
    """MENTION ≠ PORTE. On exige l'APPEL dans l'AST, pas un simple import décoratif : c'est la seule
    façon d'empêcher que ce garde redevienne mort au prochain remaniement."""
    arbre = ast.parse(OUTIL.read_text(encoding="utf-8"))
    main = next(n for n in arbre.body if isinstance(n, ast.FunctionDef) and n.name == "main")

    appels = {getattr(n.func, "id", getattr(n.func, "attr", "")) for n in ast.walk(main)
              if isinstance(n, ast.Call)}
    assert "surveillant_memoire" in appels, "main doit APPELER surveillant_memoire"

    handlers = [h for n in ast.walk(main) if isinstance(n, ast.Try) for h in n.handlers]
    attrapes = {getattr(h.type, "id", None) for h in handlers}
    assert "MemoryError" in attrapes, "main doit rattraper MemoryError (jamais de trace de pile brute)"


def test_CANARI_le_surveillant_consulte_le_gouverneur_officiel():
    """Le surveillant doit passer par `hl_observer.ops.budget_ram` (source unique), pas par une
    lecture psutil maison qui divergerait des seuils."""
    src = OUTIL.read_text(encoding="utf-8")
    assert "from hl_observer.ops import budget_ram" in src
    assert "psutil" not in src, "pas de lecture memoire maison : tout passe par le gouverneur"
    arbre = ast.parse(src)
    surv = next(n for n in arbre.body if isinstance(n, ast.FunctionDef)
                and n.name == "surveillant_memoire")
    attrs = {n.attr for n in ast.walk(surv) if isinstance(n, ast.Attribute)}
    for attendu in ("decision", "journal_memoire", "attendre_que_ca_respire"):
        assert attendu in attrs, f"le surveillant doit utiliser gouverneur.{attendu}()"
