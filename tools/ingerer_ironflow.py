r"""Ingestion bornée, idempotente et reprenable des jeux Hyperliquid publics d'Ironflow (Hugging Face).

    tools\python\python.exe tools\ingerer_ironflow.py                       (les 4 jeux légers)
    tools\python\python.exe tools\ingerer_ironflow.py --jeux funding --max-mo 100

Source : https://ironflow.sh/datasets — Parquet construits depuis les nœuds d'Ironflow, l'archive et l'API
Hyperliquid. Licence CC BY 4.0 pour les fichiers ingérés ici (les trades récents sont CC BY-NC : non
ingérés par défaut). Les fichiers paraissent après la clôture du mois UTC.

CE QUE FAIT L'OUTIL
1. liste les fichiers via l'API Hugging Face (chemin, taille, SHA-256 LFS officiel) ;
2. télécharge seulement ce qui manque ou a changé, dans un fichier temporaire renommé une fois l'empreinte
   vérifiée (une coupure ne laisse jamais un fichier à moitié écrit sous le nom final) ;
3. valide chaque fichier (schéma attendu, lignes, bornes temporelles en UTC, valeurs impossibles,
   doublons de clé) SANS le charger d'un bloc : lecture par groupes de lignes ;
4. écrit `runtime/history/ironflow/MANIFESTE.json` : provenance, licence, empreinte, statut
   (`EXTERNAL_VALIDATED` ou `EXTERNAL_REJECTED` + motifs) et niveau de preuve autorisé.

CE QUE L'OUTIL NE FAIT PAS. Il ne rend rien SAFE et ne touche pas au coffre certifié : ces données sont des
observations de MARCHÉ reconstruites après coup, sans heure de réception par Alina. Elles servent à la
recherche descriptive et aux études d'événements, jamais à un replay d'exécution ni à une preuve.
Aucun ordre, aucune clé, aucune écriture hors de `runtime/history/ironflow/`.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import httpx

RACINE = Path(__file__).resolve().parents[1]
DOSSIER = Path("runtime") / "history" / "ironflow"
API = "https://huggingface.co/api/datasets/ironflow/{jeu}/tree/main"
FICHIER = "https://huggingface.co/datasets/ironflow/{jeu}/resolve/main/{chemin}"
ENTETES = {"User-Agent": "research-client"}

# Schéma minimal attendu par jeu, clé de déduplication et bornes de valeurs plausibles.
JEUX: dict[str, dict[str, Any]] = {
    "funding": {"depot": "hyperliquid-funding", "licence": "CC BY 4.0",
                "colonnes": ("timestamp", "market", "coin", "funding_rate"), "cle": ("timestamp", "market"),
                "bornes": {"funding_rate": (-0.05, 0.05)}},
    "open-interest": {"depot": "hyperliquid-open-interest", "licence": "CC BY 4.0",
                      "colonnes": ("timestamp", "market", "mark_price", "oracle_price", "open_interest"),
                      "cle": ("timestamp", "market"),
                      "bornes": {"mark_price": (0.0, 1e8), "oracle_price": (0.0, 1e8), "open_interest": (0.0, 1e14)}},
    "liquidations": {"depot": "hyperliquid-liquidations", "licence": "CC BY 4.0",
                     "colonnes": ("timestamp", "market", "wallet", "position_side", "size", "notional_usd", "avg_price"),
                     "cle": None, "bornes": {"notional_usd": (0.0, 1e10), "avg_price": (0.0, 1e8)}},
    "candles-1h": {"depot": "hyperliquid-candles-1h", "licence": "CC BY 4.0",
                   "colonnes": ("timestamp", "market", "open", "high", "low", "close", "volume"),
                   "cle": ("timestamp", "market"),
                   "bornes": {"open": (0.0, 1e8), "high": (0.0, 1e8), "low": (0.0, 1e8), "close": (0.0, 1e8),
                              "volume": (0.0, 1e16)}, "ohlc": True},
}
# La table `fills` des liquidations (une ligne par fill de liquidation) n'a pas le schéma des `events`.
SOUS_TABLES = {("liquidations", "fills"): {
    "colonnes": ("timestamp", "market", "wallet", "side", "price", "size", "notional_usd", "tx_hash"),
    "cle": None, "bornes": {"price": (0.0, 1e8), "notional_usd": (0.0, 1e10)}}}
VERSION_CONTROLES = 3          # change quand les contrôles changent : force la revalidation, jamais le retéléchargement


def spec_de(jeu: str, chemin_relatif: str) -> dict[str, Any]:
    parties = Path(chemin_relatif).parts
    for (j, sous), spec in SOUS_TABLES.items():
        if j == jeu and sous in parties:
            return {**JEUX[jeu], **spec}
    return JEUX[jeu]
DEBUT_PLAUSIBLE_MS = 1_672_531_200_000          # 2023-01-01 : avant, Hyperliquid perps n'existait pas sous cette forme


def lister(jeu: str, client: httpx.Client) -> list[dict]:
    r = client.get(API.format(jeu=JEUX[jeu]["depot"]), params={"recursive": "true"}, timeout=60)
    r.raise_for_status()
    return [e for e in r.json() if e.get("type") == "file" and e["path"].endswith(".parquet")]


def sha256(chemin: Path) -> str:
    h = hashlib.sha256()
    with chemin.open("rb") as f:
        for bloc in iter(lambda: f.read(1 << 20), b""):
            h.update(bloc)
    return h.hexdigest()


def telecharger(jeu: str, entree: dict, cible: Path, client: httpx.Client) -> str:
    """Rend 'deja_la', 'telecharge' ou lève. N'écrit le nom final qu'après vérification de l'empreinte."""
    attendu = (entree.get("lfs") or {}).get("oid")
    if cible.exists() and cible.stat().st_size == entree.get("size") and (attendu is None or sha256(cible) == attendu):
        return "deja_la"
    cible.parent.mkdir(parents=True, exist_ok=True)
    tmp = cible.with_suffix(cible.suffix + ".partiel")
    with client.stream("GET", FICHIER.format(jeu=JEUX[jeu]["depot"], chemin=entree["path"]), timeout=300,
                       follow_redirects=True) as r:
        r.raise_for_status()
        with tmp.open("wb") as f:
            for bloc in r.iter_bytes(1 << 20):
                f.write(bloc)
    obtenu = sha256(tmp)
    if attendu and obtenu != attendu:
        tmp.rename(tmp.with_suffix(".empreinte_fausse"))        # gardé pour diagnostic, jamais sous le nom final
        raise ValueError(f"empreinte {obtenu[:12]} != {attendu[:12]}")
    os.replace(tmp, cible)
    return "telecharge"


def _ms(v: Any) -> int | None:
    """Horodatage pyarrow -> ms UTC ; refuse les fuseaux non UTC plutôt que de deviner."""
    if v is None:
        return None
    try:
        return int(v.timestamp() * 1000)
    except (AttributeError, OverflowError, ValueError):
        return None


def valider(jeu: str, chemin: Path, chemin_relatif: str = "") -> dict:
    import pyarrow.compute as pc
    import pyarrow.parquet as pq

    spec = spec_de(jeu, chemin_relatif)
    incoherences_ohlc = 0
    motifs: list[str] = []
    f = pq.ParquetFile(chemin)
    schema = f.schema_arrow
    manquantes = [c for c in spec["colonnes"] if c not in schema.names]
    if manquantes:
        motifs.append(f"colonnes manquantes {manquantes}")
    ts_type = str(schema.field("timestamp").type) if "timestamp" in schema.names else None
    if ts_type and "tz=UTC" not in ts_type and "tz=utc" not in ts_type.lower():
        motifs.append(f"timestamp sans fuseau UTC explicite ({ts_type})")
    lignes, tmin, tmax, hors_bornes, nuls_ts, doublons = 0, None, None, {}, 0, 0
    vus: set = set()
    for i in range(f.num_row_groups):
        t = f.read_row_group(i)
        lignes += t.num_rows
        if "timestamp" in t.column_names:
            col = t.column("timestamp")
            nuls_ts += col.null_count
            mm = pc.min_max(col).as_py()
            for v in (mm["min"], mm["max"]):
                ms = _ms(v)
                if ms is not None:
                    tmin = ms if tmin is None else min(tmin, ms)
                    tmax = ms if tmax is None else max(tmax, ms)
        for c, (bas, haut) in spec["bornes"].items():
            if c in t.column_names:
                col = pc.drop_null(t.column(c))
                n = pc.sum(pc.or_(pc.less(col, bas), pc.greater(col, haut))).as_py() or 0
                hors_bornes[c] = hors_bornes.get(c, 0) + int(n)
        if spec.get("ohlc") and all(c in t.column_names for c in ("open", "high", "low", "close")):
            o, h, lo, c_ = (t.column(x) for x in ("open", "high", "low", "close"))
            mauvais = pc.or_(pc.less(h, pc.max_element_wise(o, c_)), pc.greater(lo, pc.min_element_wise(o, c_)))
            incoherences_ohlc += int(pc.sum(mauvais).as_py() or 0)
        if spec["cle"] and all(c in t.column_names for c in spec["cle"]):
            cles = zip(*(t.column(c).to_pylist() for c in spec["cle"]))
            for k in cles:
                if k in vus:
                    doublons += 1
                else:
                    vus.add(k)
    if lignes == 0:
        motifs.append("fichier vide")
    if nuls_ts:
        motifs.append(f"{nuls_ts} horodatages nuls")
    if tmin is not None and tmin < DEBUT_PLAUSIBLE_MS:
        motifs.append(f"date antérieure à 2023 ({tmin})")
    if tmax is not None and tmax > time.time() * 1000 + 86_400_000:
        motifs.append(f"date dans le futur ({tmax})")
    # Quelques lignes impossibles (ex. open interest NÉGATIF sans prix mark sur 4 marchés HIP-3 en juin-juillet
    # 2026) ne condamnent pas un mois entier : elles sont EXCLUES et nommées, jamais réparées. Au-delà de
    # 1 ligne sur 10 000, le fichier entier est refusé.
    exclusions = {c: n for c, n in hors_bornes.items() if n}
    if exclusions and sum(exclusions.values()) > max(1, lignes // 10_000):
        motifs.extend(f"{n} valeurs impossibles sur {c}" for c, n in exclusions.items())
        exclusions = {}
    if incoherences_ohlc:
        motifs.append(f"{incoherences_ohlc} bougies avec high < max(open, close) ou low > min(open, close)")
    if doublons:
        motifs.append(f"{doublons} doublons de clé {spec['cle']}")
    return {"lignes": lignes, "ts_min_ms": tmin, "ts_max_ms": tmax, "colonnes": schema.names,
            "lignes_exclues_a_la_lecture": {c: {"n": n, "regle": f"{c} hors {spec['bornes'][c]}"} for c, n in exclusions.items()},
            "statut": "EXTERNAL_REJECTED" if motifs else "EXTERNAL_VALIDATED", "motifs": motifs}


def main(argv: list[str] | None = None) -> int:
    for flux in (sys.stdout, sys.stderr):
        try:  # noqa: SIM105
            flux.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--racine", default=str(RACINE))
    p.add_argument("--jeux", nargs="+", default=list(JEUX), choices=list(JEUX))
    p.add_argument("--max-mo", type=float, default=800.0, help="plafond de téléchargement de CETTE exécution")
    a = p.parse_args(argv)
    base = Path(a.racine) / DOSSIER
    chemin_manifeste = base / "MANIFESTE.json"
    try:
        manifeste = json.loads(chemin_manifeste.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        manifeste = {"fichiers": {}}
    budget = a.max_mo * 1e6
    telecharges = 0.0
    with httpx.Client(headers=ENTETES) as client:
        for jeu in a.jeux:
            for e in sorted(lister(jeu, client), key=lambda x: x["path"]):
                cible = base / jeu / e["path"]
                cle = f"{jeu}/{e['path']}"
                connu = manifeste["fichiers"].get(cle, {})
                attendu = (e.get("lfs") or {}).get("oid")
                if (connu.get("sha256") == attendu and cible.exists() and connu.get("statut")
                        and connu.get("version_controles") == VERSION_CONTROLES):
                    continue                                        # idempotent : déjà ingéré et validé
                if not cible.exists() and telecharges + e.get("size", 0) > budget:
                    print(f"  [BUDGET] {cle} non téléchargé (plafond {a.max_mo:.0f} Mo atteint)")
                    continue
                try:
                    etat = telecharger(jeu, e, cible, client)
                except (httpx.HTTPError, ValueError, OSError) as exc:
                    manifeste["fichiers"][cle] = {"statut": "EXTERNAL_REJECTED", "motifs": [f"téléchargement : {exc}"]}
                    print(f"  [REFUS] {cle} : {exc}")
                    continue
                if etat == "telecharge":
                    telecharges += e.get("size", 0)
                v = valider(jeu, cible, e["path"])
                manifeste["fichiers"][cle] = {
                    "jeu": jeu, "url": FICHIER.format(jeu=JEUX[jeu]["depot"], chemin=e["path"]),
                    "editeur": "Ironflow (ironflow.sh), via Hugging Face", "licence": JEUX[jeu]["licence"],
                    "sha256": attendu, "octets": e.get("size"), "version_controles": VERSION_CONTROLES, "recupere_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "niveau_de_preuve": "RESEARCH_ELIGIBLE (descriptif / études d'événements) ; jamais REPLAY_ELIGIBLE :"
                                        " pas d'heure de réception Alina, données reconstruites après coup",
                    **v}
                print(f"  {cle:<42} {etat:<11} {v['lignes']:>9} lignes  {v['statut']}"
                      + (f"  {v['motifs']}" if v["motifs"] else ""))
                base.mkdir(parents=True, exist_ok=True)
                tmp = chemin_manifeste.with_suffix(".json.tmp")
                tmp.write_text(json.dumps(manifeste, ensure_ascii=False, indent=1), encoding="utf-8")
                os.replace(tmp, chemin_manifeste)                   # le manifeste suit chaque fichier : reprise exacte
    ok = sum(1 for x in manifeste["fichiers"].values() if x.get("statut") == "EXTERNAL_VALIDATED")
    print(f"  manifeste : {ok} fichiers validés / {len(manifeste['fichiers'])} | téléchargé cette fois : {telecharges / 1e6:.1f} Mo")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
