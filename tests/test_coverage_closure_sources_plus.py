from __future__ import annotations

import json

import pytest

from hl_observer.research import sources_plus as sp


@pytest.mark.parametrize(
    "name,marker",
    [
        ("openreview", "openreview.net"),
        ("openalex", "openalex.org"),
        ("openalex_cite", "filter=cites"),
        ("arxiv", "arxiv.org"),
        ("paperswithcode", "paperswithcode.com"),
        ("semanticscholar", "semanticscholar.org"),
        ("repec", "type:posted-content"),
        ("dblp", "dblp.org"),
        ("zenodo", "zenodo.org"),
        ("softwareheritage", "softwareheritage.org"),
        ("crossref", "crossref.org"),
        ("pypi", "pypi.org"),
        ("cratesio", "crates.io"),
        ("npm", "npmjs.org"),
        ("hackernews", "algolia.com"),
        ("stackexchange", "stackexchange.com"),
        ("wikipedia", "wikipedia.org"),
    ],
)
def test_all_supported_urls_are_explicit_and_encoded(name: str, marker: str) -> None:
    value = sp.url(name, "lead lag + costs")
    assert value is not None
    assert marker in value
    assert "lead%20lag%20%2B%20costs" in value or name == "openalex_cite"


def test_unknown_url_is_refused() -> None:
    assert sp.url("unknown", "x") is None


def test_src_and_report_are_complete() -> None:
    first = sp.CATALOGUE[0].as_dict()
    assert first["nom"] == "openreview"
    assert first["fiabilite"] > 1
    report = sp.rapport()
    assert report["n_sources"] == len(sp.CATALOGUE)
    assert len(report["sources"]) == len(sp.CATALOGUE)
    assert "OpenReview" in report["la_meilleure"]
    assert "google / bing" in report["inaccessibles"]


def test_parser_empty_invalid_and_arxiv() -> None:
    assert sp.parser("openalex", "") == []
    assert sp.parser("openalex", "not-json") == []
    xml = """<feed><entry><title>  Lead Lag  </title><summary> alpha   beta </summary><id>id-1</id></entry><entry><title>x</title></entry></feed>"""
    assert sp.parser("arxiv", xml) == [("Lead Lag", "alpha beta", "id-1", 0)]


def test_parser_openalex_rebuilds_inverted_abstract_and_skips_non_mapping() -> None:
    payload = {
        "results": [
            "bad",
            {
                "display_name": "Paper",
                "abstract_inverted_index": {"world": [1], "hello": [0], "ignored": "x"},
                "id": "W1",
                "cited_by_count": 7,
            },
        ]
    }
    assert sp.parser("openalex", json.dumps(payload)) == [("Paper", "hello world", "W1", 7)]
    assert sp.parser("openalex_cite", json.dumps(payload))[0][1] == "hello world"


def test_parser_openreview_handles_wrapped_values_and_abstract_fallback() -> None:
    payload = {
        "notes": [
            "bad",
            {
                "forum": "f1",
                "content": {
                    "title": {"value": "Review title"},
                    "weaknesses": {"value": "costs ignored"},
                    "rating": "5",
                },
            },
            {
                "id": "f2",
                "content": {"abstract": "A" * 100},
            },
        ]
    }
    rows = sp.parser("openreview", json.dumps(payload))
    assert rows[0][0] == "Review title"
    assert "costs ignored" in rows[0][1]
    assert rows[0][2].endswith("f1")
    assert len(rows[1][0]) == 90


def test_parser_paperswithcode_and_semantic_scholar() -> None:
    pwc = {"results": [{"paper": {"title": "P", "abstract": "A", "url_abs": "/p"}, "repository": {"url": "https://code", "stars": 3}}, {"title": "Direct"}]}
    rows = sp.parser("paperswithcode", json.dumps(pwc))
    assert rows[0] == ("P", "A  [CODE: https://code]", "/p", 3)
    assert "CODE: aucun" in rows[1][1]

    semantic = {"data": ["bad", {"title": "S", "abstract": "Abs", "paperId": "id", "citationCount": 4}]}
    assert sp.parser("semanticscholar", json.dumps(semantic)) == [("S", "Abs", "https://www.semanticscholar.org/paper/id", 4)]


def test_parser_crossref_repec_dblp_zenodo_and_softwareheritage() -> None:
    crossref = {"message": {"items": ["bad", {"title": ["C"], "abstract": "<p>Body</p>", "URL": "u", "is-referenced-by-count": 2}]}}
    assert sp.parser("crossref", json.dumps(crossref))[0][0] == "C"
    assert "Body" in sp.parser("repec", json.dumps(crossref))[0][1]

    dblp = {"result": {"hits": {"hit": [{"info": {"title": "D", "venue": "V", "ee": "E"}}]}}}
    assert sp.parser("dblp", json.dumps(dblp)) == [("D", "V", "E", 0)]

    zenodo = {"hits": {"hits": [{"metadata": {"title": "Z", "description": "Desc"}, "links": {"self_html": "L"}}]}}
    assert sp.parser("zenodo", json.dumps(zenodo)) == [("Z", "Desc", "L", 0)]

    swh = [{"url": "https://origin"}, {"url": ""}, None]
    assert sp.parser("softwareheritage", json.dumps(swh)) == [("https://origin", "origine archivée (Software Heritage)", "https://origin", 0)]


def test_parser_package_forum_and_wikipedia_sources() -> None:
    pypi = {"info": {"name": "pkg", "summary": "sum", "description": "desc"}}
    assert sp.parser("pypi", json.dumps(pypi))[0][2] == "https://pypi.org/project/pkg"
    assert sp.parser("pypi", json.dumps({"info": {}})) == []

    crates = {"crates": ["bad", {"name": "crate", "description": "d", "downloads": 9}]}
    assert sp.parser("cratesio", json.dumps(crates)) == [("crate", "d", "https://crates.io/crates/crate", 9)]

    npm = {"objects": [{"package": {"name": "n", "description": "d", "links": {"npm": "url"}}}]}
    assert sp.parser("npm", json.dumps(npm)) == [("n", "d", "url", 0)]

    hn = {"hits": ["bad", {"title": "H", "story_text": "story", "comment_text": "comment", "objectID": "1", "points": 6}]}
    assert sp.parser("hackernews", json.dumps(hn))[0] == ("H", "story comment", "https://news.ycombinator.com/item?id=1", 6)

    stack = {"items": ["bad", {"title": "Q", "body": "<b>body</b>", "link": "q", "score": 5}]}
    assert sp.parser("stackexchange", json.dumps(stack))[0] == ("Q", " body ", "q", 5)

    wiki = {"query": {"search": ["bad", {"title": "Lead lag", "snippet": "<span>text</span>"}]}}
    row = sp.parser("wikipedia", json.dumps(wiki))[0]
    assert row[0] == "Lead lag"
    assert row[2].endswith("Lead_lag")


def test_unknown_parser_returns_empty_after_valid_json() -> None:
    assert sp.parser("unknown", json.dumps({"anything": True})) == []
