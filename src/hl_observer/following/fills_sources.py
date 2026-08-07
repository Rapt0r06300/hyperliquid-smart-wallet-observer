"""Sources de fills pour le Global Wallet Observer — normalisation, streaming, reprise (0 réseau ici).

`wallet_reconstruction` sait reconstruire un cycle de vie à partir d'un contrat de fill précis
(`user, coin, side|dir, sz, px, time, start_pos, tid, oid, twap_id`). Le problème n'a jamais été le moteur :
c'est que les fills réels arrivent dans **cinq schémas différents** selon le collecteur qui les a écrits.

Ce module est l'adaptateur. Il fait trois choses, et refuse d'en faire une quatrième :

1. **Normaliser** chaque schéma connu vers le contrat unique, sans jamais inventer un champ absent.
2. **Étiqueter l'autorité de la source.** Une archive officielle (`node_fills_by_block`) ou un collecteur
   maison sont `autoritative=True`. Un **miroir public non vérifié** est `autoritative=False` : utilisable
   en *bootstrap* pour valider une chaîne de traitement, **jamais** pour scorer un wallet. Un edge mesuré sur
   des données dont on ne peut pas prouver la provenance n'est pas un edge, c'est une rumeur.
3. **Streamer avec reprise** : lecture ligne à ligne, mémoire bornée, checkpoint sur l'offset d'octets — un
   fichier de plusieurs Go ne doit jamais tenir en RAM, et une interruption ne doit jamais tout refaire.

Deny-by-default : champ obligatoire manquant ⇒ fill rejeté et **compté** par motif, jamais complété.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator, Mapping

SCHEMA_VERSION = "hypersmart.fills_sources.v1"

#: Champs du contrat attendu par `wallet_reconstruction`.
REQUIS = ("user", "coin", "sz", "px", "time")

#: Sources connues. `autoritative=False` ⇒ bootstrap seulement, jamais de scoring.
#: `alias` mappe {champ_contrat: (noms possibles dans la source, du plus au moins prioritaire)}.
SOURCES: dict[str, dict[str, Any]] = {
    "vault_fills": {
        "autoritative": True,
        "description": "collecteur maison userFillsByTime des vaults (porte start_position)",
        "alias": {"user": ("vault", "user", "adresse"), "coin": ("coin",), "sz": ("sz",), "px": ("px",),
                  "time": ("ts_ms", "time"), "start_pos": ("start_position", "startPosition"),
                  "dir": ("dir",), "side": ("side",), "oid": ("oid",), "tid": ("tid", "hash"),
                  "twap_id": ("twap_id", "twapId")},
    },
    "vault_fills_live": {
        "autoritative": True,
        "description": "flux WS userFills des vaults (sans start_position)",
        "alias": {"user": ("vault", "user"), "coin": ("coin",), "sz": ("sz",), "px": ("px",),
                  "time": ("ts_ms", "time"), "dir": ("dir",), "side": ("side",),
                  "oid": ("oid",), "tid": ("tid", "hash"), "twap_id": ("twap_id", "twapId")},
    },
    "node_fills_by_block": {
        "autoritative": True,
        "description": "archive officielle Hyperliquid (S3 requester-pays)",
        "alias": {"user": ("user", "address"), "coin": ("coin",), "sz": ("sz",), "px": ("px",),
                  "time": ("time", "ts_ms"), "start_pos": ("startPosition", "start_position"),
                  "dir": ("dir",), "side": ("side",), "oid": ("oid",), "tid": ("tid", "hash"),
                  "twap_id": ("twapId", "twap_id")},
    },
    "miroir_non_verifie": {
        "autoritative": False,
        "description": "miroir public de node_fills_by_block — BOOTSTRAP UNIQUEMENT, jamais autoritatif",
        "alias": {"user": ("user", "address", "wallet"), "coin": ("coin",), "sz": ("sz",), "px": ("px",),
                  "time": ("time", "ts_ms"), "start_pos": ("startPosition", "start_position"),
                  "dir": ("dir",), "side": ("side",), "oid": ("oid",), "tid": ("tid", "hash"),
                  "twap_id": ("twapId", "twap_id")},
    },
}


def est_autoritative(source: str) -> bool:
    """Une source inconnue n'est jamais autoritative : on ne présume pas de ce qu'on n'a pas déclaré."""
    return bool(SOURCES.get(str(source), {}).get("autoritative", False))


def _premier(brut: Mapping[str, Any], noms: tuple[str, ...]) -> Any:
    for nom in noms:
        if nom in brut and brut[nom] not in (None, ""):
            return brut[nom]
    return None


def _nombre(v: Any) -> float | None:
    if isinstance(v, bool) or v is None:
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x != x else x


def _side_depuis_signe(brut: Mapping[str, Any]) -> str | None:
    """Certains collecteurs écrivent `signe` (+1/-1) au lieu de `side`. On traduit, on ne devine pas."""
    signe = brut.get("signe")
    if isinstance(signe, bool) or signe is None:
        return None
    try:
        s = int(signe)
    except (TypeError, ValueError):
        return None
    return "B" if s > 0 else ("A" if s < 0 else None)


def normaliser_fill(brut: Mapping[str, Any], *, source: str) -> tuple[dict[str, Any] | None, str | None]:
    """Rend `(fill_normalise, motif_de_refus)`. Exactement l'un des deux est `None`."""
    config = SOURCES.get(str(source))
    if config is None:
        return None, "SOURCE_INCONNUE"
    alias = config["alias"]

    user = _premier(brut, alias.get("user", ()))
    coin = _premier(brut, alias.get("coin", ()))
    sz = _nombre(_premier(brut, alias.get("sz", ())))
    px = _nombre(_premier(brut, alias.get("px", ())))
    ts = _nombre(_premier(brut, alias.get("time", ())))

    if not user or not coin:
        return None, "WALLET_OU_COIN_ABSENT"
    if sz is None or sz <= 0:
        return None, "TAILLE_ABSENTE"
    if px is None or px <= 0:
        return None, "PRIX_ABSENT"
    if ts is None or ts <= 0:
        return None, "HORODATAGE_ABSENT"

    side = _premier(brut, alias.get("side", ())) or _side_depuis_signe(brut)
    direction = _premier(brut, alias.get("dir", ()))
    if side is None and direction is None:
        return None, "SENS_INCONNU"

    fill: dict[str, Any] = {
        "user": str(user).strip().lower(), "coin": str(coin).strip().upper(),
        "sz": sz, "px": px, "time": int(ts),
        "source": str(source), "autoritative": bool(config["autoritative"]),
    }
    if side is not None:
        fill["side"] = side
    if direction is not None:
        fill["dir"] = direction
    for cle in ("start_pos", "oid", "tid", "twap_id"):
        valeur = _premier(brut, alias.get(cle, ()))
        if valeur is not None:
            fill[cle] = _nombre(valeur) if cle == "start_pos" else valeur
    return fill, None


def valider_schema(chemin: Path | str, *, source: str, echantillon: int = 200) -> dict[str, Any]:
    """Inspecte un échantillon AVANT d'ingérer : quels champs du contrat sont réellement présents ?

    Sert à refuser une source qui « ressemble » au bon format mais n'a ni prix ni taille — on le voit sur
    200 lignes plutôt que sur 40 millions.
    """
    presents: dict[str, int] = {}
    refus: dict[str, int] = {}
    lus = ok = 0
    p = Path(chemin)
    if not p.exists():
        return {"statut": "FICHIER_ABSENT", "chemin": str(chemin), "utilisable": False,
                "autoritative": est_autoritative(source)}
    with p.open("r", encoding="utf-8", errors="replace") as fh:
        for ligne in fh:
            if lus >= int(echantillon):
                break
            ligne = ligne.strip()
            if not ligne:
                continue
            lus += 1
            try:
                brut = json.loads(ligne)
            except ValueError:
                refus["JSON_INVALIDE"] = refus.get("JSON_INVALIDE", 0) + 1
                continue
            if not isinstance(brut, dict):
                refus["PAS_UN_OBJET"] = refus.get("PAS_UN_OBJET", 0) + 1
                continue
            fill, motif = normaliser_fill(brut, source=source)
            if fill is None:
                refus[motif or "INCONNU"] = refus.get(motif or "INCONNU", 0) + 1
                continue
            ok += 1
            for cle in ("start_pos", "tid", "oid", "twap_id", "side", "dir"):
                if cle in fill:
                    presents[cle] = presents.get(cle, 0) + 1
    taux = round(ok / lus, 4) if lus else 0.0
    return {
        "statut": "VALIDE" if ok else "AUCUN_FILL_EXPLOITABLE",
        "chemin": str(chemin), "source": source, "autoritative": est_autoritative(source),
        "n_lignes_echantillon": lus, "n_normalisables": ok, "taux_normalisable": taux,
        "champs_presents": presents, "refus": refus,
        "start_pos_disponible": bool(presents.get("start_pos")),
        "utilisable": bool(ok),
        "note": (None if est_autoritative(source) else
                 "source NON autoritative : bootstrap uniquement, aucun scoring ne doit s'y appuyer"),
    }


@dataclass
class Checkpoint:
    """Reprise par offset d'octets. Une interruption ne doit jamais imposer de tout relire."""

    chemin: Path
    offset: int = 0
    n_lignes: int = 0
    n_fills: int = 0

    @classmethod
    def charger(cls, chemin: Path | str) -> "Checkpoint":
        p = Path(chemin)
        if p.exists():
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
                return cls(p, int(d.get("offset") or 0), int(d.get("n_lignes") or 0),
                           int(d.get("n_fills") or 0))
            except (ValueError, OSError):
                import logging as _lg  # panne rendue VISIBLE (interdiction des except:pass muets)
                _lg.getLogger(__name__).debug("exception ignoree volontairement ici", exc_info=True)
        return cls(p)

    def enregistrer(self) -> None:
        self.chemin.parent.mkdir(parents=True, exist_ok=True)
        self.chemin.write_text(json.dumps(
            {"offset": self.offset, "n_lignes": self.n_lignes, "n_fills": self.n_fills,
             "schema_version": SCHEMA_VERSION}), encoding="utf-8")


@dataclass
class StatsIngestion:
    n_lignes: int = 0
    n_fills: int = 0
    refus: dict[str, int] = field(default_factory=dict)
    sources: dict[str, int] = field(default_factory=dict)

    def resume(self) -> dict[str, Any]:
        return {"n_lignes": self.n_lignes, "n_fills": self.n_fills,
                "n_refuses": sum(self.refus.values()), "refus": dict(self.refus),
                "sources": dict(self.sources)}


def flux_fills(chemin: Path | str, *, source: str, stats: StatsIngestion | None = None,
               checkpoint: Checkpoint | None = None, max_fills: int | None = None) -> Iterator[dict[str, Any]]:
    """Générateur de fills normalisés. Mémoire bornée : une ligne à la fois, rien n'est accumulé ici."""
    s = stats if stats is not None else StatsIngestion()
    p = Path(chemin)
    if not p.exists():
        return
    with p.open("r", encoding="utf-8", errors="replace") as fh:
        if checkpoint is not None and checkpoint.offset > 0:
            fh.seek(checkpoint.offset)
        for ligne in fh:
            s.n_lignes += 1
            brute = ligne.strip()
            if checkpoint is not None:
                checkpoint.offset += len(ligne.encode("utf-8", errors="replace"))
                checkpoint.n_lignes += 1
            if not brute:
                continue
            try:
                objet = json.loads(brute)
            except ValueError:
                s.refus["JSON_INVALIDE"] = s.refus.get("JSON_INVALIDE", 0) + 1
                continue
            if not isinstance(objet, dict):
                s.refus["PAS_UN_OBJET"] = s.refus.get("PAS_UN_OBJET", 0) + 1
                continue
            fill, motif = normaliser_fill(objet, source=source)
            if fill is None:
                s.refus[motif or "INCONNU"] = s.refus.get(motif or "INCONNU", 0) + 1
                continue
            s.n_fills += 1
            s.sources[source] = s.sources.get(source, 0) + 1
            if checkpoint is not None:
                checkpoint.n_fills += 1
            yield fill
            if max_fills is not None and s.n_fills >= int(max_fills):
                return


__all__ = ["SCHEMA_VERSION", "REQUIS", "SOURCES", "Checkpoint", "StatsIngestion",
           "est_autoritative", "normaliser_fill", "valider_schema", "flux_fills"]
