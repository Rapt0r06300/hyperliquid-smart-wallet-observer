from hl_observer.ops.supply_chain import generer_sbom, verifier_hashes_dependances


def test_sbom_liste_tous_les_composants():
    s = generer_sbom([{"nom": "numpy", "version": "1.26.0"}, {"nom": "pandas", "version": "2.1.0"}])
    assert s["n_composants"] == 2
    assert [c["name"] for c in s["composants"]] == ["numpy", "pandas"]
    assert all(c["hash"] for c in s["composants"])


def test_hashes_dependances_signale_les_non_pinnees():
    reqs = ["numpy==1.26.0 --hash=sha256:abcd", "pandas==2.1.0", "# commentaire", ""]
    r = verifier_hashes_dependances(reqs)
    assert r["toutes_pinnees"] is False and r["sans_hash"] == ["pandas"] and "numpy" in r["pinnees"]
