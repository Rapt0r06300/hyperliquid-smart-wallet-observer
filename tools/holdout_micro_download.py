"""HISTORICAL_HOLDOUT_V1 — micro-échantillon AWS, ONE-CLICK STRICTEMENT BORNÉ (rectif Flo 25/07).

DENY-BY-DEFAULT : refuse sans profil AWS. **Lecture S3 uniquement** (le profil DOIT être read-only côté IAM :
c'est la vraie garantie, pas ce script). **AUCUNE clé n'est écrite, loggée ni affichée** — jamais.

PLAFONDS INVIOLABLES (compteurs durs, arrêt immédiat au dépassement) :
    • 30 requêtes LIST      • 6 requêtes GET      • 50 Mo téléchargés      • 1,00 € de coût estimé
ARRÊT AUTO (NO-GO immédiat) si : taille dépassée · coût dépassé · format lz4 illisible · aucune attribution
vault · aucune jointure L2. Sinon GO. Rapport GO/NO-GO en fin : couverture, objets, octets, requêtes, coût max.

Flux : (1) profil → client S3 requester-pays ; (2) LIST bornée → dates node_fills ∩ L2 ; (3) choisir 2 fenêtres
+ objets par une RÈGLE DÉTERMINISTE, les PRÉ-ENREGISTRER (avant lecture) ; (4) GET bornés → décompresser →
`historical_holdout.executer` (gate) ; (5) GO/NO-GO. Aucun holdout complet. Le live RAW/OOS n'est PAS touché.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0, str(RACINE / "src"))
from hl_observer.experimental import historical_holdout as HH   # noqa: E402

SORTIE = RACINE / "runtime" / "rapports" / "holdout"
PROFIL_DEFAUT = "hl-holdout-ro"
BUCKET_NOEUD = "hl-mainnet-node-data"
BUCKET_MARCHE = "hyperliquid-archive"

MAX_LIST = 30
MAX_GET = 6
MAX_OCTETS = 50 * 1024 * 1024                     # 50 Mo
MAX_EUR = 1.00
EUR_PAR_GO_EGRESS = 0.084                         # ~0,09 $/Go d'egress S3, en euros (garde-fou ; 50 Mo ≈ 0,004 €)
_DATE = re.compile(r"(20\d{2})[-/]?(\d{2})[-/]?(\d{2})")


class ArretPlafond(RuntimeError):
    """Un plafond inviolable a été atteint : on ARRÊTE, on ne dépasse jamais."""


class ProfilAbsent(RuntimeError):
    """Aucun identifiant AWS : deny-by-default, on ne tente RIEN."""


# ============================ client S3 borné (requester-pays, read-only) ==========================
class ClientBorne:
    """Enveloppe comptant chaque requête et chaque octet, plafonds DURS. `_s3` peut être injecté (tests)."""

    def __init__(self, s3=None):
        self._s3 = s3
        self.n_list = 0
        self.n_get = 0
        self.octets = 0
        self.objets: list[tuple[str, int]] = []

    @property
    def cout_eur(self) -> float:
        return round(self.octets / 1e9 * EUR_PAR_GO_EGRESS, 6)

    def _garde_cout(self) -> None:
        if self.octets > MAX_OCTETS:
            raise ArretPlafond("TAILLE > 50 Mo (%d o)" % self.octets)
        if self.cout_eur > MAX_EUR:
            raise ArretPlafond("COUT estimé > 1 € (%.4f €)" % self.cout_eur)

    def lister(self, bucket: str, prefix: str, *, delimiter: str = "/", max_keys: int = 400):
        if self.n_list >= MAX_LIST:
            raise ArretPlafond("30 requêtes LIST atteintes")
        self.n_list += 1
        r = self._s3.list_objects_v2(Bucket=bucket, Prefix=prefix, Delimiter=delimiter,
                                     MaxKeys=max_keys, RequestPayer="requester")
        prefixes = [p.get("Prefix", "") for p in r.get("CommonPrefixes", [])]
        contents = [(c["Key"], int(c.get("Size") or 0)) for c in r.get("Contents", [])]
        return prefixes, contents

    def telecharger(self, bucket: str, key: str, *, taille_attendue: int | None = None) -> bytes:
        if self.n_get >= MAX_GET:
            raise ArretPlafond("6 requêtes GET atteintes")
        if taille_attendue is not None and self.octets + taille_attendue > MAX_OCTETS:
            raise ArretPlafond("GET refusé : dépasserait 50 Mo (%s, %d o)" % (key, taille_attendue))
        self.n_get += 1
        corps = self._s3.get_object(Bucket=bucket, Key=key, RequestPayer="requester")["Body"]
        morceaux, total = [], 0
        for bloc in iter(lambda: corps.read(1 << 20), b""):
            total += len(bloc)
            if self.octets + total > MAX_OCTETS:
                raise ArretPlafond("TAILLE > 50 Mo pendant le GET (%s)" % key)
            morceaux.append(bloc)
        self.octets += total
        self.objets.append((key, total))
        self._garde_cout()
        return b"".join(morceaux)


def construire_client(profile: str) -> ClientBorne:
    """Construit un client boto3 depuis un PROFIL DÉDIÉ (read-only). Refuse si aucun identifiant. Ne logge RIEN."""
    try:
        import boto3
        from botocore.exceptions import BotoCoreError, NoCredentialsError  # noqa: F401
    except ImportError as exc:
        raise ProfilAbsent("boto3 absent : `pip install boto3` (paquet Python, PAS un compte). %s" % exc)
    session = boto3.Session(profile_name=profile)
    if session.get_credentials() is None:
        raise ProfilAbsent("aucun identifiant pour le profil %r (créer le profil read-only). Rien tenté." % profile)
    # region auto : location du bucket noeud (1 appel léger, hors budget LIST car métadonnée de bucket)
    s3 = session.client("s3")
    try:
        loc = s3.get_bucket_location(Bucket=BUCKET_NOEUD)["LocationConstraint"] or "us-east-1"
        s3 = session.client("s3", region_name=loc)
    except Exception:                                            # noqa: BLE001
        pass
    return ClientBorne(s3)


# ============================ règle déterministe : fenêtres + objets ================================
def _dates(chaines) -> list[str]:
    out = set()
    for s in chaines:
        m = _DATE.search(s or "")
        if m:
            out.add("".join(m.groups()))
    return sorted(out)


def choisir_objets(cli: ClientBorne, *, coin: str) -> dict:
    """RÈGLE DÉTERMINISTE (aucun coup d'œil aux résultats) : dates node_fills ∩ L2 → **médiane** = date holdout ;
    heure 12 ; objets = L2 {coin, BTC} + node_fills_by_block de la date. Rend la pré-registration à figer."""
    pn, cn = cli.lister(BUCKET_NOEUD, "node_fills_by_block/")
    dates_f = _dates(pn + [k for k, _ in cn])
    pm, cm = cli.lister(BUCKET_MARCHE, "market_data/")
    dates_l2 = _dates(pm + [k for k, _ in cm])
    overlap = sorted(set(dates_f) & set(dates_l2))
    if not overlap:
        raise ArretPlafond("aucun chevauchement node_fills ∩ L2 (rien à échantillonner)")
    d = overlap[len(overlap) // 2]                                # médiane = déterministe, pas de cherry-pick
    coins = [coin.upper(), "BTC"]
    objets_l2 = ["market_data/%s/12/l2Book/%s.lz4" % (d, c) for c in dict.fromkeys(coins)]
    # node_fills : découvrir les objets de la date (structure réelle) et prendre le plus petit couvrant l'heure
    pf, cf = cli.lister(BUCKET_NOEUD, "node_fills_by_block/%s/" % d)
    node_objets = sorted((k for k, _ in cf), key=lambda k: dict(cf).get(k, 0))[:1] or \
        ["node_fills_by_block/%s/12" % d]
    spec = {"date_holdout": d, "heure": 12, "coins": coins,
            "objets_l2": [(BUCKET_MARCHE, k) for k in objets_l2],
            "objets_node_fills": [(BUCKET_NOEUD, k) for k in node_objets],
            "overlap_dates": [overlap[0], overlap[-1]], "n_overlap": len(overlap)}
    spec["prereg_hash"] = hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()[:16]
    return spec


# ============================ orchestration + GO/NO-GO ============================================
def executer(cli: ClientBorne, vaults: list[str], *, coin: str = "SOL") -> dict:
    """Bout-en-bout borné. Rend le rapport GO/NO-GO. Arrêt AUTO à la 1re faille (taille/coût/format/attribution/L2)."""
    SORTIE.mkdir(parents=True, exist_ok=True)
    rap = {"ts_ms": int(time.time() * 1000), "vaults_suivis": len(vaults)}
    try:
        spec = choisir_objets(cli, coin=coin)
        (SORTIE / "holdout_micro_preregistration.json").write_text(
            json.dumps(spec, indent=2, ensure_ascii=False), encoding="utf-8")   # PRÉ-ENREGISTRÉ avant lecture
        rap["preregistration"] = spec

        node_records, l2_records = [], []
        for bucket, key in spec["objets_node_fills"]:
            try:
                node_records += list(HH._lignes_json(HH.decompresser_lz4(cli.telecharger(bucket, key))))
            except ArretPlafond:
                raise
            except Exception as exc:                              # noqa: BLE001
                return _finir(cli, rap, "NO_GO", "FORMAT_NODE_FILLS_ILLISIBLE:%s" % str(exc)[:60], spec)
        for bucket, key in spec["objets_l2"]:
            try:
                l2_records += list(HH._lignes_json(HH.decompresser_lz4(cli.telecharger(bucket, key))))
            except ArretPlafond:
                raise
            except Exception as exc:                              # noqa: BLE001
                return _finir(cli, rap, "NO_GO", "FORMAT_L2_ILLISIBLE:%s" % str(exc)[:60], spec)

        gate = HH.executer(node_records, l2_records, vaults, coin_placebo="BTC")
        rap["gate"] = {"couverture": gate["couverture"], "vaults_avec_fills": gate.get("vaults_avec_fills"),
                       "coins_l2": gate.get("coins_l2")}
        if not gate.get("vaults_avec_fills"):
            return _finir(cli, rap, "NO_GO", "ATTRIBUTION_VAULT_NULLE", spec)
        if gate["couverture"]["l2_synchronise"] < 1:
            return _finir(cli, rap, "NO_GO", "JOINTURE_L2_NULLE", spec)
        return _finir(cli, rap, "GO", "attribution+jointure+format OK", spec)
    except ArretPlafond as stop:
        return _finir(cli, rap, "NO_GO", "PLAFOND:%s" % stop, rap.get("preregistration"))
    except ProfilAbsent as pa:
        rap.update({"verdict": "REFUS", "raison": str(pa)})
        return rap


def _finir(cli: ClientBorne, rap: dict, verdict: str, raison: str, spec) -> dict:
    rap.update({
        "verdict": verdict, "raison": raison,
        "requetes": {"list": cli.n_list, "get": cli.n_get, "list_max": MAX_LIST, "get_max": MAX_GET},
        "octets": cli.octets, "octets_max": MAX_OCTETS,
        "cout_eur_estime": cli.cout_eur, "cout_eur_max": MAX_EUR,
        "objets": cli.objets, "preregistration": spec,
    })
    (SORTIE / "holdout_micro_go_nogo.json").write_text(json.dumps(rap, indent=2, ensure_ascii=False), encoding="utf-8")
    return rap


def _vaults_suivis() -> list[str]:
    """Vaults suivis (lecture seule) depuis le scoring runtime ; défaut vide si absent (jamais inventé)."""
    p = RACINE / "runtime" / "data" / "vaults_scores.json"
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        return [str(c["vault"]) for c in (d.get("classement") or []) if c.get("vault")]
    except (OSError, ValueError, KeyError):
        return []


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Micro-échantillon holdout AWS — borné, read-only, GO/NO-GO.")
    ap.add_argument("--profile", default=PROFIL_DEFAUT)
    ap.add_argument("--coin", default="SOL", help="coin primaire pré-enregistré (le 2e est toujours BTC).")
    a = ap.parse_args()
    try:
        cli = construire_client(a.profile)
    except ProfilAbsent as exc:
        print("REFUS (deny-by-default) :", exc)
        print("  Rien téléchargé, aucune clé lue/affichée. Configure d'abord le profil read-only.")
        raise SystemExit(3)
    r = executer(cli, _vaults_suivis(), coin=a.coin)
    print("VERDICT :", r["verdict"], "·", r.get("raison"))
    print("  requêtes LIST=%s/%s GET=%s/%s · octets=%s/%s · coût≈%.4f €/%.2f €" % (
        r.get("requetes", {}).get("list"), MAX_LIST, r.get("requetes", {}).get("get"), MAX_GET,
        r.get("octets"), MAX_OCTETS, r.get("cout_eur_estime", 0.0), MAX_EUR))
    print("  rapport : runtime/rapports/holdout/holdout_micro_go_nogo.json")
    print("  SÉCURITÉ : lecture S3 seule · 0 clé loggée · 0 ordre réel · live intact.")
