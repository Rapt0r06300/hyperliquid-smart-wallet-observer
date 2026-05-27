from hl_observer.explorer.explorer_parser import parse_explorer_payload, parse_explorer_records


def test_explorer_rejects_truncated_addresses():
    transactions, truncated = parse_explorer_records(
        [{"tx_hash": "0x" + "1" * 64, "address": "0x1234...abcd"}]
    )

    assert truncated == 1
    assert transactions[0].wallet_address is None
    assert transactions[0].validation_status.value == "TRUNCATED_ADDRESS_REJECTED"


def test_explorer_event_without_full_address_does_not_create_candidate():
    transactions, _ = parse_explorer_records([{"tx_hash": "0x" + "2" * 64, "action": "fill"}])

    assert transactions[0].wallet_address is None
    assert transactions[0].validation_status.value == "EVENT_WITHOUT_ADDRESS"


def test_explorer_accepts_full_address_only():
    address = "0x" + "a" * 40
    transactions, truncated = parse_explorer_records([{"tx_hash": "0x" + "3" * 64, "address": address}])

    assert truncated == 0
    assert transactions[0].wallet_address == address
    assert transactions[0].validation_status.value == "FULL_ADDRESS_OK"


def test_explorer_rpc_stream_order_payload_is_parsed():
    address = "0x" + "b" * 40
    payload = [
        {
            "hash": "0x" + "4" * 64,
            "user": address,
            "time": 1710000000000,
            "action": {
                "type": "order",
                "orders": [{"a": 1, "b": True, "p": "123.45", "s": "2.5"}],
            },
        }
    ]

    transactions, truncated = parse_explorer_payload(payload, source_url="wss://rpc.hyperliquid.xyz/ws")

    assert truncated == 0
    assert transactions[0].wallet_address == address
    assert transactions[0].action_type == "order"
    assert transactions[0].coin == "ASSET_1"
    assert transactions[0].side == "buy"
    assert transactions[0].size == 2.5
    assert transactions[0].price == 123.45


def test_explorer_block_details_payload_is_parsed():
    address = "0x" + "c" * 40
    payload = {
        "blockDetails": {
            "txs": [
                {
                    "hash": "0x" + "5" * 64,
                    "user": address,
                    "action": {"type": "cancel", "cancels": [{"asset": 7}]},
                }
            ]
        }
    }

    transactions, truncated = parse_explorer_payload(payload, source_url="https://rpc.hyperliquid.xyz/explorer")

    assert truncated == 0
    assert transactions[0].wallet_address == address
    assert transactions[0].action_type == "cancel"
    assert transactions[0].coin == "ASSET_7"
