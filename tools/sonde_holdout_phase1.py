"""HISTORICAL_HOLDOUT_V1 — PHASE 1 : sonde MÉTADONNÉES S3, STRICTEMENT BORNÉE (rectif Flo 25/07).

Objectif : savoir GRATUITEMENT ce que l'archive Hyperliquid contient, SANS rien télécharger, SANS
identifiants, SANS installer le moindre outil. On interroge l'API REST S3 en **ANONYME** (`list-type=2`)
avec la seule bibliothèque standard `urllib` — donc **aucune CLI aws**, **aucun compte AWS**, **aucun
moyen de paiement**.

Garde-fous durs (décision de Flo) :
  • **≤ 30 requêtes S3 au total** (compteur strict, refus au-delà) ;
  • **AUCUN téléchargement d'objet** — uniquement des LISTES de métadonnées (clés, tailles, préfixes) ;
  • **AUCUN compte / moyen de paiement AWS** ;
  • si un bucket n'autorise pas la liste anonyme (403) → il est **requester-pays** → on s'arrête proprement,
    Flo décide (« rien de payant »). Aucune approximation : on rapporte ce que S3 renvoie, pas une supposition.

Sortie : dates disponibles, préfixes (L2 / node_fills), tailles d'objets échantillon, et CHEVAUCHEMENT
des dates node_fills ↔ L2. Rapport dans runtime/rapports/holdout/phase1_sonde.txt.
"""
from __future__ import annotations

import re
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
SORTIE = RACINE / "runtime" / "rapports" / "holdout"
REQUETE_MAX = 30
NS = "{http://s3.amazonaws.com/doc/2006-03-01/}"
BUCKET_NOEUD = "hl-mainnet-node-data"
BUCKET_MARCHE = "hyperliquid-archive"

_etat = {"n": 0, "region": None}
_journal: list[str] = []


def _log(msg: str = "") -> None:
    print(msg, flush=True)
    _journal.append(msg)


def _url(bucket: str, prefix: str, delimiter: str, max_keys: int, region: str | None) -> str:
    host = "%s.s3.%s.amazonaws.com" % (bucket, region) if region else "%s.s3.amazonaws.com" % bucket
    q = "list-type=2&max-keys=%d" % max_keys
    if delimiter:
        q += "&delimiter=" + urllib.parse.quote(delimiter)
    if prefix:
        q += "&prefix=" + urllib.parse.quote(prefix)
    return "https://%s/?%s" % (host, q)


def s3_list(bucket: str, *, prefix: str = "", delimiter: str = "/", max_keys: int = 400):
    """Liste ANONYME (list-type=2). Rend (ok, prefixes[list], contents[(cle,octets)], err). Compte la requête ;
    refuse au-delà de REQUETE_MAX. Suit UNE fois la redirection de région (mise en cache)."""
    if _etat["n"] >= REQUETE_MAX:
        return False, [], [], "PLAFOND_30_REQUETES_ATTEINT"
    _etat["n"] += 1
    url = _url(bucket, prefix, delimiter, max_keys, _etat["region"])
    req = urllib.request.Request(url, headers={"User-Agent": "holdout-phase1-metadata"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = r.read()
    except urllib.error.HTTPError as e:
        body = e.read()
        reg = e.headers.get("x-amz-bucket-region")
        if e.code in (301, 307) and _etat["region"] is None:
            if not reg:
                try:
                    reg = ET.fromstring(body).findtext(".//Endpoint")
                    m = re.search(r"s3[.-]([a-z0-9-]+)\.amazonaws", reg or "")
                    reg = m.group(1) if m else None
                except ET.ParseError:
                    reg = None
            if reg:
                _etat["region"] = reg
                return s3_list(bucket, prefix=prefix, delimiter=delimiter, max_keys=max_keys)
        return False, [], [], "HTTP %d %s" % (e.code, body[:100].decode("utf-8", "replace").replace("\n", " "))
    except Exception as exc:  # noqa: BLE001
        return False, [], [], str(exc)[:120]
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        return False, [], [], "XML illisible: %s" % str(exc)[:80]
    prefixes = [cp.findtext(NS + "Prefix") or "" for cp in root.findall(NS + "CommonPrefixes")]
    contents = [((c.findtext(NS + "Key") or ""), int(c.findtext(NS + "Size") or 0))
                for c in root.findall(NS + "Contents")]
    return True, prefixes, contents, ""


_DATE = re.compile(r"(20\d{2})[-/]?(\d{2})[-/]?(\d{2})")


def _dates(chaines: list[str]) -> list[str]:
    out = set()
    for s in chaines:
        m = _DATE.search(s or "")
        if m:
            out.add("".join(m.groups()))
    return sorted(out)


def main() -> int:
    SORTIE.mkdir(parents=True, exist_ok=True)
    _log("=" * 90)
    _log("  HISTORICAL_HOLDOUT_V1 — PHASE 1 : sonde MÉTADONNÉES S3 (urllib, ANONYME, ≤30 req, 0 download)")
    _log("=" * 90)
    _log("  (aucune CLI aws, aucun compte, aucun paiement — bibliothèque standard Python uniquement)\n")

    _log("  [A] Le bucket est-il listable ANONYMEMENT (= gratuit) ?")
    ok_n, pref_n, _, e_n = s3_list(BUCKET_NOEUD, prefix="", delimiter="/")
    if ok_n:
        _log("    ✅ node-data LISTABLE (region=%s) : %s" % (_etat["region"] or "us-east-1",
             ", ".join(p.rstrip("/") for p in pref_n[:14]) or "(racine vide)"))
    else:
        _log("    🔒 node-data : %s" % e_n)
    ok_m, pref_m, _, e_m = s3_list(BUCKET_MARCHE, prefix="", delimiter="/")
    if ok_m:
        _log("    ✅ market LISTABLE : %s" % (", ".join(p.rstrip("/") for p in pref_m[:14]) or "(racine vide)"))
    else:
        _log("    🔒 market : %s" % e_m)

    if not (ok_n or ok_m):
        _log("\n  🔒 AUCUNE liste anonyme possible → l'archive exige le requester-pays (PAYANT).")
        _log("     Décision de Flo = « rien de payant » → on S'ARRÊTE ici. 0 identifiant, 0 coût, 0 install.")
        _log("     Porte fermée par CHOIX, enregistrée comme telle (pas une fatalité technique).")
        (SORTIE / "phase1_sonde.txt").write_text("\n".join(_journal), encoding="utf-8")
        return 1

    dates_fills: list[str] = []
    dates_l2: list[str] = []

    if ok_n:
        _log("\n  [B] node_fills / node_fills_by_block : préfixes + dates")
        for jeu in ("node_fills/", "node_fills_by_block/"):
            ok, pref, cont, err = s3_list(BUCKET_NOEUD, prefix=jeu, delimiter="/")
            if ok:
                d = _dates(pref + [k for k, _ in cont])
                if d:
                    dates_fills = sorted(set(dates_fills) | set(d))
                    _log("    %-22s %d dates · %s .. %s" % (jeu, len(d), d[0], d[-1]))
                else:
                    apercu = [p.rstrip("/").split("/")[-1] for p in pref[:6]] or [k for k, _ in cont[:6]]
                    _log("    %-22s contenu : %s" % (jeu, ", ".join(apercu) or "(vide)"))
            else:
                _log("    %-22s 🔒 %s" % (jeu, err))

    if ok_m:
        _log("\n  [C] market_data (L2) : dates")
        ok, pref, cont, err = s3_list(BUCKET_MARCHE, prefix="market_data/", delimiter="/")
        if ok:
            dates_l2 = _dates(pref + [k for k, _ in cont])
            _log("    market_data/ : %d dates · %s .. %s" % (len(dates_l2), dates_l2[0], dates_l2[-1])
                 if dates_l2 else "    market_data/ contenu : %s" % ", ".join(p.rstrip("/") for p in pref[:6]))
        else:
            _log("    market_data/ 🔒 %s" % err)

    overlap = sorted(set(dates_fills) & set(dates_l2))
    _log("\n  [D] CHEVAUCHEMENT node_fills ↔ L2")
    _log("    dates node_fills=%d · dates L2=%d · communes=%d" % (len(dates_fills), len(dates_l2), len(overlap)))
    if overlap:
        _log("    plage commune : %s .. %s" % (overlap[0], overlap[-1]))
        d = overlap[len(overlap) // 2]
        okL, prefL, contL, errL = s3_list(BUCKET_MARCHE, prefix="market_data/%s/12/l2Book/" % d, delimiter="/")
        if okL and contL:
            _log("    échantillon L2 %s/12h : %s" % (d, ", ".join("%s=%.2fMo" % (k.split("/")[-1], o / 1e6)
                                                                    for k, o in contL[:8])))
        elif okL:
            _log("    échantillon L2 %s/12h : préfixes %s" % (d, ", ".join(p.rstrip("/").split("/")[-1]
                                                                            for p in prefL[:8]) or "(vide)"))
        else:
            _log("    échantillon L2 %s : 🔒 %s" % (d, errL))

    _log("\n" + "-" * 90)
    _log("  Requêtes S3 : %d/%d  ·  téléchargement : 0 octet  ·  coût : 0 €  ·  install : 0" % (_etat["n"], REQUETE_MAX))
    _log("  Prochaine étape = Phase 2 : figer 2 fenêtres disjointes selon CES dates + pré-registration.")
    _log("  AUCUN téléchargement supplémentaire sans ton accord explicite.")
    (SORTIE / "phase1_sonde.txt").write_text("\n".join(_journal), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
