"""Voie PRÉ-SIGNAL du compagnon : lier la référence à un carnet DÉJÀ REÇU avant le signal.

POURQUOI CE MODULE EST À PART (17/11/2026). Ces deux méthodes ont été écrites le 16/11 dans
``copy_vault_checkpoint_tail.py`` pour réparer le bloqueur P0 (une référence demandée APRÈS le
signal, donc reçue 320 à 1 527 ms trop tard et refusée 77 008 fois sur 98 138). Elles l'avaient
fait dépasser son plafond de 800 lignes. Elles forment un tout — avancer sur le ruban WS continu,
puis émettre la ligne ``REFERENCE`` liée — et sont donc extraites ici en classe de base du
compagnon, sans changement de comportement.

Le compagnon fournit l'état que ces méthodes lisent : ``lane_path``, ``output_path``, ``state`` et
``_dernier_carnet``.
"""
from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from hl_observer.backtesting.copy_vault_executable import CHECKPOINT_COLLECTOR_PROTOCOL
from hl_observer.backtesting.copy_vault_protocol import INSTRUMENT_IDENTITY_SCHEMA
from hl_observer.collection import copy_vault_reference_binding as LIAISON
from hl_observer.collection.copy_vault_checkpoint_socle import _append_jsonl, _file_identity
from hl_observer.instrument_identity import preserve_native_instrument_symbol

COMPANION_PROTOCOL = CHECKPOINT_COLLECTOR_PROTOCOL
#: Ruban WS CONTINU des carnets de leaders, écrit par `l2-leaders`. C'est la seule source qui
#: contient des carnets DÉJÀ REÇUS avant un signal ; il porte `connection_id` et `l2_gap_epoch`.
LANE_RELPATH = Path("runtime") / "data" / "copy_vault_l2_lane.jsonl"
#: Carnets retenus par coin. Assez pour couvrir plusieurs lignes arrivées entre deux passes,
#: assez peu pour rester en mémoire bornée (180 coins observés le 16/11).
CARNETS_PAR_COIN = 8


class VoiePreSignal:
    """Les deux gestes de la liaison pré-signal ; hérité par ``CopyVaultCheckpointTail``."""

    lane_path: Path
    output_path: Path
    state: dict[str, Any]
    _dernier_carnet: dict[str, list[dict[str, Any]]]

    def _lire_carnets_du_ruban(self) -> int:
        """Avance sur le ruban WS continu et retient le DERNIER carnet lié par coin.

        On ne relit jamais l'historique : au premier passage, l'offset est calé sur la taille du
        fichier (666 Mo le 16/11). Une rotation du ruban recale l'offset sans rien inventer — on
        perd simplement la mémoire des carnets jusqu'au prochain, ce qui refuse des liaisons au
        lieu d'en fabriquer.
        """
        try:
            stat = self.lane_path.stat()
        except OSError:
            return 0
        identite = _file_identity(stat)
        taille = int(stat.st_size)
        offset = int(self.state.get("lane_offset") or 0)
        precedente = self.state.get("lane_file_identity")
        if precedente is None or precedente != identite or taille < offset:
            # Premier passage ou rotation : on se cale sur la fin. Aucune ligne historique n'entre.
            self.state["lane_offset"] = taille
            self.state["lane_file_identity"] = identite
            self._dernier_carnet.clear()
            return 0
        if taille == offset:
            return 0
        try:
            with self.lane_path.open("rb") as handle:
                handle.seek(offset)
                bloc = handle.read()
        except OSError:
            return 0
        fin = bloc.rfind(b"\n")
        if fin < 0:
            return 0
        consomme = bloc[: fin + 1]
        lues = 0
        position = offset
        for ligne in consomme.splitlines(keepends=True):
            debut = position
            position += len(ligne)
            nue = ligne.strip()
            if not nue:
                continue
            liaison = LIAISON.liaison_depuis_ligne(nue, source=str(LANE_RELPATH.as_posix()),
                                                   offset=debut)
            if liaison is None:
                continue
            coin = preserve_native_instrument_symbol(liaison["coin"])
            file = self._dernier_carnet.setdefault(coin, [])
            file.append(liaison)
            if len(file) > CARNETS_PAR_COIN:
                del file[:-CARNETS_PAR_COIN]
            lues += 1
        self.state["lane_offset"] = offset + len(consomme)
        return lues

    def _emettre_reference_liee(self, base: Mapping[str, Any], *, signal_received_ms: int) -> bool:
        """Écrit la ligne `REFERENCE` depuis un carnet DÉJÀ REÇU avant le signal.

        C'est la réparation du bloqueur P0 : l'ancien chemin programmait une requête REST APRÈS
        avoir lu le fill, donc reçue 320 à 1 527 ms après le signal, donc refusée à juste titre par
        l'exécuteur (77 008 refus sur 98 138 signaux). Ici le carnet a été observé AVANT, et la
        ligne porte de quoi le revérifier : source, offset, SHA-256, connexion, époque de gap.

        Rend ``False`` sans rien écrire si aucun carnet pré-signal n'est éligible. On n'élargit
        aucune fenêtre pour sauver un signal : le refus est compté et nommé.
        """
        coin = preserve_native_instrument_symbol(base["coin"])
        # Le plus RECENT carnet strictement anterieur au signal, et non « le dernier connu » :
        # une ligne de ruban peut arriver entre deux passes et etre posterieure au signal.
        candidats = [c for c in self._dernier_carnet.get(coin, ())
                     if int(c["observed_received_at_ms"]) < int(signal_received_ms)]
        liaison = max(candidats, key=lambda c: int(c["observed_received_at_ms"])) if candidats else None
        eligible, raison = LIAISON.eligible(liaison, signal_received_ms=signal_received_ms)
        if not eligible:
            compteur = {
                "NO_PRESIGNAL_BOOK": "reference_no_presignal_book",
                "BOOK_NOT_RECEIVED_BEFORE_SIGNAL": "reference_no_presignal_book",
                "PRESIGNAL_BOOK_TOO_OLD": "reference_presignal_too_old",
            }.get(raison, "reference_no_presignal_book")
            self.state["counters"][compteur] = int(
                self.state["counters"].get(compteur) or 0) + 1
            return False
        age = LIAISON.age_ms(liaison, signal_received_ms=signal_received_ms)
        row = {
            "schema_version": "hypersmart.copy_vault_l2.v1",
            "instrument_identity_schema": INSTRUMENT_IDENTITY_SCHEMA,
            "coin": coin,
            **{k: base[k] for k in ("vault", "direction", "signal_ts_ms", "signal_event_id",
                                    "signal_action") if k in base},
            # L'horodatage de la ligne est celui de l'observation REELLE du carnet, donc AVANT le
            # signal. C'est le fait que l'executeur doit pouvoir verifier.
            "received_at_ms": int(liaison["observed_received_at_ms"]),
            "exchange_ts_ms": int(liaison["observed_exchange_ts_ms"]),
            "bid": float(liaison["bid"]),
            "ask": float(liaison["ask"]),
            "capacity_usd": float(liaison["capacity_usd"]),
            "source": "HYPERLIQUID_L2_WS",
            "data_origin": "REAL_OBSERVED",
            "causal_observation": True,
            "paper_read_only": True,
            "real_execution": False,
            "checkpoint_stage": "REFERENCE",
            "checkpoint_target_ms": int(signal_received_ms),
            "checkpoint_id": f"{base['metaorder_id']}:REFERENCE",
            "metaorder_id": str(base["metaorder_id"]),
            "collector_protocol": COMPANION_PROTOCOL,
            "writer_run_id": str(self.state["writer_run_id"]),
            "clean_epoch_ms": int(self.state["clean_epoch_ms"]),
            "reference_binding": dict(liaison),
            "presignal_age_ms": int(age if age is not None else 0),
        }
        # Les niveaux ne sont recopies QUE s'ils existent tous les deux : le chargeur valide les
        # deux cotes ensemble (`L2_SIDE_MISSING`) et refuse une cle presente a None.
        if liaison.get("bids5") is not None and liaison.get("asks5") is not None:
            row["bids5"] = liaison["bids5"]
            row["asks5"] = liaison["asks5"]
        _append_jsonl(self.output_path, row)
        self.state["counters"]["reference_bound_presignal"] = int(
            self.state["counters"].get("reference_bound_presignal") or 0) + 1
        self.state["counters"]["checkpoints_captured"] += 1
        return True


__all__ = ["CARNETS_PAR_COIN", "LANE_RELPATH", "VoiePreSignal"]
