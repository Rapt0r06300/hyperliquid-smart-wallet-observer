r"""Ingestion bornée, idempotente et reprenable du Reservoir d'Hydromancer (Hugging Face, CC BY 4.0).

    tools\python\python.exe tools\ingerer_hydromancer.py                     (carnets, instantanés, bougies, liquidations)
    tools\python\python.exe tools\ingerer_hydromancer.py --jeux snapshots --max-go 1

Source : https://huggingface.co/datasets/Hydromancer/hyperliquid-reservoir (licence CC BY 4.0, public, gratuit).
La même archive sur S3 est en « requester pays » (payante) : on ne la touche pas.

Ce qui est pris, et pourquoi (mesuré le 23/11/2026 sur l'API publique) :
- ``orderbooks_perps`` (21,1 Go, 338 jours, 15/12/2025 -> 17/11/2026) : 20 niveaux par côté, chaque minute, pour 463
  perps -- le CARNET À LA SORTIE des épisodes, ce qui manque au labo ;
- ``snapshots`` (0,66 Go) : positions et valeur de chaque compte, le 1er de chaque mois ;
- ``candles_1m`` (2,0 Go) : bougies 1 minute de chaque marché ;
- ``liquidations`` (0,32 Go) : chaque liquidation, avec le compte.
Les fills de tous les comptes (199 Go) ne sont PAS pris ici : il faudrait tout télécharger pour garder nos leaders.

Garanties (comme ``ingerer_ironflow.py``) :
1. liste par l'API Hugging Face (chemin, taille, SHA-256 LFS officiel) ;
2. télécharge seulement ce qui manque ou a changé, dans un ``.part`` renommé une fois l'empreinte VÉRIFIÉE ;
3. valide chaque fichier sans le charger d'un bloc (schéma, heures du jour du fichier, carnets non croisés…) ;
4. écrit ``runtime/history/hydromancer/MANIFESTE.json`` : provenance, licence, empreinte, statut, niveau de preuve.
Les fichiers restent TELS QUE PUBLIÉS (Parquet compressé, sans perte). Rien n'est SAFE : aucune heure de réception
par Alina. Aucun ordre, aucune clé, aucune écriture hors de ``runtime/history/hydromancer/``.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

import httpx

RACINE = Path(__file__).resolve().parents[1]
DOSSIER = Path("runtime") / "history" / "hydromancer"
DEPOT = "Hydromancer/hyperliquid-reservoir"
API = "https://huggingface.co/api/datasets/" + DEPOT + "/tree/main/{prefixe}?recursive=true"
FICHIER = "https://huggingface.co/datasets/" + DEPOT + "/resolve/main/{chemin}"
ENTETES = {"User-Agent": "research-client"}
LICENCE = "CC BY 4.0 (Hydromancer Reservoir)"
NIVEAU = "RESEARCH_ELIGIBLE ; observations de marché reconstruites, pas d'heure de réception Alina"

#: jeu -> préfixe et colonnes minimales attendues
JEUX: dict[str, dict[str, Any]] = {
    "orderbooks_perps": {"prefixe": "orderbooks_perps", "colonnes": ("coin", "dex", "time", "block_time_ms", "bids", "asks")},
    "snapshots": {"prefixe": "snapshots", "colonnes": ()},
    "candles_1m": {"prefixe": "candles_1m", "colonnes": ()},
    "liquidations": {"prefixe": "liquidations", "colonnes": ()},
}
CROISES_MAX = 0.001          # part de carnets croisés (meilleur bid >= meilleur ask) tolérée par fichier
ECART_BLOC_MAX_MS = 300_000  # |time - block_time_ms| toléré (5 min)


def lister(prefixe: str, client: httpx.Client) -> list[dict]:
    """Tous les fichiers sous un préfixe (pagination suivie : l'API ne rend qu'une page à la fois)."""
    url: str | None = API.format(prefixe=prefixe)
    out: list[dict] = []
    while url:
        r = client.get(url, headers=ENTETES, timeout=60)
        r.raise_for_status()
        out += [x for x in r.json() if x.get("type") == "file"]
        lien = r.headers.get("link") or ""
        m = re.search(r'<([^>]+)>;\s*rel="next"', lien)
        url = m.group(1) if m else None
    return out


def sha256(chemin: Path) -> str:
    h = hashlib.sha256()
    with chemin.open("rb") as f:
        for bloc in iter(lambda: f.read(8 << 20), b""):
            h.update(bloc)
    return h.hexdigest()


def telecharger(entree: dict, cible: Path, client: httpx.Client) -> str:
    """'deja_la' ou 'telecharge' ; n'écrit le nom final qu'après vérification de l'empreinte officielle."""
    attendu = (entree.get("lfs") or {}).get("oid")
    taille = (entree.get("lfs") or {}).get("size") or entree.get("size")
    if cible.exists() and cible.stat().st_size == taille and (attendu is None or sha256(cible) == attendu):
        return "deja_la"
    cible.parent.mkdir(parents=True, exist_ok=True)
    part = cible.with_name(cible.name + ".part")
    h = hashlib.sha256()
    with client.stream("GET", FICHIER.format(chemin=entree["path"]), headers=ENTETES, timeout=300,
                       follow_redirects=True) as r:
        r.raise_for_status()
        with part.open("wb") as f:
            for morceau in r.iter_bytes(1 << 20):
                f.write(morceau)
                h.update(morceau)
    if attendu and h.hexdigest() != attendu:
        part.unlink()
        raise ValueError(f"empreinte differente pour {entree['path']}")
    for i in range(8):
        try:
            os.replace(part, cible)
            break
        except PermissionError:
            if i == 7:
                raise
            time.sleep(0.25 * (i + 1))
    return "telecharge"


def _jour(chemin_relatif: str) -> dt.date | None:
    m = re.search(r"(\d{4}-\d{2}-\d{2})", chemin_relatif)
    return dt.date.fromisoformat(m.group(1)) if m else None


def valider(jeu: str, chemin: Path, chemin_relatif: str) -> dict[str, Any]:
    """Statut + motifs, sans charger le fichier d'un bloc (lecture par groupes de lignes)."""
    import pyarrow.compute as pc
    import pyarrow.parquet as pq

    motifs: list[str] = []
    f = pq.ParquetFile(chemin)
    noms = set(f.schema_arrow.names)
    manque = [c for c in JEUX[jeu]["colonnes"] if c not in noms]
    if manque:
        motifs.append(f"colonnes absentes : {manque}")
    lignes = f.metadata.num_rows
    croises = ts_min = ts_max = 0
    ecart_bloc = un_cote = 0
    if jeu == "orderbooks_perps" and not manque:
        ts_min, ts_max = None, None
        for i in range(f.num_row_groups):
            t = f.read_row_group(i, columns=["time", "block_time_ms", "bids", "asks"])
            temps = t.column("time").cast("int64").to_numpy()
            unite = t.schema.field("time").type.unit
            temps_ms = temps // {"s": 1 / 1000, "ms": 1, "us": 1000, "ns": 1_000_000}[unite] if unite != "s" else temps * 1000
            bloc = t.column("block_time_ms").cast("int64").to_numpy()
            ecart_bloc += int((abs(temps_ms - bloc) > ECART_BLOC_MAX_MS).sum())
            # un côté VIDE existe (marché sans offre d'un côté) : compté et nommé, jamais lu comme un niveau
            deux_cotes = pc.and_(pc.greater(pc.list_value_length(t.column("bids")), 0),
                                 pc.greater(pc.list_value_length(t.column("asks")), 0))
            un_cote += int(len(t) - (pc.sum(deux_cotes).as_py() or 0))
            pleins = t.filter(deux_cotes)
            if len(pleins):
                bb = pc.cast(pc.struct_field(pc.list_element(pleins.column("bids"), 0), "px"), "float64")
                ba = pc.cast(pc.struct_field(pc.list_element(pleins.column("asks"), 0), "px"), "float64")
                croises += int(pc.sum(pc.greater_equal(bb, ba)).as_py() or 0)
            ts_min = int(temps_ms.min()) if ts_min is None else min(ts_min, int(temps_ms.min()))
            ts_max = int(temps_ms.max()) if ts_max is None else max(ts_max, int(temps_ms.max()))
        jour = _jour(chemin_relatif)
        if jour is not None:
            debut = int(dt.datetime(jour.year, jour.month, jour.day, tzinfo=dt.timezone.utc).timestamp() * 1000)
            if ts_min < debut - 3_600_000 or ts_max > debut + 25 * 3_600_000:
                motifs.append(f"heures hors du jour du fichier : [{ts_min} ; {ts_max}]")
        if croises > CROISES_MAX * max(1, lignes):
            motifs.append(f"carnets croises : {croises} sur {lignes}")
        if ecart_bloc:
            motifs.append(f"{ecart_bloc} instantanes a plus de 5 min de leur bloc")
    return {"statut": "EXTERNAL_REJECTED" if motifs else "EXTERNAL_VALIDATED", "motifs": motifs, "lignes": lignes,
            "ts_min_ms": ts_min or None, "ts_max_ms": ts_max or None, "carnets_croises": croises,
            "carnets_a_un_seul_cote": un_cote}


def main(argv: list[str] | None = None) -> int:
    for flux in (sys.stdout, sys.stderr):
        try:  # noqa: SIM105
            flux.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--racine", default=str(RACINE))
    p.add_argument("--jeux", nargs="+", default=list(JEUX), choices=list(JEUX))
    p.add_argument("--max-go", type=float, default=30.0, help="plafond de téléchargement de CETTE exécution")
    a = p.parse_args(argv)
    root = Path(a.racine)
    dossier = root / DOSSIER
    chemin_man = dossier / "MANIFESTE.json"
    try:
        manifeste = json.loads(chemin_man.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        manifeste = {"source": DEPOT, "licence": LICENCE, "fichiers": {}}
    budget = a.max_go * 1e9
    telecharges = 0
    with httpx.Client() as client:
        for jeu in a.jeux:
            entrees = lister(JEUX[jeu]["prefixe"], client)
            print(f"  {jeu:<18} {len(entrees):>4} fichiers, {sum(int(e.get('size') or 0) for e in entrees) / 1e9:.2f} Go",
                  flush=True)
            for e in entrees:
                cle = e["path"]
                cible = dossier / cle
                connu = manifeste["fichiers"].get(cle, {})
                attendu = (e.get("lfs") or {}).get("oid")
                if connu.get("sha256") == attendu and cible.exists() and connu.get("statut"):
                    continue
                if not cible.exists() and telecharges + int(e.get("size") or 0) > budget:
                    print(f"  [budget] plafond de {a.max_go} Go atteint : reprise au prochain lancement", flush=True)
                    break
                etat = telecharger(e, cible, client)
                if etat == "telecharge":
                    telecharges += int(e.get("size") or 0)
                v = valider(jeu, cible, cle) if cle.endswith(".parquet") else {"statut": "EXTERNAL_VALIDATED", "motifs": []}
                manifeste["fichiers"][cle] = {"jeu": jeu, "url": FICHIER.format(chemin=cle), "editeur": "Hydromancer",
                                              "licence": LICENCE, "sha256": attendu, "octets": e.get("size"),
                                              "recupere_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                                              "niveau_de_preuve": NIVEAU, **v}
                tmp = chemin_man.with_name(chemin_man.name + ".tmp")
                dossier.mkdir(parents=True, exist_ok=True)
                tmp.write_text(json.dumps(manifeste, ensure_ascii=False, indent=1), encoding="utf-8")
                os.replace(tmp, chemin_man)                         # le manifeste suit chaque fichier : reprise exacte
                print(f"    {etat:<10} {v['statut']:<18} {cle}  {('; '.join(v['motifs']))[:120]}", flush=True)
    valides = sum(1 for m in manifeste["fichiers"].values() if m.get("statut") == "EXTERNAL_VALIDATED")
    print(f"  manifeste : {valides} fichiers valides / {len(manifeste['fichiers'])} | telecharge cette fois : "
          f"{telecharges / 1e9:.2f} Go", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
