from hl_observer.collection.proxy_pool import ProxyEndpoint


def test_proxy_endpoint_plain_url_is_returned_unchanged() -> None:
    endpoint = ProxyEndpoint(
        endpoint_id="egress-direct",
        url="https://example.invalid:8080",
    )

    assert endpoint.redacted_url == "https://example.invalid:8080"
