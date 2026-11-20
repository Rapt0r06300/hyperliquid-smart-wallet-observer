#!/usr/bin/env python3
"""Qui efface les fichiers de ``catalog/`` ? Surveillance en TEMPS REEL, sans dependance.

LE FAIT A EXPLIQUER (19-20/11/2026). Des fichiers de ``catalog/`` disparaissent HORS DE GIT, et
le rythme augmente : **194 supprimes** en soiree, **484** le lendemain, dont des manifestes de
campagne restaures quelques heures plus tot. Deux restaurations ont deja ete faites a l aveugle ;
une troisieme serait un tapis roulant. L elagage d AlinaSync a ete ECARTE (``--prune-cache-only``
est une operation explicite et separee, jamais la synchronisation par defaut).

POURQUOI PAS UNE INTERROGATION PERIODIQUE. Un instantane de ``catalog/`` coute 2,9 s pour 22 415
entrees : a 30 s d intervalle on brule 10 % d un coeur ET on rate le coupable, puisqu on constate
APRES coup. ``ReadDirectoryChangesW`` (Win32, via ctypes) previent a l instant meme, pour un cout
nul entre deux evenements.

CE QUE L OUTIL PROUVE, ET CE QU IL NE PROUVE PAS. L API Windows dit QUEL fichier disparait, jamais
QUI l a supprime -- l attribution exigerait un audit SACL, donc des droits administrateur et une
modification de la politique systeme de l operateur. On photographie donc les processus vivants a
la milliseconde de l evenement, avec leurs compteurs d E/S : en pratique le coupable est celui qui
ecrit. C est une CORRELATION etayee, pas une preuve formelle, et le journal le dit.

PAPER / LECTURE SEULE : cet outil n efface rien, ne restaure rien et ne touche a aucun flux. Il
observe et journalise.

    python tools/surveiller_catalog.py                 # surveille jusqu a Ctrl+C
    python tools/surveiller_catalog.py --minutes 120   # ou pendant une duree bornee
"""

from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wt
import json
import os
import sys
import time
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
JOURNAL = Path("runtime") / "logs" / "surveillance_catalog.jsonl"

#: Actions de ``ReadDirectoryChangesW``.
ACTIONS = {1: "AJOUTE", 2: "SUPPRIME", 3: "MODIFIE", 4: "RENOMME_DEPUIS", 5: "RENOMME_VERS"}
#: Celles qui nous interessent : une disparition, sous ses deux formes.
DISPARITIONS = {"SUPPRIME", "RENOMME_DEPUIS"}

FILE_LIST_DIRECTORY = 0x0001
FILE_SHARE_ALL = 0x0007
OPEN_EXISTING = 3
FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
FILTRE = 0x0001 | 0x0002 | 0x0008 | 0x0010  # noms de fichier, de repertoire, taille, ecriture

#: Une rafale de suppressions ne merite qu UNE photographie des processus : la repeter des
#: milliers de fois noierait le journal et fausserait la mesure en consommant le processeur.
SECONDES_ENTRE_DEUX_PHOTOS = 5.0


def _photographier_processus(psutil_mod=None) -> list[dict]:
    """Les processus vivants, tries par ecritures disque -- le coupable ecrit, par definition."""
    if psutil_mod is None:
        try:
            import psutil as psutil_mod  # type: ignore[no-redef]
        except ImportError:
            return []
    moi = os.getpid()
    vus: list[dict] = []
    for proc in psutil_mod.process_iter(["pid", "name", "cmdline", "create_time"]):
        try:
            pid = int(proc.info.get("pid") or 0)
            if pid in (0, moi):
                continue        # ne jamais se designer soi-meme comme coupable
            try:
                io = proc.io_counters()
                ecritures, octets = int(io.write_count), int(io.write_bytes)
            except Exception:   # noqa: BLE001 - droits refuses ou processus disparu
                ecritures = octets = -1
            vus.append({
                "pid": pid,
                "nom": str(proc.info.get("name") or ""),
                "ligne": " ".join(proc.info.get("cmdline") or ())[:220],
                "depuis_s": round(time.time() - float(proc.info.get("create_time") or 0), 1),
                "ecritures": ecritures,
                "octets_ecrits": octets,
            })
        except Exception:       # noqa: BLE001 - un processus peut mourir pendant le scan
            continue
    vus.sort(key=lambda p: (-p["ecritures"], -p["octets_ecrits"]))
    return vus[:12]


def _journaliser(chemin: Path, enregistrement: dict) -> None:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    with chemin.open("a", encoding="utf-8") as sortie:
        sortie.write(json.dumps(enregistrement, ensure_ascii=False) + "\n")


def surveiller(racine: Path, *, dossier: str = "catalog", minutes: float = 0.0,
               journal: Path | None = None, _lecteur=None) -> int:
    """Journalise chaque disparition dans ``catalog/`` avec l etat des processus.

    ``minutes <= 0`` surveille indefiniment (Ctrl+C pour arreter).
    """
    cible = racine / dossier
    if not cible.is_dir():
        print(f"[NON] dossier absent : {cible}", file=sys.stderr)
        return 2
    chemin_journal = journal or (racine / JOURNAL)

    k32 = ctypes.windll.kernel32
    poignee = k32.CreateFileW(
        str(cible), FILE_LIST_DIRECTORY, FILE_SHARE_ALL, None,
        OPEN_EXISTING, FILE_FLAG_BACKUP_SEMANTICS, None)
    if poignee == wt.HANDLE(-1).value:
        print(f"[NON] ouverture impossible : {cible}", file=sys.stderr)
        return 3

    tampon = ctypes.create_string_buffer(64 * 1024)
    rendus = wt.DWORD()
    fin = time.time() + minutes * 60 if minutes > 0 else None
    derniere_photo = 0.0
    disparitions = 0
    print(f"[SURVEILLANCE] {cible} -> {chemin_journal}", flush=True)
    print("[SURVEILLANCE] en temps reel ; Ctrl+C pour arreter.", flush=True)
    try:
        while fin is None or time.time() < fin:
            ok = k32.ReadDirectoryChangesW(
                poignee, tampon, ctypes.sizeof(tampon), True, FILTRE,
                ctypes.byref(rendus), None, None)
            if not ok or rendus.value == 0:
                continue
            maintenant = time.time()
            lot: list[tuple[str, str]] = []
            decalage = 0
            while True:
                suivant = int.from_bytes(tampon.raw[decalage:decalage + 4], "little")
                action = int.from_bytes(tampon.raw[decalage + 4:decalage + 8], "little")
                taille = int.from_bytes(tampon.raw[decalage + 8:decalage + 12], "little")
                nom = tampon.raw[decalage + 12:decalage + 12 + taille].decode("utf-16-le")
                lot.append((ACTIONS.get(action, str(action)), nom))
                if suivant == 0:
                    break
                decalage += suivant
            partis = [nom for acte, nom in lot if acte in DISPARITIONS]
            if not partis:
                continue
            disparitions += len(partis)
            photo: list[dict] = []
            if maintenant - derniere_photo >= SECONDES_ENTRE_DEUX_PHOTOS:
                photo = _photographier_processus()
                derniere_photo = maintenant
            _journaliser(chemin_journal, {
                "horodatage": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(maintenant)),
                "disparus": partis[:40],
                "disparus_total_ce_lot": len(partis),
                "cumul": disparitions,
                # L API ne nomme PAS l auteur : ceci est une correlation, pas une preuve.
                "processus_au_moment_de_l_evenement": photo,
            })
            print(f"[DISPARITION] {len(partis)} fichier(s) ; cumul {disparitions} "
                  f"-> {partis[0][:70]}", flush=True)
    except KeyboardInterrupt:
        print("\n[SURVEILLANCE] arret demande.", flush=True)
    finally:
        k32.CloseHandle(poignee)
    print(f"[SURVEILLANCE] terminee : {disparitions} disparition(s) journalisee(s).", flush=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--racine", default=str(RACINE))
    p.add_argument("--dossier", default="catalog")
    p.add_argument("--minutes", type=float, default=0.0,
                   help="duree de surveillance ; 0 = jusqu a Ctrl+C")
    p.add_argument("--journal", default="")
    a = p.parse_args(argv)
    # `ReadDirectoryChangesW` est BLOQUANT : tant qu aucun evenement n arrive, la boucle ne
    # reprend pas la main et la borne `--minutes` n est jamais evaluee -- l outil ne
    # s arreterait donc pas quand on le lui demande. Constate a l essai du 20/11/2026. On
    # confie la surveillance a un fil DEMON et on attend ici : a l echeance, le processus
    # sort et le fil meurt avec lui.
    if a.minutes > 0:
        import threading
        code = {"valeur": 0}

        def _tourner():
            code["valeur"] = surveiller(
                Path(a.racine), dossier=a.dossier, minutes=0.0,
                journal=Path(a.journal) if a.journal else None)

        fil = threading.Thread(target=_tourner, daemon=True)
        fil.start()
        fil.join(timeout=a.minutes * 60)
        if fil.is_alive():
            print("[SURVEILLANCE] duree atteinte ; arret.", flush=True)
        return code["valeur"]
    return surveiller(
        Path(a.racine), dossier=a.dossier, minutes=0.0,
        journal=Path(a.journal) if a.journal else None)


if __name__ == "__main__":
    raise SystemExit(main())
