"""HISTORICAL_HOLDOUT_V1 — PHASE 1 : sonde MÉTADONNÉES S3, STRICTEMENT BORNÉE (rectif Flo 25/07).

Objectif : savoir GRATUITEMENT ce que l'archive Hyperliquid contient, SANS rien télécharger et SANS
identifiants. On ne fait que des `aws s3 ls --no-sign-request` (aucune signature, aucune facturation).

Garde-fous durs (décision de Flo) :
  • **≤ 30 requêtes S3 au total** (compteur strict, refus au-delà) ;
  • **AUCUN téléchargement** (seulement des `ls`) ;
  • **AUCUN compte / moyen de paiement AWS** installé ou configuré ;
  • si `aws` est absent → on s'arrête et on le dit (on n'installe RIEN sans accord) ;
  • si le bucket n'est pas public (`--no-sign-request` refusé) → requester-pays → on s'arrête proprement.

Sortie : dates disponibles, préfixes (L2 / node_fills), tailles d'objets échantillon, et CHEVAUCHEMENT
des dates node_fills ↔ L2. Rapport écrit dans runtime/rapports/holdout/phase1_sonde.txt. Aucune approximation :
on rapporte ce que S3 renvoie, pas ce qu'on suppose.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
SORTIE = RACINE / "runtime" / "rapports" / "holdout"
REQUETE_MAX = 30
BUCKET_NOEUD = "s3://hl-mainnet-node-data/"
BUCKET_MARCHE = "s3://hyperliquid-archive/"

_compteur = {"n": 0}
_journal: list[str] = []


def _log(msg: str = "") -> None:
    print(msg, flush=True)
    _journal.append(msg)


def _aws_dispo() -> bool:
    return shutil.which("aws") is not None


def _ls(uri: str) -> tuple[bool, list[str], str]:
    """`aws s3 ls --no-sign-request uri`. Compte la requête ; refuse au-delà de REQUETE_MAX. 0 téléchargement."""
    if _compteur["n"] >= REQUETE_MAX:
        return False, [], "PLAFOND_30_REQUETES_ATTEINT"
    _compteur["n"] += 1
    try:
        r = subprocess.run(["aws", "s3", "ls", "--no-sign-request", uri],
                           capture_output=True, text=True, timeout=40, check=False)
    except Exception as exc:  # noqa: BLE001
        return False, [], str(exc)[:120]
    if r.returncode != 0:
        det = (r.stderr or "").strip().splitlines()
        return False, [], (det[-1][:130] if det else "code %d" % r.returncode)
    return True, (r.stdout or "").splitlines(), ""


_DATE = re.compile(r"(20\d{2})[-/]?(\d{2})[-/]?(\d{2})")


def _dates(lignes: list[str]) -> list[str]:
    """Extrait les jetons date (YYYYMMDD) des lignes `PRE .../` ou clés."""
    out = set()
    for l in lignes:
        m = _DATE.search(l)
        if m:
            out.add("".join(m.groups()))
    return sorted(out)


def _tailles(lignes: list[str]) -> list[tuple[str, int]]:
    """(clé, octets) des lignes objets (pas les PRE/)."""
    out = []
    for l in lignes:
        p = l.split()
        if len(p) >= 4 and p[2].isdigit():
            out.append((p[3], int(p[2])))
    return out


def main() -> int:
    SORTIE.mkdir(parents=True, exist_ok=True)
    _log("=" * 88)
    _log("  HISTORICAL_HOLDOUT_V1 — PHASE 1 : sonde MÉTADONNÉES S3 (≤30 req, GRATUIT, 0 download)")
    _log("=" * 88)
    if not _aws_dispo():
        _log("\n  ❌ La CLI `aws` n'est pas installée sur ce PC.")
        _log("     -> Installe-la (https://aws.amazon.com/cli/) OU dis-moi de le faire.")
        _log("     RIEN n'a été téléchargé, RIEN n'a été facturé, aucun compte AWS configuré.")
        (SORTIE / "phase1_sonde.txt").write_text("\n".join(_journal), encoding="utf-8")
        return 2

    _log("\n  [A] Racines de bucket (le bucket est-il PUBLIC en lecture ?)")
    noeud_ok, noeud_root, e1 = _ls(BUCKET_NOEUD)
    _log(("    ✅ node-data PUBLIC : " + ", ".join(x.strip() for x in noeud_root[:12])) if noeud_ok
         else f"    🔒 node-data FERMÉ ({e1})")
    marche_ok, marche_root, e2 = _ls(BUCKET_MARCHE)
    _log(("    ✅ market PUBLIC : " + ", ".join(x.strip() for x in marche_root[:12])) if marche_ok
         else f"    🔒 market FERMÉ ({e2})")

    if not (noeud_ok or marche_ok):
        _log("\n  🔒 AUCUN bucket public en lecture anonyme → l'archive exige le requester-pays (PAYANT).")
        _log("     Décision de Flo = 'rien de payant' → on S'ARRÊTE ici, sans identifiants, sans coût.")
        _log("     Ce n'est pas un mur technique : c'est un CHOIX, enregistré comme tel.")
        (SORTIE / "phase1_sonde.txt").write_text("\n".join(_journal), encoding="utf-8")
        return 1

    dates_fills: list[str] = []
    dates_l2: list[str] = []

    if noeud_ok:
        _log("\n  [B] node_fills / node_fills_by_block : préfixes + dates")
        for jeu in ("node_fills/", "node_fills_by_block/"):
            ok, li, err = _ls(BUCKET_NOEUD + jeu)
            if ok:
                d = _dates(li)
                if d:
                    dates_fills = sorted(set(dates_fills) | set(d))
                    _log(f"    {jeu:22s} {len(d)} dates · {d[0]}..{d[-1]}")
                else:
                    _log(f"    {jeu:22s} contenu : {', '.join(x.strip() for x in li[:6])}")
            else:
                _log(f"    {jeu:22s} 🔒 ({err})")

    if marche_ok:
        _log("\n  [C] market_data (L2) : dates")
        ok, li, err = _ls(BUCKET_MARCHE + "market_data/")
        if ok:
            dates_l2 = _dates(li)
            _log(f"    market_data/ : {len(dates_l2)} dates · {dates_l2[0]}..{dates_l2[-1]}" if dates_l2
                 else f"    market_data/ contenu : {', '.join(x.strip() for x in li[:6])}")
        else:
            _log(f"    market_data/ 🔒 ({err})")

    # [D] chevauchement + tailles échantillon (bornées par le plafond restant)
    overlap = sorted(set(dates_fills) & set(dates_l2))
    _log("\n  [D] CHEVAUCHEMENT node_fills ↔ L2")
    _log(f"    dates node_fills={len(dates_fills)} · dates L2={len(dates_l2)} · communes={len(overlap)}")
    if overlap:
        _log(f"    plage commune : {overlap[0]} .. {overlap[-1]}")
        d = overlap[len(overlap) // 2]                                # une date au milieu (échantillon)
        an, mo, jo = d[:4], d[4:6], d[6:8]
        for uri in (f"{BUCKET_MARCHE}market_data/{d}/12/l2Book/",
                    f"{BUCKET_MARCHE}market_data/{an}{mo}{jo}/12/l2Book/BTC.lz4"):
            ok, li, err = _ls(uri)
            if ok:
                t = _tailles(li)
                if t:
                    _log(f"    L2 {uri.split('market_data/')[1]} : " +
                         ", ".join(f"{k.split('/')[-1]}={o/1e6:.2f}Mo" for k, o in t[:6]))
                else:
                    _log(f"    L2 {uri.split('market_data/')[1]} : {', '.join(x.strip() for x in li[:6])}")
            else:
                _log(f"    L2 {uri} 🔒 ({err})")

    _log("\n" + "-" * 88)
    _log(f"  Requêtes S3 utilisées : {_compteur['n']}/{REQUETE_MAX}  ·  téléchargement : 0 octet  ·  coût : 0 €")
    _log("  Prochaine étape = Phase 2 (figer 2 fenêtres disjointes selon CES dates + pré-registration).")
    _log("  AUCUN téléchargement supplémentaire sans ton accord explicite.")
    (SORTIE / "phase1_sonde.txt").write_text("\n".join(_journal), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
