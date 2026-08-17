"""Preuves complementaires AUD-221 -> AUD-260.

Ce module ne remplace pas les moteurs existants. Il ferme les trous de preuve
restants autour de l'orchestration officielle, de la causalite et des tests E2E.
Tout est local/read-only/paper-only.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from hl_observer.hyperliquid.pagination_completeness import evaluer_completude


def audit_point_entree_officiel(cmd_text: str) -> dict[str, Any]:
    """AUD-221/222/223/226: le profil FULL officiel doit lancer la suite etendue."""
    low = cmd_text.lower()
    has_master = "hl_observer.ops.lab_alpha" in low
    has_extended = "hl_observer.ops.historical_analysis_suite" in low
    marker_full = ':mode_full' in low
    full_chunk = low.split(':mode_full', 1)[1].split(':mode_deep', 1)[0] if marker_full and ':mode_deep' in low else ''
    full_extended = 'set "run_extended_suite=1"' in full_chunk
    safe = all(bad not in low for bad in ('private_key=', 'place_order(', 'market_order('))
    return {
        "orchestrateur_canonique": has_master,
        "suite_historique": has_extended,
        "full_etendu": full_extended,
        "quick_seul_court": 'set "run_extended_suite=0"' in low.split(':mode_quick', 1)[1].split(':mode_full', 1)[0] if ':mode_quick' in low else False,
        "paper_safe_surface": safe,
        "ok": has_master and has_extended and full_extended and safe,
    }


def fingerprint_flux_complet(events: Sequence[Mapping[str, Any]]) -> str:
    """AUD-228: hash de TOUT le flux et de ses champs economiques, jamais une fenetre de 64."""
    h = hashlib.sha256()
    h.update(str(len(events)).encode('ascii'))
    for index, ev in enumerate(events):
        canonical = json.dumps(dict(ev), sort_keys=True, separators=(',', ':'), ensure_ascii=False, default=str)
        h.update(f"{index}|{canonical}\n".encode('utf-8'))
    return h.hexdigest()


def purger_intervalles_labels(train: Sequence[tuple[int, int, Any]], test: Sequence[tuple[int, int, Any]], *, embargo_ms: int = 0) -> list[tuple[int, int, Any]]:
    """AUD-230: retire du train tout label dont l'intervalle chevauche test+embargo."""
    out: list[tuple[int, int, Any]] = []
    test_intervals = [(int(a) - embargo_ms, int(b) + embargo_ms) for a, b, _ in test]
    for a, b, payload in train:
        a, b = int(a), int(b)
        overlap = any(not (b < ta or a > tb) for ta, tb in test_intervals)
        if not overlap:
            out.append((a, b, payload))
    return out


def construire_placebos_causaux(events: Sequence[Mapping[str, Any]], *, shift: int = 1) -> dict[str, list[dict[str, Any]]]:
    """AUD-237: plusieurs placebos; jamais seulement l'inversion du signe IS."""
    src = [dict(e) for e in events]
    direction = [{**e, 'signe': -(e.get('signe') or 0)} for e in src]
    if not src:
        shifted: list[dict[str, Any]] = []
    else:
        k = int(shift) % len(src)
        signs = [e.get('signe') for e in src]
        rotated = signs[k:] + signs[:k]
        shifted = [{**e, 'signe': rotated[i]} for i, e in enumerate(src)]
    return {'direction_opposed': direction, 'time_shifted': shifted}


def verifier_equity_leader_vault(*, leader_equity: float | None, vault_equity: float | None) -> dict[str, Any]:
    """AUD-240: aucune equity leader/vault fictive; absence => UNMEASURABLE."""
    missing = []
    if leader_equity is None:
        missing.append('leader_equity')
    if vault_equity is None:
        missing.append('vault_equity')
    values = [leader_equity, vault_equity]
    invalid = any(v is not None and float(v) <= 0 for v in values)
    ok = not missing and not invalid
    return {'ok': ok, 'measurable': ok, 'missing': missing, 'reason': None if ok else ('INVALID_EQUITY' if invalid else 'UNMEASURABLE_EQUITY')}


def paginer_fills_e2e(fetch_page: Callable[[int, int], Sequence[Mapping[str, Any]]], *, start_ms: int, page_limit: int = 500, max_pages: int = 100) -> dict[str, Any]:
    """AUD-241: pagination E2E avec cursor timestamp+1, dedup et completude explicite."""
    cursor = int(start_ms)
    seen: set[str] = set()
    fills: list[dict[str, Any]] = []
    stopped = 'max_pages_reached'
    for _page in range(max_pages):
        rows = [dict(r) for r in fetch_page(cursor, page_limit)]
        if not rows:
            stopped = 'empty_response'
            break
        last_ts = cursor - 1
        for row in rows:
            ts = int(row.get('time', row.get('ts_ms', -1)))
            key = str(row.get('tid') or row.get('oid') or hashlib.sha256(json.dumps(row, sort_keys=True, default=str).encode()).hexdigest())
            if key not in seen:
                seen.add(key)
                fills.append(row)
            last_ts = max(last_ts, ts)
        if last_ts < cursor:
            stopped = 'timestamp_not_progressing'
            break
        cursor = last_ts + 1
        if len(rows) < page_limit:
            stopped = 'completed'
            break
    completeness = evaluer_completude(stopped)
    return {'fills': fills, 'cursor_ms': cursor, 'stopped_reason': stopped, **completeness}


def resoudre_role_adresse(metadata: Mapping[str, Any]) -> dict[str, Any]:
    """AUD-242: agent/master/subaccount explicite; ambiguite => UNKNOWN/fail-closed."""
    role = str(metadata.get('role') or '').upper()
    allowed = {'MASTER', 'AGENT', 'SUBACCOUNT'}
    if role not in allowed:
        return {'role': 'UNKNOWN', 'ok': False, 'reason': 'ADDRESS_ROLE_UNRESOLVED'}
    master = metadata.get('master_address')
    if role in {'AGENT', 'SUBACCOUNT'} and not master:
        return {'role': role, 'ok': False, 'reason': 'MASTER_ADDRESS_MISSING'}
    return {'role': role, 'ok': True, 'master_address': master}


def reconcilier_apres_reconnect(before_ids: Sequence[str], snapshot_ids: Sequence[str], delta_ids: Sequence[str]) -> dict[str, Any]:
    """AUD-243: snapshot de reconnect + delta; aucun doublon, aucun event silencieusement perdu."""
    before = set(map(str, before_ids))
    snap = set(map(str, snapshot_ids))
    delta = set(map(str, delta_ids))
    merged = before | snap | delta
    nouveaux = sorted((snap | delta) - before)
    duplicate_count = len(before_ids) + len(snapshot_ids) + len(delta_ids) - len(merged)
    return {'ids': sorted(merged), 'nouveaux': nouveaux, 'duplicate_count': duplicate_count, 'reconcilie': True}


def compter_essais_effectifs(dimensions: Mapping[str, Sequence[Any]], *, generated_candidates: int = 0) -> dict[str, int]:
    """AUD-255: le budget de multiple-testing inclut aussi les idees generees."""
    total = 1
    for values in dimensions.values():
        total *= max(1, len(list(values)))
    generated = max(0, int(generated_candidates))
    return {'grid_trials': total, 'generated_trials': generated, 'effective_trials': total + generated}


__all__ = ['audit_point_entree_officiel', 'fingerprint_flux_complet', 'purger_intervalles_labels', 'construire_placebos_causaux', 'verifier_equity_leader_vault', 'paginer_fills_e2e', 'resoudre_role_adresse', 'reconcilier_apres_reconnect', 'compter_essais_effectifs']
