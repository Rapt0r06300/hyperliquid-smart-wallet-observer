"""[LAB α item 11/5] INGESTION EN STREAMING À MÉMOIRE BORNÉE — supprime le plafond arbitraire de 200 000
événements SANS risque d'OOM.

Au lieu de charger tous les bundles/événements en RAM puis de couper à 200k, on lit les fichiers LIGNE
PAR LIGNE, on convertit chaque bundle en événements et on les DÉVERSE (spill) au fil de l'eau dans un
shard JSONL sur DISQUE. La RAM ne tient jamais plus d'un bundle à la fois. Un CHECKPOINT permet la
REPRISE (un shard déjà complet n'est pas recalculé). Le replay charge ensuite une FENÊTRE bornée du shard
(budget mémoire EXPLICITE, jamais un nombre magique).

`max_events <= 0` = pas de plafond arbitraire (lit tout, mémoire bornée par le streaming).
Réutilise les briques canoniques (lab_inventaire.lire_lignes/_row_to_bundle, feed_adapter). 0 réseau.
"""
from __future__ import annotations

import heapq
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Iterable, Iterator

from hl_observer.mega_cablage.feed_adapter import evenements_depuis_bundles
from hl_observer.ops.lab_inventaire import lire_lignes, _row_to_bundle, LabFormatBloque

# item 9 — ordre CAUSAL global : exchange_ts -> recv_ts -> sequence -> source. Un timestamp absent trie
# APRÈS les présents (jamais devant), de façon déterministe. Sans cet ordre, Lead-Lag et Cross-Venue sont
# FAUX : on ne peut pas mesurer que Binance bouge avant Hyperliquid si les événements sont concaténés
# fichier par fichier au lieu d'être entrelacés dans le temps.
_INF = float("inf")


def cle_causale(ev: Any) -> tuple:
    """Clé d'ordre causal d'un événement (dict ou objet canonique). Champs manquants -> +inf (fin).
    Le temps primaire est l'horodatage d'exchange : `exchange_ts_ms` (canonique) OU `ts_ms` (feed lab),
    puis recv_ts, puis sequence, puis source (venue) — pour départager de façon DÉTERMINISTE."""
    def _lire(nom, *alias):
        if isinstance(ev, dict):
            for k in (nom, *alias):
                if ev.get(k) is not None:
                    return ev.get(k)
            return None
        for k in (nom, *alias):
            v = getattr(ev, k, None)
            if v is not None:
                return v
        return None
    ex = _lire("exchange_ts_ms", "exchange_ts", "ts_ms")
    rc = _lire("recv_ts_ms", "reception_ts_ms", "recv_ts")
    sq = _lire("sequence")
    src = _lire("source", "venue") or ""
    return (float(ex) if ex is not None else _INF,
            float(rc) if rc is not None else _INF,
            float(sq) if sq is not None else _INF,
            str(src))


def flux_evenements_stream(fichiers: Iterable[str | Path], *, max_events: int = 0) -> Iterator[dict[str, Any]]:
    """Générateur BORNÉ : pour chaque fichier, lit ligne par ligne, convertit CHAQUE bundle en événements
    et les yield un par un. Ne matérialise JAMAIS un dataset entier. `max_events<=0` = illimité (le
    streaming garde la mémoire bornée). Un fichier au format bloqué est sauté (compté par l'appelant)."""
    n = 0
    for f in fichiers:
        try:
            lignes = lire_lignes(f)
        except (OSError, LabFormatBloque):
            continue
        for row in lignes:
            try:
                bundle = _row_to_bundle(row)
                evs = evenements_depuis_bundles([bundle])
            except Exception:  # noqa: BLE001 — ligne défaillante = sautée, jamais fabriquée
                continue
            for ev in evs:
                yield ev
                n += 1
                if max_events > 0 and n >= max_events:
                    return


def materialiser_shard(fichiers: Iterable[str | Path], shard_path: str | Path, *, max_events: int = 0,
                       checkpoint_path: str | Path | None = None) -> dict[str, Any]:
    """Déverse le flux d'événements dans un shard JSONL sur DISQUE (un événement à la fois → RAM bornée).
    Écrit un checkpoint {n, complet}. REPRISE : si le shard existe et le checkpoint dit `complet`, on ne
    recalcule pas. Rend {n, shard, repris}."""
    shard_path = Path(shard_path)
    shard_path.parent.mkdir(parents=True, exist_ok=True)
    cp = Path(checkpoint_path) if checkpoint_path else None
    if cp and cp.is_file() and shard_path.is_file():
        try:
            etat = json.loads(cp.read_text(encoding="utf-8"))
            if etat.get("complet"):
                return {"n": int(etat.get("n") or 0), "shard": str(shard_path), "repris": True}
        except (OSError, ValueError):
            pass
    n = 0
    tmp = shard_path.with_name(".%s.%d.tmp" % (shard_path.name, os.getpid()))
    with tmp.open("w", encoding="utf-8") as fh:
        for ev in flux_evenements_stream(fichiers, max_events=max_events):
            fh.write(json.dumps(ev, ensure_ascii=False) + "\n")
            n += 1
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, shard_path)
    if cp:
        cp.write_text(json.dumps({"n": n, "complet": True}), encoding="utf-8")
    return {"n": n, "shard": str(shard_path), "repris": False}


def flux_depuis_shard(shard_path: str | Path) -> Iterator[dict[str, Any]]:
    """Relit le shard en streaming (une ligne à la fois → RAM bornée)."""
    p = Path(shard_path)
    if not p.is_file():
        return
    with p.open("r", encoding="utf-8") as fh:
        for ligne in fh:
            ligne = ligne.strip()
            if not ligne:
                continue
            try:
                yield json.loads(ligne)
            except ValueError:
                continue


def compter_shard(shard_path: str | Path) -> int:
    return sum(1 for _ in flux_depuis_shard(shard_path))


def _sha_taille(chemin: str | Path) -> tuple[str, int]:
    from hl_observer.ops.session_catalog import sha256_fichier
    p = Path(chemin)
    return sha256_fichier(p) if p.is_file() else ("", -1)


def charger_borne(shard_path: str | Path, *, max_ram: int = 0) -> list[dict[str, Any]]:
    """Charge une FENÊTRE bornée du shard (budget mémoire EXPLICITE). `max_ram<=0` = tout le shard. Le
    replay in-memory travaille sur cette fenêtre — jamais un plafond arbitraire codé en dur."""
    out: list[dict[str, Any]] = []
    for i, ev in enumerate(flux_depuis_shard(shard_path)):
        if max_ram > 0 and i >= max_ram:
            break
        out.append(ev)
    return out


# ── item 7 : EMPREINTE DE CACHE (le checkpoint ne se croit JAMAIS valide sans preuve) ─────────────
def empreinte_sources(fichiers: Iterable[str | Path], *, parser_version: str = "",
                      git_sha: str = "") -> dict[str, Any]:
    """Empreinte COMPLÈTE des sources : chemin relatif + SHA-256 + taille de CHAQUE fichier, + version
    de parser + SHA git. Deux jeux de sources identiques -> même empreinte ; le moindre octet changé, un
    fichier ajouté/retiré, un parser ou un commit différent -> empreinte différente -> reconstruction."""
    import hashlib
    from hl_observer.ops.session_catalog import sha256_fichier
    entrees = []
    for f in sorted(str(x) for x in fichiers):
        p = Path(f)
        if p.is_file():
            sha, taille = sha256_fichier(p)
        else:
            sha, taille = "", -1
        entrees.append({"rel": p.name, "sha256": sha, "taille": taille})
    materiau = json.dumps({"sources": entrees, "parser_version": parser_version,
                           "git_sha": git_sha}, sort_keys=True, ensure_ascii=False)
    return {"sources": entrees, "parser_version": parser_version, "git_sha": git_sha,
            "empreinte": hashlib.sha256(materiau.encode("utf-8")).hexdigest()}


# ── item 9 : FUSION CAUSALE GLOBALE par TRI-FUSION EXTERNE (jamais une concaténation naïve) ────────
def _ecrire_runs_tries(evs: Iterator[dict[str, Any]], dossier: Path, prefixe: str,
                       max_ram_tri: int) -> list[Path]:
    """Découpe un flux en RUNS triés sur DISQUE (tri-fusion externe) : on charge au plus `max_ram_tri`
    événements, on les TRIE par clé causale, on les déverse ; on répète. RAM bornée par max_ram_tri."""
    runs: list[Path] = []
    buf: list[dict[str, Any]] = []

    def _spill(chunk: list[dict[str, Any]]) -> None:
        chunk.sort(key=cle_causale)
        p = dossier / ("%s.run%03d.jsonl" % (prefixe, len(runs)))
        with p.open("w", encoding="utf-8") as fh:
            for ev in chunk:
                fh.write(json.dumps(ev, ensure_ascii=False) + "\n")
        runs.append(p)

    for ev in evs:
        buf.append(ev)
        if len(buf) >= max_ram_tri > 0:
            _spill(buf)
            buf = []
    if buf:
        _spill(buf)
    return runs


def _flux_tagge(fichier: Path, source: str) -> Iterator[dict[str, Any]]:
    """Étiquette chaque événement d'un fichier avec sa SOURCE (venue). Essentiel pour Cross-Venue /
    Lead-Lag : après la fusion, on doit toujours savoir de quelle venue vient chaque événement, même si
    le feed_adapter a laissé tomber le champ venue. On n'écrase JAMAIS une source déjà présente."""
    for ev in flux_evenements_stream([fichier]):
        if isinstance(ev, dict) and not (ev.get("source") or ev.get("venue")):
            ev = {**ev, "source": source}
        yield ev


def fusionner_causalement(fichiers: Iterable[str | Path], sortie: str | Path, *,
                          max_ram_tri: int = 50_000, checkpoint_path: str | Path | None = None,
                          source_de=None, parser_version: str = "", git_sha: str = "") -> dict[str, Any]:
    """Produit un shard GLOBAL trié causalement (exchange_ts→recv_ts→sequence→source) à partir de
    plusieurs artefacts par-source, par TRI-FUSION EXTERNE : (1) chaque source est découpée en runs
    triés sur disque (RAM bornée), (2) tous les runs sont k-way-mergés par clé causale (heapq.merge,
    un événement par run en RAM), (3) dédoublonnage CROISÉ des event_id adjacents (reconnexions /
    chevauchements de snapshot produisent le MÊME event_id à la MÊME clé → adjacents après tri).
    Chaque événement est étiqueté de sa SOURCE (venue) — `source_de(fichier)` si fourni, sinon le nom
    de fichier — pour que Cross-Venue/Lead-Lag sachent toujours d'où vient chaque tick.
    Compte hors_ordre (toujours 0 après tri : preuve que l'ordre est causal), gaps de séquence par
    source, et doublons. Rend {n, dedupes, hors_ordre, gaps, sources, runs}. RAM bornée, 0 réseau."""
    sortie = Path(sortie)
    sortie.parent.mkdir(parents=True, exist_ok=True)
    fichiers = [Path(f) for f in fichiers]
    # item 7 : empreinte COMPLÈTE des sources (rel + SHA-256 + taille + parser + git). Le cache n'est
    # réutilisé que si CETTE empreinte correspond ET que le shard existant a le bon hash + le bon nombre
    # de lignes. Toute divergence (source modifiée, ajoutée, retirée, parser/commit différent, shard
    # corrompu) => on RECONSTRUIT. Un checkpoint n'est jamais cru sur parole.
    emp = empreinte_sources(fichiers, parser_version=parser_version, git_sha=git_sha)
    cp = Path(checkpoint_path) if checkpoint_path else None
    if cp and cp.is_file() and sortie.is_file():
        try:
            etat = json.loads(cp.read_text(encoding="utf-8"))
            meme_sources = etat.get("empreinte_sources", {}).get("empreinte") == emp["empreinte"]
            sha_now, taille_now = _sha_taille(sortie)
            shard_intact = (etat.get("shard_sha256") == sha_now
                            and etat.get("lignes") == compter_shard(sortie))
            if etat.get("complet") and meme_sources and shard_intact:
                etat = dict(etat)
                etat["repris"] = True
                return etat
        except (OSError, ValueError):
            pass

    with tempfile.TemporaryDirectory(prefix="fusion_causale_", dir=str(sortie.parent)) as tmpdir:
        tmp = Path(tmpdir)
        runs: list[Path] = []
        for i, f in enumerate(fichiers):
            src = source_de(f) if callable(source_de) else f.stem
            runs.extend(_ecrire_runs_tries(_flux_tagge(f, str(src)), tmp, "src%03d" % i, max_ram_tri))
        # k-way merge : heapq.merge ne garde qu'UN événement par run en RAM (tri-fusion externe).
        iterateurs = [flux_depuis_shard(r) for r in runs]
        fusion = heapq.merge(*iterateurs, key=cle_causale)
        n = dedupes = hors_ordre = 0
        gaps = 0
        derniere_cle = None
        precedent_ident = None
        seq_par_source: dict[str, float] = {}
        tmp_sortie = sortie.with_name(".%s.%d.tmp" % (sortie.name, os.getpid()))
        with tmp_sortie.open("w", encoding="utf-8") as fh:
            for ev in fusion:
                k = cle_causale(ev)
                if derniere_cle is not None and k < derniere_cle:
                    hors_ordre += 1                    # ne doit JAMAIS arriver après tri (preuve d'ordre)
                derniere_cle = k
                # Identité de dédoublonnage : event_id STABLE si présent (deux fois le même id = le même
                # événement, quelle que soit la source) ; sinon le CONTENU exact (une reconnexion qui
                # renvoie le même enregistrement). Une venue différente => contenu différent (source
                # étiquetée) => jamais fusionnée à tort avec une autre venue.
                eid = ev.get("event_id") if isinstance(ev, dict) else getattr(ev, "event_id", None)
                ident = eid if eid is not None else json.dumps(ev, ensure_ascii=False, sort_keys=True)
                if ident == precedent_ident:
                    dedupes += 1                        # doublon adjacent (reconnexion/snapshot) -> écarté
                    continue
                precedent_ident = ident
                # gap de séquence par source (trou dans le flux = perte/reconnexion, compté honnêtement).
                src = (ev.get("source") or ev.get("venue") or "") if isinstance(ev, dict) else ""
                sq = ev.get("sequence") if isinstance(ev, dict) else None
                if isinstance(sq, (int, float)):
                    prev = seq_par_source.get(str(src))
                    if prev is not None and sq > prev + 1:
                        gaps += int(sq - prev - 1)
                    seq_par_source[str(src)] = float(sq)
                fh.write(json.dumps(ev, ensure_ascii=False) + "\n")
                n += 1
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_sortie, sortie)
    shard_sha, _shard_taille = _sha_taille(sortie)
    resultat = {"n": n, "dedupes": dedupes, "hors_ordre": hors_ordre, "gaps": gaps,
                "sources": len(fichiers), "runs": len(runs), "shard": str(sortie), "repris": False}
    if cp:
        # item 7 : le checkpoint contient l'empreinte des sources + le SHA du shard + le nombre EXACT de
        # lignes + la liste des sources -> toute divergence future forcera une reconstruction.
        etat = dict(resultat)
        etat.update({"complet": True, "empreinte_sources": emp, "shard_sha256": shard_sha, "lignes": n})
        cp.write_text(json.dumps(etat, ensure_ascii=False), encoding="utf-8")
    return resultat


def flux_causal(fichiers: Iterable[str | Path], *, max_ram_tri: int = 50_000) -> Iterator[dict[str, Any]]:
    """Confort : fusion causale -> relecture en streaming (RAM bornée). Matérialise un shard temporaire
    trié puis le relit. Pour un usage répété, préférer fusionner_causalement (shard persistant)."""
    with tempfile.TemporaryDirectory(prefix="flux_causal_") as d:
        shard = Path(d) / "global.jsonl"
        fusionner_causalement(fichiers, shard, max_ram_tri=max_ram_tri)
        for ev in flux_depuis_shard(shard):
            yield ev


__all__ = ["cle_causale", "empreinte_sources", "flux_evenements_stream", "materialiser_shard",
           "flux_depuis_shard", "compter_shard", "charger_borne", "fusionner_causalement", "flux_causal"]
