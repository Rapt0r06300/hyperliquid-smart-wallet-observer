"""[AUD-033..040 RECONSTRUIT] Reproductibilite / provenance / supply chain de release. Intitules
d'origine perdus (MASTER V3) : reconstruction a confirmer. Tests reels sur la logique livree."""
from hl_observer.research import release_reproductibilite as rr


def test_033_reproductible_bit_a_bit():
    a = {"pkg/__init__.py": b"x=1\n", "pkg/core.py": b"def f(): return 2\n"}
    b = {"pkg/core.py": b"def f(): return 2\n", "pkg/__init__.py": b"x=1\n"}  # ordre different
    assert rr.reproductible(a, b)["reproductible"] is True
    c = dict(a); c["pkg/core.py"] = b"def f(): return 3\n"
    assert rr.reproductible(a, c)["reproductible"] is False


def test_034_attestation_provenance():
    att = rr.attestation("HASHART", "SHA123", "ci-runner-1")
    assert rr.verifier_attestation(att, "HASHART", "SHA123") is True
    assert rr.verifier_attestation(att, "HASHART", "AUTRE_SHA") is False


def test_035_integrite_lockfile():
    lock = {"numpy": "h1", "pandas": "h2"}
    assert rr.verifier_lock(lock, {"numpy": "h1", "pandas": "h2"})["ok"] is True
    bad = rr.verifier_lock(lock, {"numpy": "h1", "pandas": "HACKED"})
    assert bad["ok"] is False and bad["ecarts"][0]["paquet"] == "pandas"


def test_036_deps_non_epinglees():
    reqs = ["numpy==1.26.4", "pandas>=2.0", "requests", "scipy~=1.11", "pytest==8.0.0 ; python_version>'3.8'"]
    flous = rr.deps_non_epinglees(reqs)
    assert "numpy==1.26.4" not in flous
    assert "pytest==8.0.0 ; python_version>'3.8'" not in flous
    assert set(flous) == {"pandas>=2.0", "requests", "scipy~=1.11"}


def test_037_deps_yankees_interdites():
    interdits = rr.deps_interdites(["foo==1.0.0", "bar==2.3.1"], {"bar": ["2.3.1", "2.3.2"]})
    assert interdits == [{"paquet": "bar", "version": "2.3.1"}]


def test_038_empreinte_env():
    e1 = rr.empreinte_env("3.11.5", "linux", "x86_64")
    e2 = rr.empreinte_env("3.11.5", "linux", "x86_64")
    e3 = rr.empreinte_env("3.12.0", "linux", "x86_64")
    assert e1 == e2 and rr.env_compatible(e1, e2) and not rr.env_compatible(e1, e3)


def test_039_diff_artefact():
    ref = {"a.py": b"1", "b.py": b"2"}
    cur = {"a.py": b"1", "b.py": b"CHANGED", "c.py": b"3"}
    d = rr.diff_artefact(ref, cur)
    assert d["ajoutes"] == ["c.py"] and d["modifies"] == ["b.py"] and d["identique"] is False
    assert rr.diff_artefact(ref, dict(ref))["identique"] is True


def test_040_chaine_garde_anti_swap():
    assert rr.chaine_garde("S", "S", "S")["ok"] is True
    assert rr.chaine_garde("S", "S", "AUTRE")["ok"] is False
