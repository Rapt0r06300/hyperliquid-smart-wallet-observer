"""Liaison d'un carnet de référence **déjà reçu avant le signal** à un métaordre.

POURQUOI — BLOQUEUR P0 CONFIRMÉ LE 16/11/2026, L'AUTRE MOITIÉ DU ZÉRO EXÉCUTABLE.
`CopyVaultCheckpointTail` ne programmait le checkpoint `REFERENCE` qu'**après** avoir lu le fill :
sa requête REST partait donc après le signal et revenait 320 à 1 527 ms plus tard (51 références
sur 51 dans les 4 000 dernières lignes inspectées). Le chargeur les date correctement par leur
réception et l'exécuteur les refuse — à raison : un carnet reçu après le signal ne peut pas avoir
servi à décider. Résultat : 77 008 refus `STALE_OR_MISSING_REFERENCE_BOOK` sur 98 138 signaux, et
**zéro trade exécutable**.

Ce n'est pas une fenêtre de fraîcheur à élargir. Il faut lier au métaordre un carnet **réellement
observé avant** le signal. Le ruban WS continu `copy_vault_l2_lane.jsonl` en contient, et il porte
déjà `connection_id` et `l2_gap_epoch`.

MESURE DU 16/11/2026 qui justifie ce module — fenêtres de temps appariées (195,9 min de carnets
contre 194,5 min de fills, 171 713 lignes de carnet sur 180 coins) : **10 470 fills sur 10 470**
ont un carnet du même coin reçu STRICTEMENT avant le signal et à moins de 30 s, âge médian
6 637 ms, p90 11 329 ms. (Une première sonde annonçait 34 % : elle comparait 40 Mo de carnets à
8 Mo de fills, donc des fenêtres de temps différentes. La sonde était fausse, pas la donnée.)

CE QUE CE MODULE GARANTIT :
* **strictement avant** : une égalité exacte à la milliseconde est REFUSÉE. Dans la même
  milliseconde l'ordre réel est inconnu, et l'inconnu ferme la porte. C'était une question ouverte
  du journal d'audit ; elle est tranchée ici, et testée ;
* la liaison porte de quoi être **revérifiée** : source, offset, SHA-256 de la ligne exacte,
  `connection_id`, `l2_gap_epoch`, horloge de réception ;
* elle ne prouve rien par elle-même : si le ruban a tourné et que l'octet n'est plus vérifiable,
  le statut est `UNVERIFIABLE` et la ligne reste exploratoire.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable, Mapping
from typing import Any

from hl_observer.ops.echec_silencieux import noter as _noter_echec

#: Schéma de la liaison écrite dans la ligne `REFERENCE`.
SCHEMA_LIAISON = "hypersmart.copy_vault_reference_binding.v1"

#: Âge maximal toléré entre la réception du carnet et celle du signal. 30 s est la borne déjà
#: utilisée par le compagnon (`MAX_TARGET_LAG_MS`) : on ne l'élargit pas pour sauver un signal.
AGE_MAX_MS = 30_000

#: Statuts de vérification au chargement.
VERIFIEE = "VERIFIED"
INVERIFIABLE = "UNVERIFIABLE"
DIVERGENTE = "MISMATCH"


def _fini(valeur: Any) -> float | None:
    """Un prix fini et strictement positif, ou ``None``. Ni NaN, ni inf, ni zéro."""
    try:
        x = float(valeur)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(x) or x <= 0.0:
        return None
    return x


def _entier(valeur: Any) -> int | None:
    if type(valeur) is not int or isinstance(valeur, bool):
        return None
    return valeur


def empreinte(ligne: bytes) -> str:
    """SHA-256 des octets EXACTS de la ligne, saut de ligne exclu."""
    return hashlib.sha256(bytes(ligne).rstrip(b"\r\n")).hexdigest()


def liaison_depuis_ligne(ligne: bytes, *, source: str, offset: int) -> dict[str, Any] | None:
    """La liaison décrivant ce carnet WS, ou ``None`` si la ligne ne porte pas les preuves requises.

    Exiger `connection_id` et `l2_gap_epoch` n'est pas cosmétique : sans identité de connexion on
    ne peut pas dire de quel flux vient le carnet, et c'est précisément le motif des 14 878 refus
    « identité de connexion L2 incomplète » du rapport du 12 novembre.
    """
    try:
        brut = json.loads(bytes(ligne).decode("utf-8"))
    except (UnicodeDecodeError, ValueError, TypeError):
        return None
    if not isinstance(brut, Mapping):
        return None
    recu = _entier(brut.get("received_at_ms"))
    bid, ask = _fini(brut.get("bid")), _fini(brut.get("ask"))
    coin = brut.get("coin")
    connexion = brut.get("connection_id")
    epoque = _entier(brut.get("l2_gap_epoch"))
    position = _entier(offset)
    # `exchange_ts_ms` est EXIGE ici, et non toleré : le chargeur de carnets impose
    # `received >= exchange_ts > 0` et `received - exchange_ts <= 30 s`. Une liaison qui ne porte
    # pas cette horloge serait acceptée par l'écrivain puis rejetée silencieusement au chargement
    # — on ferme donc à la source, là où le motif est encore lisible.
    echange = _entier(brut.get("exchange_ts_ms"))
    if recu is None or recu <= 0 or bid is None or ask is None or ask < bid:
        return None
    if echange is None or echange <= 0 or recu < echange or recu - echange > AGE_MAX_MS:
        return None
    if not isinstance(coin, str) or not coin.strip():
        return None
    if not isinstance(connexion, str) or not connexion.strip():
        return None
    if epoque is None or position is None or position < 0:
        return None
    return {
        "schema_version": SCHEMA_LIAISON,
        "coin": coin,
        "observed_received_at_ms": recu,
        "observed_exchange_ts_ms": echange,
        "bid": bid,
        "ask": ask,
        "capacity_usd": _fini(brut.get("capacity_usd")) or 0.0,
        "bids5": brut.get("bids5"),
        "asks5": brut.get("asks5"),
        "connection_id": connexion,
        "l2_gap_epoch": epoque,
        "source_relpath": str(source),
        "source_offset": position,
        "line_sha256": empreinte(ligne),
        "data_origin": "REAL_OBSERVED",
        "paper_read_only": True,
        "real_execution": False,
    }


def eligible(liaison: Mapping[str, Any] | None, *, signal_received_ms: Any,
             age_max_ms: int = AGE_MAX_MS) -> tuple[bool, str]:
    """``(eligible, raison)`` — ce carnet peut-il servir de référence à ce signal ?

    ÉGALITÉ À LA MILLISECONDE : refusée. Deux événements de la même milliseconde n'ont pas d'ordre
    observable ; accepter reviendrait à supposer que le carnet est arrivé le premier.
    """
    if not isinstance(liaison, Mapping):
        return False, "NO_PRESIGNAL_BOOK"
    if liaison.get("schema_version") != SCHEMA_LIAISON:
        return False, "BINDING_SCHEMA_MISMATCH"
    observe = _entier(liaison.get("observed_received_at_ms"))
    signal = _entier(signal_received_ms)
    if observe is None or signal is None:
        return False, "RECEIVE_CLOCK_MISSING"
    if observe >= signal:
        return False, "BOOK_NOT_RECEIVED_BEFORE_SIGNAL"
    age = signal - observe
    if age > max(0, int(age_max_ms)):
        return False, "PRESIGNAL_BOOK_TOO_OLD"
    return True, "OK"


def age_ms(liaison: Mapping[str, Any], *, signal_received_ms: int) -> int | None:
    observe = _entier(liaison.get("observed_received_at_ms"))
    signal = _entier(signal_received_ms)
    if observe is None or signal is None:
        return None
    return signal - observe


def verifier_liaison(liaison: Mapping[str, Any] | None,
                     *, lire: Callable[[str, int], bytes | None]) -> tuple[str, str]:
    """``(statut, raison)`` au CHARGEMENT : les octets liés existent-ils encore, identiques ?

    ``lire(source_relpath, offset)`` rend la ligne à cet offset, ou ``None`` si elle n'est plus
    atteignable (ruban tourné, archivé, tronqué). Dans ce cas on ne crie pas au faux : on dit
    `UNVERIFIABLE`, et l'appelant sait que cette ligne ne peut pas servir de preuve.
    """
    if not isinstance(liaison, Mapping) or liaison.get("schema_version") != SCHEMA_LIAISON:
        return INVERIFIABLE, "BINDING_ABSENT_OR_UNKNOWN_SCHEMA"
    attendu = liaison.get("line_sha256")
    source = liaison.get("source_relpath")
    offset = _entier(liaison.get("source_offset"))
    if not isinstance(attendu, str) or len(attendu) != 64 or not isinstance(source, str) or offset is None:
        return INVERIFIABLE, "BINDING_INCOMPLETE"
    try:
        octets = lire(source, offset)
    except Exception:                      # noqa: BLE001 — une lecture en panne n'est pas une preuve
        return INVERIFIABLE, "SOURCE_UNREADABLE"
    if octets and empreinte(octets) == attendu:
        return VERIFIEE, "OK"
    # 22/11/2026 — LE RUBAN A ÉTÉ ARCHIVÉ, PAS FALSIFIÉ. À chaque arrêt, `runtime/data` est DÉPLACÉ
    # tel quel dans `runtime/archive/<session>/` ; la session suivante réécrit un ruban neuf au même
    # chemin. Mesuré : 5 241 références sur 5 241 au coffre étaient `SOURCE_LINE_ABSENT`, et une
    # nouvelle session les aurait déclarées DIVERGENTES (« preuve fausse », ligne rejetée) en
    # relisant d'autres octets à la même position. La ligne exacte existe toujours dans l'archive,
    # à la même position : on la cherche là, avec la MÊME exigence d'empreinte SHA-256.
    alternatives = getattr(lire, "alternatives", None)
    archives_vues = False
    if callable(alternatives):
        try:
            for candidat in alternatives(source, offset):
                archives_vues = True
                if candidat and empreinte(candidat) == attendu:
                    return VERIFIEE, "OK_ARCHIVE"
        except Exception:                  # noqa: BLE001
            return INVERIFIABLE, "SOURCE_UNREADABLE"
    if not octets:
        return INVERIFIABLE, "SOURCE_LINE_ABSENT"
    if archives_vues:
        # le chemin a déjà été réécrit par une autre session : un octet différent n'y prouve rien
        return INVERIFIABLE, "LINE_NOT_FOUND_AFTER_ROTATION"
    return DIVERGENTE, "LINE_SHA256_MISMATCH"


class LecteurBorne:
    """Relit la ligne d'un ruban à un offset donné — sans jamais sortir de la racine.

    Sert à REVÉRIFIER un lien de référence : l'écrivain a noté la source, l'offset et le SHA-256
    de la ligne exacte ; le chargeur relit ces octets ici. Un chemin qui sort de la racine rend
    ``None`` (aucune lecture hors coffre), un fichier introuvable aussi — et n'est essayé qu'une
    fois. Les descripteurs sont gardés ouverts le temps du chargement, puis fermés par
    ``fermer()``.
    """

    def __init__(self, racine: Any) -> None:
        self._racine = racine
        self._descripteurs: dict[str, Any] = {}

    def __call__(self, relpath: str, offset: int) -> bytes | None:
        chemin = (self._racine / relpath).resolve()
        try:
            chemin.relative_to(self._racine)
        except ValueError:
            return None
        handle = self._descripteurs.get(relpath)
        if handle is None:
            if relpath in self._descripteurs:
                return None
            try:
                handle = chemin.open("rb")
            except OSError:
                self._descripteurs[relpath] = None
                return None
            self._descripteurs[relpath] = handle
        try:
            handle.seek(int(offset))
            return handle.readline()
        except (OSError, ValueError, OverflowError):
            return None

    def alternatives(self, relpath: str, offset: int):
        """La même ligne dans les sessions ARCHIVÉES (`runtime/data/X` -> `runtime/archive/*/X`)."""
        relatif = str(relpath).replace(chr(92), "/")
        if not relatif.startswith("runtime/data/"):
            return
        nom = relatif[len("runtime/data/"):]
        base = self._racine / "runtime" / "archive"
        try:
            sessions = sorted(d.name for d in base.iterdir() if d.is_dir())
        except OSError:
            return
        for session in sessions:
            octets = self(f"runtime/archive/{session}/{nom}", offset)
            if octets:
                yield octets

    def fermer(self) -> None:
        for handle in self._descripteurs.values():
            if handle is not None:
                try:
                    handle.close()
                except OSError as exc:
                    _noter_echec("collection/copy_vault_reference_binding.py:fermer_lecteur", exc)
        self._descripteurs.clear()


__all__ = [
    "SCHEMA_LIAISON", "AGE_MAX_MS", "VERIFIEE", "INVERIFIABLE", "DIVERGENTE",
    "empreinte", "liaison_depuis_ligne", "eligible", "age_ms", "verifier_liaison",
    "LecteurBorne",
]
