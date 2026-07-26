"""INGESTION INCRÉMENTALE (LABO-CONTINU-FINAL FINAL-1/2, Flo 26/07). Un curseur PRÉCIS par source : on ne
relit JAMAIS aveuglément tout l'historique au cycle suivant — seulement les événements arrivés DEPUIS le
curseur (offset octet + dernière ligne complète). Détecte rotation/troncature/remplacement (taille qui
diminue ou sha du préfixe qui change) et repart proprement.

Chaque cycle distingue : new_events (depuis le curseur), historical_context (accès indexé aux anciennes
données), affected_windows (fenêtres/horizons réellement impactés). 0 réseau, 0 écriture sur les originaux.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

CURSORS_REL = "cursors.json"
EXTS_STREAM = (".jsonl",)                 # formats lus incrémentalement par offset (les autres : par identité)


def _charger(rundir: Path) -> dict:
    try:
        return json.loads((Path(rundir) / CURSORS_REL).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _sauver(rundir: Path, cur: dict) -> None:
    p = Path(rundir) / CURSORS_REL
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(cur, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, p)


def _prefix_sha(p: Path, n: int) -> str:
    """SHA des `n` PREMIERS octets (région déjà consommée). n<=0 -> vide (rien à comparer)."""
    if n <= 0:
        return ""
    with Path(p).open("rb") as f:
        return hashlib.sha256(f.read(n)).hexdigest()[:16]


def _region_consommee(offset: int, plafond: int = 65536) -> int:
    return min(int(offset), plafond)


def nouveaux_evenements(root: Path, rundir: Path, chemin: Path, *, max_events: int = 100_000) -> tuple[list[dict], dict]:
    """Lit UNIQUEMENT les lignes JSONL arrivées depuis le dernier offset pour `chemin`. Rend (new_events,
    info_curseur). Détecte rotation/troncature/remplacement en comparant le SHA de la région DÉJÀ CONSOMMÉE
    (min(offset, 64 Ko)) : un simple append (au-delà de l'offset) ne déclenche PAS de fausse rotation."""
    chemin = Path(chemin)
    cle = str(chemin.resolve())
    cur = _charger(rundir)
    prev = cur.get(cle, {})
    try:
        taille = chemin.stat().st_size
    except OSError:
        return [], {"erreur": "STAT"}
    offset = int(prev.get("offset", 0))
    rotation = False
    # SHA de la région déjà consommée telle qu'elle est MAINTENANT : si elle a changé -> remplacement
    pref_region_now = _prefix_sha(chemin, _region_consommee(offset))
    if taille < offset or (prev.get("prefix_sha") and offset > 0 and prev.get("prefix_sha") != pref_region_now):
        offset = 0                          # rotation/troncature/remplacement -> on repart du début
        rotation = True
    news, dernier_ex_ts, dernier_id = [], prev.get("dernier_exchange_ts"), prev.get("dernier_event_id")
    n = 0
    with chemin.open("rb") as f:
        f.seek(offset)
        for raw in f:
            if not raw.endswith(b"\n"):     # dernière ligne incomplète (troncature en cours) -> ne pas consommer
                break
            offset += len(raw)
            s = raw.decode("utf-8", "ignore").strip()
            if not s:
                continue
            try:
                d = json.loads(s)
            except ValueError:
                continue
            if isinstance(d, dict):
                news.append(d)
                dernier_ex_ts = d.get("exchange_ts") or d.get("ts_ex") or dernier_ex_ts
                dernier_id = d.get("tid") or d.get("event_id") or d.get("sequence") or dernier_id
                n += 1
                if n >= max_events:
                    break
    info = {"chemin": cle, "offset": offset, "taille": taille,
            "prefix_sha": _prefix_sha(chemin, _region_consommee(offset)),   # SHA de la NOUVELLE région consommée
            "dernier_exchange_ts": dernier_ex_ts, "dernier_event_id": dernier_id, "rotation": rotation,
            "n_nouveaux": len(news)}
    cur = _charger(rundir)                   # relire AVANT d'écrire (ne pas clobbérer d'autres sources)
    cur[cle] = info
    _sauver(rundir, cur)
    return news, info


def scanner_nouveautes(root: Path, rundir: Path, *, dossiers=("runtime/data",), max_events_par_source: int = 100_000) -> dict:
    """Parcourt les sources JSONL et n'extrait que les NOUVEAUX événements par source (offsets). Rend
    {new_events, par_source, n_new, sources_avec_nouveaute}. Les non-JSONL sont suivis par identité (sha/taille)."""
    import catalogue_archives_18h as CAT
    root = Path(root)
    new_events, par_source, avec = [], {}, 0
    snap = _charger(rundir)                   # snapshot pour LIRE les sig d'identité précédents
    ident_updates = {}
    for dd in dossiers:
        base = root / dd
        if not base.exists():
            continue
        for p in sorted(base.rglob("*")):
            if not p.is_file() or "continuous" in p.parts or any("overnight" in x for x in p.parts):
                continue
            if p.suffix.lower() in EXTS_STREAM:
                news, info = nouveaux_evenements(root, rundir, p, max_events=max_events_par_source)
                if news:
                    avec += 1
                    for d in news:
                        new_events.append({**d, "_source": str(p.relative_to(root))})
                    par_source[str(p.relative_to(root))] = info["n_nouveaux"]
            elif p.suffix.lower() in CAT.EXTS:
                # non-JSONL : suivi par identité (sha des 64 premiers Ko + taille) — nouveauté = identité changée
                cle = str(p.resolve())
                try:
                    sig = "%d:%s" % (p.stat().st_size, _prefix_sha(p, 65536))
                except OSError:
                    continue
                if snap.get(cle, {}).get("sig") != sig:
                    avec += 1
                    par_source[str(p.relative_to(root))] = "IDENTITE_CHANGEE"
                    ident_updates[cle] = {"sig": sig}
    if ident_updates:                         # relire APRÈS les offsets jsonl, fusionner l'identité, sauver
        cur = _charger(rundir)
        cur.update(ident_updates)
        _sauver(rundir, cur)
    return {"new_events": new_events, "par_source": par_source, "n_new": len(new_events),
            "sources_avec_nouveaute": avec}


def fenetres_impactees(new_events: list[dict], horizons_ms) -> dict:
    """affected_windows : coins × horizons réellement touchés par les nouveaux événements (on ne recalcule
    pas ce qui n'a pas bougé)."""
    coins = sorted({str(d.get("coin") or d.get("symbol") or "").upper() for d in new_events if d.get("coin") or d.get("symbol")})
    return {"coins": [c for c in coins if c], "horizons_ms": list(horizons_ms), "n_events": len(new_events)}


__all__ = ["nouveaux_evenements", "scanner_nouveautes", "fenetres_impactees", "CURSORS_REL"]
