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


def test_fill_non_identifiable_refuse():
    reg = RegistreFills()
    assert reg.consommer(wallet="0xABC")["nouveau"] is False   # aucun discriminant -> jamais consommé
