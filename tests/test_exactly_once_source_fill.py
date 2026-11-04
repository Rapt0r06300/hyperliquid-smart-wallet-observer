"""[COPY-VAULT #60] exactly-once source fill : identité unique wallet+tid/oid, un fill consommé une seule fois."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.copy_vault.exactly_once_source_fill import identite, RegistreFills   # noqa: E402


def test_consommation_idempotente():
    reg = RegistreFills()
    a = reg.consommer(wallet="0xABC", tid=111, oid=999)
    b = reg.consommer(wallet="0xabc", tid=111, oid=999)   # même identité (wallet insensible a la casse)
    assert a["nouveau"] is True and b["nouveau"] is False and b["raison"] == "DEJA_CONSOMME"


def test_identite_stable():
    assert identite(wallet="0xABC", tid=1, oid=2) == identite(wallet="0xabc", tid=1, oid=2)


def test_identite_preserves_discriminant_type_and_delimiters():
    assert identite(wallet="0xabc", tid=1) != identite(wallet="0xabc", oid=1)
    assert identite(wallet="0xabc", tid="a|b") != identite(wallet="0xabc", tid="a", oid="b")


def test_fill_non_identifiable_refuse():
    reg = RegistreFills()
    assert reg.consommer(wallet="0xABC")["nouveau"] is False   # aucun discriminant -> jamais consommé


def test_registre_durable_survit_au_redemarrage(tmp_path):
    path = tmp_path / "fills.sqlite"
    with RegistreFills(path) as first:
        accepted = first.consommer(wallet="0xabc", tid=7)
    with RegistreFills(path) as restarted:
        duplicate = restarted.consommer(wallet="0xABC", tid=7)

    assert accepted["nouveau"] is True
    assert duplicate["nouveau"] is False
    assert duplicate["raison"] == "DEJA_CONSOMME"


def test_registre_durable_refuse_les_identites_inconnues_si_le_stockage_est_indisponible(tmp_path):
    with RegistreFills(tmp_path) as registry:
        result = registry.consommer(wallet="0xabc", tid=8)

    assert result["nouveau"] is False
    assert result["raison"] == "REGISTRE_DURABILITE_INDISPONIBLE"
