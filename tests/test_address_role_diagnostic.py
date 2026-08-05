from hl_observer.signals.address_role_diagnostic import (
    ROLE_AGENT, ROLE_INCONNU, ROLE_MASTER, ROLE_SUBACCOUNT, CarteAdresses, diagnostic_adresse)

CARTE = CarteAdresses(master="0xMASTER", agents=frozenset({"0xAGENT"}),
                      subaccounts=frozenset({"0xSUB1"}))


def test_master_attendu_master_ok():
    d = diagnostic_adresse("0xmaster", CARTE, role_attendu=ROLE_MASTER)
    assert d["role"] == ROLE_MASTER and d["ok"] is True


def test_agent_observe_quand_master_attendu_mismatch():
    d = diagnostic_adresse("0xAGENT", CARTE, role_attendu=ROLE_MASTER)
    assert d["role"] == ROLE_AGENT and d["ok"] is False and "MISMATCH" in d["raison"]


def test_subaccount_classe():
    assert diagnostic_adresse("0xsub1", CARTE, role_attendu=ROLE_SUBACCOUNT)["ok"] is True


def test_adresse_inconnue():
    d = diagnostic_adresse("0xDEADBEEF", CARTE)
    assert d["role"] == ROLE_INCONNU and d["ok"] is False and "INCONNUE" in d["raison"]


def test_adresse_vide_inconnue():
    assert diagnostic_adresse("", CARTE)["role"] == ROLE_INCONNU
