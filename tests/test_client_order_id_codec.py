"""[pépite 213] deterministic client-order-ID codec : encode/décode module+episode+leg+generation."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.exec_reconciliation.client_order_id_codec import encoder, decoder, roundtrip_stable   # noqa: E402


def test_encode_decode():
    cid = encoder(module="arb", episode="ep7", leg="A", generation=2)
    d = decoder(cid)
    assert d["ok"] is True and d["module"] == "ARB" and d["episode"] == "ep7" and d["leg"] == "A"


def test_roundtrip_stable():
    assert roundtrip_stable(module="copy", episode="e1", leg="B", generation=0) is True


def test_format_invalide():
    assert decoder("pas-un-id-valide-trop-long-x")["ok"] is False
