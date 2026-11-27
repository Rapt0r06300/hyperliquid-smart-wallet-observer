"""Archive gzip PAR BLOCS, indexée : SANS PERTE, lisible par n'importe quel outil gzip, relue à n'importe quel offset.

Pourquoi pas un simple ``gzip`` : le coffre et le lecteur de preuves (``copy_vault_reference_binding``) relisent une
ligne EXACTE à un offset noté au moment de l'écriture (« runtime/archive/<session>/X », octet N, SHA-256 de la ligne).
Dans un gzip ordinaire, atteindre l'octet N oblige à tout décompresser depuis le début ; sur un ruban de plusieurs
Go relu pour des milliers de preuves, c'est inutilisable. Ici le fichier est une suite de membres gzip indépendants
(le format le permet : ``gzip -d``, ``zcat``, ``gzip.open`` les lisent bout à bout comme un seul flux), chacun
terminé sur une fin de ligne, et un index ``<archive>.idx.json`` dit où commence chaque bloc dans le texte d'origine
et dans le fichier compressé. Relire une ligne coûte UN bloc (~4 Mo), jamais le fichier.

Garanties, vérifiées avant de toucher à la source :
- la décompression complète de l'archive rend EXACTEMENT les octets d'origine (taille et SHA-256 égaux) ;
- la source n'a pas changé pendant la compression (taille et date) ; sinon rien n'est remplacé ;
- l'archive et son index sont écrits sous un nom temporaire puis renommés : jamais d'archive tronquée en place.
Une source n'est retirée que par ``remplacer_par_archive``, après ces vérifications.
"""
from __future__ import annotations

import bisect
import gzip
import hashlib
import json
import os
import time
import zlib
from pathlib import Path
from typing import Any, Callable

SCHEMA_INDEX = "hypersmart.archive_gzip_blocs.v1"
SUFFIXE_INDEX = ".idx.json"
BLOC_DEFAUT = 4 * 1024 * 1024


def chemin_index(archive: Path) -> Path:
    return archive.with_name(archive.name + SUFFIXE_INDEX)


def _remplacer(tmp: Path, cible: Path, essais: int = 8) -> None:
    for i in range(essais):
        try:
            os.replace(tmp, cible)
            return
        except PermissionError:          # Windows : antivirus / indexeur qui tient la cible un instant
            if i == essais - 1:
                raise
            time.sleep(0.25 * (i + 1))


def compresser(source: Path, cible: Path | None = None, *, bloc: int = BLOC_DEFAUT, niveau: int = 6,
               progression: Callable[[str, int, int], None] | None = None) -> dict[str, Any]:
    """Écrit ``source`` en archive par blocs + index, VÉRIFIÉE. Ne touche pas à la source. Rend l'index."""
    source = Path(source)
    cible = Path(cible) if cible is not None else source.with_name(source.name + ".gz")
    if cible.exists():
        raise FileExistsError(f"archive deja presente : {cible}")
    avant = source.stat()
    tmp = cible.with_name(cible.name + ".part")
    h_clair = hashlib.sha256()
    blocs: list[list[int]] = []
    pos = 0
    lus_source = dernier_rapport = 0
    dernier_temps_rapport = time.monotonic()

    def publier(phase: str, faits: int, total: int) -> None:
        if progression is None:
            return
        try:
            progression(phase, faits, total)
        except Exception:  # noqa: BLE001 — la télémétrie ne doit jamais interrompre l'archivage
            pass

    try:
        publier("COMPRESSION_SOURCE", 0, avant.st_size)
        with source.open("rb") as src, tmp.open("wb") as out:
            tampon = bytearray()

            def vider() -> None:
                nonlocal pos
                if not tampon:
                    return
                debut = out.tell()
                out.write(gzip.compress(bytes(tampon), compresslevel=niveau, mtime=0))
                blocs.append([pos, debut, len(tampon)])
                pos += len(tampon)
                tampon.clear()

            for ligne in src:                       # une ligne n'est JAMAIS coupée entre deux blocs
                h_clair.update(ligne)
                tampon += ligne
                lus_source += len(ligne)
                if len(tampon) >= bloc:
                    vider()
                maintenant = time.monotonic()
                if lus_source - dernier_rapport >= 8 * 1024 * 1024 or maintenant - dernier_temps_rapport >= 1.0:
                    publier("COMPRESSION_SOURCE", lus_source, avant.st_size)
                    dernier_rapport, dernier_temps_rapport = lus_source, maintenant
            vider()
            publier("COMPRESSION_SOURCE", lus_source, avant.st_size)
            out.flush()
            os.fsync(out.fileno())
        apres = source.stat()
        if (apres.st_size, apres.st_mtime_ns) != (avant.st_size, avant.st_mtime_ns) or pos != avant.st_size:
            raise RuntimeError(f"source modifiee pendant la compression : {source}")
        h_verif, n = hashlib.sha256(), 0
        dernier_rapport = 0
        dernier_temps_rapport = time.monotonic()
        publier("VERIFICATION_ARCHIVE", 0, pos)
        with gzip.open(tmp, "rb") as g:                # relecture COMPLÈTE par un lecteur gzip standard
            for morceau in iter(lambda: g.read(1 << 20), b""):
                h_verif.update(morceau)
                n += len(morceau)
                maintenant = time.monotonic()
                if n - dernier_rapport >= 8 * 1024 * 1024 or maintenant - dernier_temps_rapport >= 1.0:
                    publier("VERIFICATION_ARCHIVE", n, pos)
                    dernier_rapport, dernier_temps_rapport = n, maintenant
        publier("VERIFICATION_ARCHIVE", n, pos)
        if n != pos or h_verif.hexdigest() != h_clair.hexdigest():
            raise RuntimeError(f"verification de l'archive echouee : {source}")
        index = {"schema": SCHEMA_INDEX, "source": source.name, "taille_clair": pos,
                 "sha256_clair": h_clair.hexdigest(), "octets_archive": tmp.stat().st_size,
                 "bloc_cible": bloc, "niveau": niveau, "blocs": blocs}
        tmp_idx = chemin_index(cible).with_name(chemin_index(cible).name + ".part")
        tmp_idx.write_text(json.dumps(index, separators=(",", ":")), encoding="utf-8")
        _remplacer(tmp_idx, chemin_index(cible))
        _remplacer(tmp, cible)
        return index
    except BaseException:
        if tmp.exists():
            tmp.unlink()
        raise


def remplacer_par_archive(source: Path, *, bloc: int = BLOC_DEFAUT, niveau: int = 6,
                           progression: Callable[[str, int, int], None] | None = None) -> dict[str, Any]:
    """Compresse puis RETIRE la source en clair, seulement si l'archive vérifiée en redonne chaque octet."""
    source = Path(source)
    avant = source.stat()
    index = compresser(source, bloc=bloc, niveau=niveau, progression=progression)
    apres = source.stat()
    if (apres.st_size, apres.st_mtime_ns) != (avant.st_size, avant.st_mtime_ns):
        raise RuntimeError(f"source modifiee apres compression, conservee : {source}")
    source.unlink()
    return index


class LecteurArchive:
    """Relit la ligne qui commence à un offset du texte d'origine, en ne décompressant qu'un bloc."""

    def __init__(self, archive: Path) -> None:
        self.archive = Path(archive)
        idx_path = chemin_index(self.archive)
        self.index = json.loads(idx_path.read_text(encoding="utf-8")) if idx_path.exists() else None
        self._debuts = [b[0] for b in self.index["blocs"]] if self.index else []
        self._handle = None
        self._cache: tuple[int, bytes] | None = None

    def _bloc(self, i: int) -> bytes:
        if self._cache is not None and self._cache[0] == i:
            return self._cache[1]
        blocs = self.index["blocs"]
        fin = blocs[i + 1][1] if i + 1 < len(blocs) else self.index["octets_archive"]
        if self._handle is None:
            self._handle = self.archive.open("rb")
        self._handle.seek(blocs[i][1])
        donnees = zlib.decompress(self._handle.read(fin - blocs[i][1]), wbits=31)
        self._cache = (i, donnees)
        return donnees

    def ligne_a(self, offset: int) -> bytes | None:
        offset = int(offset)
        if self.index is None:                 # archive sans index : correct mais lent (lecture séquentielle)
            with gzip.open(self.archive, "rb") as g:
                g.seek(offset)
                return g.readline() or None
        i = bisect.bisect_right(self._debuts, offset) - 1
        if i < 0:
            return None
        debut, _, longueur = self.index["blocs"][i]
        if offset >= debut + longueur:
            return None
        donnees = self._bloc(i)
        rel = offset - debut
        fin = donnees.find(b"\n", rel)
        return donnees[rel:] if fin < 0 else donnees[rel:fin + 1]

    def fermer(self) -> None:
        if self._handle is not None:
            self._handle.close()
            self._handle = None


def ouvrir_texte(chemin: Path):
    """Ouvre un ruban en texte, qu'il soit en clair ou archivé (``X.jsonl`` ou ``X.jsonl.gz``)."""
    chemin = Path(chemin)
    if chemin.suffix == ".gz":
        return gzip.open(chemin, "rt", encoding="utf-8", errors="ignore")
    return chemin.open(encoding="utf-8", errors="ignore")


def version_presente(chemin: Path) -> Path | None:
    """Le ruban tel qu'il existe : en clair s'il l'est encore, sinon son archive ``.gz``, sinon None."""
    chemin = Path(chemin)
    if chemin.is_file():
        return chemin
    gz = chemin.with_name(chemin.name + ".gz")
    return gz if gz.is_file() else None


__all__ = ["SCHEMA_INDEX", "SUFFIXE_INDEX", "BLOC_DEFAUT", "chemin_index", "compresser", "remplacer_par_archive",
           "LecteurArchive", "ouvrir_texte", "version_presente"]
