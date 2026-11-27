#!/usr/bin/env python3
"""SUIVI COFFRE — écran de suivi en direct de la certification -> coffre.

Lit le statut live écrit par ``tools/sceller_coffre_local.py``
(``runtime/coffre_certifie/SUIVI_COFFRE.json``) et affiche, en continu :
avancement (%), barre, fichier en cours, i/N, débit (Mo/s), ETA (temps restant),
et l'état final (bilan). Fonctionne même quand la certification tourne détachée
(lancée automatiquement à l'arrêt des collecteurs). Lecture seule, q pour quitter.
"""
from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes
import json
import os
import time
from collections import deque
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
STATUT = RACINE / "runtime" / "coffre_certifie" / "SUIVI_COFFRE.json"
PERIME_S = 20.0  # suivi sans battement; l'état du PID verrouillé prime sur cette ancienneté
VERROU_CERTIFICATEUR = Path("runtime") / "data" / "coffre_certificateur.lock"


def _fmt_duree(secondes: float) -> str:
    s = int(max(0, secondes))
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m{s % 60:02d}s"
    return f"{s // 3600}h{(s % 3600) // 60:02d}m"


def _fmt_mo(octets: float) -> str:
    return f"{octets / 1048576:.1f} Mo"


def _fmt_volume(octets: float) -> str:
    valeur = max(0.0, float(octets or 0.0))
    if valeur >= 1024**3:
        return f"{valeur / 1024**3:.2f} Go"
    return _fmt_mo(valeur)


class _FILETIME(ctypes.Structure):
    _fields_ = [("dwLowDateTime", ctypes.wintypes.DWORD),
                ("dwHighDateTime", ctypes.wintypes.DWORD)]


class _IO_COUNTERS(ctypes.Structure):
    _fields_ = [("ReadOperationCount", ctypes.c_ulonglong),
                ("WriteOperationCount", ctypes.c_ulonglong),
                ("OtherOperationCount", ctypes.c_ulonglong),
                ("ReadTransferCount", ctypes.c_ulonglong),
                ("WriteTransferCount", ctypes.c_ulonglong),
                ("OtherTransferCount", ctypes.c_ulonglong)]


def _inspecter_processus_verrou(racine: Path) -> tuple[bool | None, dict | None]:
    """Vérifie le PID du verrou, sa date de création et son activité E/S sous Windows.

    Le statut JSON est un instantané écrit entre fichiers. Sa fraîcheur seule ne permet
    donc pas d'affirmer que le certificateur est inactif. ``None`` signifie que le
    processus n'a pas pu être vérifié ; dans ce cas l'écran n'annonce pas un arrêt.
    """
    chemin = Path(racine) / VERROU_CERTIFICATEUR
    try:
        verrou = json.loads(chemin.read_text(encoding="utf-8"))
        pid = int(verrou["pid"])
        verrou_ts = float(verrou["ts"])
        if pid <= 0 or verrou_ts <= 0:
            return None, None
    except FileNotFoundError:
        return False, None
    except (OSError, ValueError, TypeError, KeyError):
        return None, None

    if os.name != "nt":
        # Sans heure de création du processus, on ne peut exclure un PID réutilisé.
        return None, {"pid": pid}

    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [ctypes.wintypes.DWORD, ctypes.wintypes.BOOL,
                                         ctypes.wintypes.DWORD]
        kernel32.OpenProcess.restype = ctypes.wintypes.HANDLE
        kernel32.CloseHandle.argtypes = [ctypes.wintypes.HANDLE]
        kernel32.CloseHandle.restype = ctypes.wintypes.BOOL
        kernel32.GetExitCodeProcess.argtypes = [ctypes.wintypes.HANDLE,
                                                 ctypes.POINTER(ctypes.wintypes.DWORD)]
        kernel32.GetExitCodeProcess.restype = ctypes.wintypes.BOOL
        kernel32.GetProcessTimes.argtypes = [ctypes.wintypes.HANDLE,
                                             ctypes.POINTER(_FILETIME), ctypes.POINTER(_FILETIME),
                                             ctypes.POINTER(_FILETIME), ctypes.POINTER(_FILETIME)]
        kernel32.GetProcessTimes.restype = ctypes.wintypes.BOOL
        kernel32.GetProcessIoCounters.argtypes = [ctypes.wintypes.HANDLE,
                                                   ctypes.POINTER(_IO_COUNTERS)]
        kernel32.GetProcessIoCounters.restype = ctypes.wintypes.BOOL
        handle = kernel32.OpenProcess(0x1000 | 0x00100000, False, pid)
        if not handle:
            # ERROR_INVALID_PARAMETER signifie que le PID n'existe pas. Access denied,
            # erreur transitoire ou droits insuffisants restent INCONNUS, jamais INACTIFS.
            return (False, None) if ctypes.get_last_error() == 87 else (None, {"pid": pid})
        try:
            exit_code = ctypes.wintypes.DWORD()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return None, {"pid": pid}
            if exit_code.value != 259:  # STILL_ACTIVE
                return False, None
            creation, _exit, _kernel, _user = _FILETIME(), _FILETIME(), _FILETIME(), _FILETIME()
            if not kernel32.GetProcessTimes(handle, ctypes.byref(creation), ctypes.byref(_exit),
                                            ctypes.byref(_kernel), ctypes.byref(_user)):
                return None, {"pid": pid}
            ticks = (int(creation.dwHighDateTime) << 32) | int(creation.dwLowDateTime)
            creation_unix = ticks / 10_000_000 - 11_644_473_600
            if abs(creation_unix - verrou_ts) > 120.0:
                return False, None  # PID réutilisé ou verrou d'une autre exécution
            counters = _IO_COUNTERS()
            io_ok = bool(kernel32.GetProcessIoCounters(handle, ctypes.byref(counters)))
            info = {"pid": pid, "started_unix": creation_unix}
            if io_ok:
                info["read_bytes"] = int(counters.ReadTransferCount)
                info["write_bytes"] = int(counters.WriteTransferCount)
                info["process_count"] = 1
                info["io_scope"] = "certificateur"
                # La compression utilise des workers enfants. Les compter évite d'afficher
                # artificiellement 0 Mo/s alors que ces workers lisent les rubans.
                try:
                    import psutil
                    parent = psutil.Process(pid)
                    if abs(parent.create_time() - creation_unix) <= 2.0:
                        descendants = parent.children(recursive=True)
                        total_lu, total_ecrit, comptes = info["read_bytes"], info["write_bytes"], 1
                        cpu_s = parent.cpu_times().user + parent.cpu_times().system
                        for enfant in descendants:
                            try:
                                io = enfant.io_counters()
                                temps_cpu = enfant.cpu_times()
                            except (psutil.Error, OSError):
                                continue
                            total_lu += int(io.read_bytes)
                            total_ecrit += int(io.write_bytes)
                            cpu_s += float(temps_cpu.user + temps_cpu.system)
                            comptes += 1
                        info.update(read_bytes=total_lu, write_bytes=total_ecrit,
                                    cpu_seconds=cpu_s, process_count=comptes,
                                    io_scope="certificateur + workers")
                except Exception:  # noqa: BLE001 — le compteur optionnel ne doit pas casser l'écran
                    pass  # les compteurs du PID principal restent une mesure valide
            return True, info
        finally:
            kernel32.CloseHandle(handle)
    except (AttributeError, OSError, TypeError, ValueError):
        return None, {"pid": pid}


class _SondeDebitLecture:
    """Débit de lecture Windows du processus certifié, lissé sur une fenêtre courte."""

    def __init__(self, fenetre_s: float = 5.0) -> None:
        self.fenetre_s = max(1.0, float(fenetre_s))
        self.pid: int | None = None
        self.samples: deque[tuple[float, int]] = deque()
        self.cpu_samples: deque[tuple[float, float]] = deque()

    def actualiser(self, info: dict | None, maintenant: float | None = None) -> dict | None:
        if not isinstance(info, dict) or "read_bytes" not in info:
            self.pid = None
            self.samples.clear()
            self.cpu_samples.clear()
            return None
        pid, lus = int(info["pid"]), int(info["read_bytes"])
        instant = time.monotonic() if maintenant is None else float(maintenant)
        if pid != self.pid or (self.samples and lus < self.samples[-1][1]):
            self.samples.clear()
            self.cpu_samples.clear()
        self.pid = pid
        self.samples.append((instant, lus))
        while len(self.samples) > 2 and instant - self.samples[0][0] > self.fenetre_s:
            self.samples.popleft()
        resultat = dict(info)
        if len(self.samples) >= 2:
            debut_t, debut_b = self.samples[0]
            delta_t = instant - debut_t
            resultat["read_mo_s"] = max(0.0, (lus - debut_b) / delta_t / 1048576) if delta_t > 0 else 0.0
            resultat["window_s"] = delta_t
        cpu_s = info.get("cpu_seconds")
        if isinstance(cpu_s, (int, float)):
            if self.cpu_samples and float(cpu_s) < self.cpu_samples[-1][1]:
                self.cpu_samples.clear()  # un worker a quitté le groupe observé
            self.cpu_samples.append((instant, float(cpu_s)))
            while len(self.cpu_samples) > 2 and instant - self.cpu_samples[0][0] > self.fenetre_s:
                self.cpu_samples.popleft()
            if len(self.cpu_samples) >= 2:
                debut_t, debut_cpu = self.cpu_samples[0]
                delta_t = instant - debut_t
                if delta_t > 0:
                    resultat["cpu_percent"] = max(0.0, (float(cpu_s) - debut_cpu) / delta_t * 100.0)
                    resultat["cpu_window_s"] = delta_t
        return resultat


class _SondeAvancementStatut:
    """Mesure les octets terminés réellement annoncés par le certificateur sur une fenêtre glissante."""

    def __init__(self, fenetre_s: float = 10.0) -> None:
        self.fenetre_s = max(2.0, float(fenetre_s))
        self.cle: tuple[str, str] | None = None
        self.samples: deque[tuple[float, int]] = deque()

    def actualiser(self, statut: dict | None, maintenant: float | None = None) -> dict | None:
        if not isinstance(statut, dict) or statut.get("termine"):
            self.cle = None
            self.samples.clear()
            return None
        stage = str(statut.get("stage") or "")
        if stage == "CERTIFICATION":
            octets = int(statut.get("octets_faits") or 0)
        elif stage.startswith("COMPRESSION"):
            octets = int(statut.get("compression_octets_traites") or 0)
        else:
            self.cle = None
            self.samples.clear()
            return None
        cle = (str(statut.get("batch_id") or ""), stage)
        instant = time.monotonic() if maintenant is None else float(maintenant)
        if cle != self.cle or (self.samples and octets < self.samples[-1][1]):
            self.samples.clear()
        self.cle = cle
        self.samples.append((instant, octets))
        while len(self.samples) > 2 and instant - self.samples[0][0] > self.fenetre_s:
            self.samples.popleft()
        if len(self.samples) < 2:
            return None
        debut, octets_debut = self.samples[0]
        duree = instant - debut
        if duree <= 0:
            return None
        nouveaux = max(0, octets - octets_debut)
        return {"nouveaux_octets": nouveaux, "mo_s": nouveaux / duree / 1048576,
                "window_s": duree, "stage": stage}


def barre(pct: float, largeur: int = 32) -> str:
    pct = max(0.0, min(100.0, float(pct or 0.0)))
    plein = int(round(pct / 100.0 * largeur))
    return "[" + "#" * plein + "-" * (largeur - plein) + "]"


def lire_statut(chemin: Path) -> dict | None:
    try:
        return json.loads(chemin.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


#: Le plan ecrit par le certificateur apres chaque scellement reussi.
CHEMIN_PLAN = ("runtime", "reports", "plan_tranches.json")


def lire_le_plan(racine: Path) -> dict | None:
    """Le dernier plan de tranches connu, ou ``None``.

    Un plan absent ou illisible ne doit RIEN casser : le suivi affiche alors une ligne qui le dit
    et continue. Un ecran de suivi qui planterait sur un JSON tronque serait pire qu'un ecran sans
    plan -- et un JSON tronque arrive, puisque le certificateur l'ecrit pendant qu'on le lit.
    """
    chemin = Path(racine).joinpath(*CHEMIN_PLAN)
    try:
        charge = json.loads(chemin.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return charge if isinstance(charge, dict) else None


def lignes_du_plan(plan: dict | None) -> list[str]:
    """Les deux ou trois lignes du decoupage — FONCTION PURE elle aussi."""
    if not plan:
        return ["  Plan labo : aucun (il sera ecrit a la fin de la prochaine certification)"]
    tranches = plan.get("tranches")
    if not isinstance(tranches, list) or not tranches:
        return ["  Plan labo : illisible — la certification reste valide"]
    couv = plan.get("couverture") if isinstance(plan.get("couverture"), dict) else {}
    heures = float(couv.get("etendue_ms") or 0) / 3_600_000
    continu = "continu" if couv.get("continue") else "DISCONTINU"
    au_plus = " au plus" if str(plan.get("borne") or "").upper() == "HAUTE" else ""
    lignes = [f"  Plan labo : {len(tranches)} tranche(s){au_plus}  |  {heures:.0f} h  |  {continu}"]
    mesure = plan.get("mesure") if isinstance(plan.get("mesure"), dict) else {}
    fills = mesure.get("lignes")
    if isinstance(fills, int):
        lignes.append(f"              {fills:,} fills dans la fenetre du labo".replace(",", " "))
    if au_plus:
        lignes.append("              (borne haute : fills BRUTS du coffre, doublons et non-causaux"
                      " seront ecartes)")
    return lignes


def rendre(st: dict | None, *, maintenant_ms: float, plan: dict | None = None,
           certificateur_actif: bool | None = None,
           lecture_processus: dict | None = None,
           progression_lot: dict | None = None) -> list[str]:
    """Construit les lignes de l'écran — FONCTION PURE (testable).

    ``plan`` est PASSE, jamais lu ici : c'est ce qui garde cette fonction testable sans fichier.
    """
    L: list[str] = []
    L.append("=" * 64)
    L.append("  ALINA - SUIVI COFFRE : certification -> coffre (temps reel)")
    L.append("=" * 64)
    if not st:
        if certificateur_actif is True:
            L.append("  CERTIFICATEUR ACTIF — initialisation du premier suivi")
        else:
            L.append("  En attente d'une certification...")
        L.append("  (lance 'Certificateur Coffre Fort.cmd' ou arrete les collecteurs)")
        L.append("  " + "-" * 60)
        L.extend(lignes_du_plan(plan))
        L.append("=" * 64)
        return L
    age_s = max(0.0, (maintenant_ms - float(st.get("updated_ms") or 0)) / 1000.0)
    termine = bool(st.get("termine"))
    stage = str(st.get("stage") or "?")
    pct_confirme = float(st.get("pct_confirme", st.get("pct", 0.0)) or 0.0)
    pct_estime = st.get("pct_estime")
    pct = float(pct_estime if isinstance(pct_estime, (int, float)) else st.get("pct") or 0.0)
    i, n = int(st.get("i") or 0), int(st.get("n") or 0)
    compression = stage.startswith("COMPRESSION")
    if termine and certificateur_actif is True:
        etat = "ÉTAPE CERTIFICATION TERMINÉE — processus toujours actif (post-traitement)"
    elif termine:
        etat = f"TERMINE (code {st.get('code')})"
    elif age_s > PERIME_S:
        if certificateur_actif is True:
            etat = f"EN COURS — processus vérifié actif, dernier battement il y a {_fmt_duree(age_s)}"
        elif certificateur_actif is False:
            etat = f"INACTIF — processus arrêté/absent, suivi daté de {_fmt_duree(age_s)}"
        else:
            etat = f"SUIVI PÉRIMÉ — activité non vérifiée ({_fmt_duree(age_s)})"
    else:
        etat = "EN COURS"
    L.append(f"  Etat   : {etat}")
    L.append(f"  Etape  : {stage}")
    if stage == "SCAN":
        entrees = int(st.get("scan_entrees_vues") or 0)
        donnees = int(st.get("scan_donnees_trouvees") or 0)
        dossiers = int(st.get("scan_dossiers_vus") or 0)
        L.append(f"  Inventaire des données : {donnees:,} fichier(s) trouvé(s) parmi "
                 f"{entrees:,} entrées, {dossiers:,} dossier(s)".replace(",", " "))
        L.append("  ETA : calculée après l'inventaire (le total de fichiers est encore inconnu)")
    elif stage == "COMPRESSION_SCAN":
        scannes = int(st.get("compression_scannes") or 0)
        candidats = int(st.get("compression_candidats") or 0)
        L.append(f"  Inventaire : {scannes:,} fichier(s) examinés, {candidats:,} candidat(s) figé(s)".replace(",", " "))
        L.append("  Pourcentage et ETA : disponibles après la fin de l'inventaire (total encore inconnu)")
    elif compression and not termine:
        pct_comp = st.get("compression_pct_estime")
        if isinstance(pct_comp, (int, float)):
            L.append(f"  Progression compression + vérification : {barre(pct_comp)} {pct_comp:5.1f}% estimés")
        else:
            L.append("  Progression compression + vérification : mesure des premiers fichiers")
        faits = int(st.get("compression_faits") or 0)
        total_fichiers = int(st.get("compression_candidats") or 0)
        L.append(f"  Compression : {faits:,}/{total_fichiers:,} fichiers terminés".replace(",", " "))
        traites = int(st.get("compression_octets_traites") or 0)
        total_comp = int(st.get("compression_octets_total") or 0)
        if total_comp:
            L.append(f"  Volume source traité : {_fmt_volume(traites)} / {_fmt_volume(total_comp)}"
                     " (fichiers terminés)")
        compresse = int(st.get("compression_octets_compressees") or 0)
        if compresse:
            L.append(f"  Volume compressé confirmé et vérifié : {_fmt_volume(compresse)}")
        actifs = st.get("compression_actifs")
        if isinstance(actifs, list) and actifs:
            apercu = ", ".join(str(x) for x in actifs[:3])
            suffixe = f" (+{len(actifs) - 3})" if len(actifs) > 3 else ""
            L.append(f"  Fichiers actifs : {apercu}{suffixe}")
        en_traitement = int(st.get("compression_en_traitement") or 0)
        L.append(f"  Fichiers actuellement traités : {en_traitement}")
        debit_comp = st.get("compression_debit_mo_s")
        if isinstance(debit_comp, (int, float)):
            L.append(f"  Débit de travail estimé : {float(debit_comp):.1f} Mo-traitement/s")
    elif stage == "SCAN":
        pass  # le volume total est inconnu jusqu'à la fin de l'inventaire
    else:
        pct_lot = pct_confirme if stage == "CERTIFICATION" else pct
        nom_avancement = "Progression confirmée du lot" if stage == "CERTIFICATION" else "Avancement"
        L.append(f"  {nom_avancement} : {barre(pct_lot)} {pct_lot:5.1f}%")
        pct_fichier = st.get("fichier_pct")
        if stage == "CERTIFICATION" and isinstance(pct_fichier, (int, float)):
            L.append(f"  Fichier courant : {barre(pct_fichier, 20)} {float(pct_fichier):4.1f}% "
                     f"({st.get('fichier_phase') or 'phase en cours'})")
    if n:
        L.append(f"  Fichiers : {i}/{n}")
    fich = str(st.get("fichier") or "")
    if fich and not termine:
        L.append(f"  En cours : {fich}")
    of, ot = float(st.get("octets_faits") or 0), float(st.get("octets_total") or 0)
    if ot and not compression:
        L.append(f"  Volume source confirmé : {_fmt_volume(of)} / {_fmt_volume(ot)}"
                 " (fichiers terminés)")
    octets_estimes = st.get("octets_estimes_faits")
    if isinstance(octets_estimes, (int, float)) and ot:
        L.append(f"  Volume estimé avec fichier courant : {_fmt_volume(octets_estimes)} / {_fmt_volume(ot)}")
    fichier_lus = st.get("fichier_octets_lus")
    fichier_total = st.get("fichier_octets_total")
    if isinstance(fichier_lus, (int, float)):
        detail = f"  Fichier courant lu : {_fmt_volume(fichier_lus)}"
        if isinstance(fichier_total, (int, float)) and fichier_total > 0:
            detail += f" / {_fmt_volume(fichier_total)} ({min(100.0, fichier_lus / fichier_total * 100):.1f}%)"
        phase_fichier = str(st.get("fichier_phase") or "").strip()
        if phase_fichier:
            detail += f" — {phase_fichier}"
        L.append(detail)
    if lecture_processus and isinstance(lecture_processus.get("read_mo_s"), (int, float)):
        L.append(f"  Lecture disque ({lecture_processus.get('io_scope', 'certificateur')}) : "
                 f"{lecture_processus['read_mo_s']:.1f} Mo/s"
                 f" (fenêtre {lecture_processus.get('window_s', 0):.0f}s, PID {lecture_processus.get('pid')})")
        L.append(f"  Compteur E/S des processus actifs : {_fmt_volume(lecture_processus.get('read_bytes', 0))}")
    if lecture_processus and isinstance(lecture_processus.get("cpu_percent"), (int, float)):
        L.append(f"  Activité CPU observée : {lecture_processus['cpu_percent']:.0f}% d'un cœur"
                 f" (fenêtre {lecture_processus.get('cpu_window_s', 0):.0f}s, "
                 f"{lecture_processus.get('process_count', 1)} processus)")
    if lecture_processus and isinstance(lecture_processus.get("started_unix"), (int, float)):
        duree_processus = max(0.0, maintenant_ms / 1000.0 - lecture_processus["started_unix"])
        L.append(f"  Durée du processus : {_fmt_duree(duree_processus)}")
    debit_fichier = st.get("fichier_debit_mo_s")
    if isinstance(debit_fichier, (int, float)) and not termine:
        L.append(f"  Débit JSONL du fichier courant : {float(debit_fichier):.1f} Mo/s"
                 " (octets décompressés lus)")
    if progression_lot and isinstance(progression_lot.get("mo_s"), (int, float)):
        debit_confirme = float(progression_lot["mo_s"])
        fenetre = float(progression_lot.get("window_s") or 0.0)
        if progression_lot.get("stage") == "CERTIFICATION":
            L.append(f"  Débit confirmé des fichiers terminés : {debit_confirme:.1f} Mo/s "
                     f"(fenêtre {fenetre:.0f}s)")
        else:
            L.append(f"  Débit confirmé des fichiers compressés/traités : {debit_confirme:.1f} Mo/s "
                     f"(fenêtre {fenetre:.0f}s)")
        if int(progression_lot.get("nouveaux_octets") or 0) == 0:
            L.append("  Aucun fichier terminé dans cette fenêtre; le travail CPU/disque reste affiché séparément.")
    lignes_fichier = st.get("fichier_lignes_lues")
    if isinstance(lignes_fichier, int) and not termine:
        L.append(f"  Lignes lues dans le fichier courant : {lignes_fichier:,}".replace(",", " "))
    deb = float(st.get("debit_mo_s") or 0.0)
    if deb and not termine:
        L.append(f"  Débit moyen estimé du lot : {deb:.1f} Mo/s")
    if not termine:
        eta_brut = max(0.0, float(st.get("eta_s") or 0.0))
        eta_mesure_ms = st.get("eta_updated_ms")
        age_eta = (max(0.0, (maintenant_ms - float(eta_mesure_ms)) / 1000.0)
                   if isinstance(eta_mesure_ms, (int, float)) else age_s)
        eta_restant = max(0.0, eta_brut - age_eta)
        if not (certificateur_actif is True or age_s <= PERIME_S):
            L.append("  ETA estimée : indisponible (certificateur non actif ou état non vérifié)")
        elif eta_brut:
            if eta_brut and age_eta >= eta_brut:
                L.append("  ETA estimée : projection dépassée — attente de la prochaine mesure")
            else:
                L.append(f"  ETA estimée : ~{_fmt_duree(eta_restant)} (décompte depuis la dernière mesure)")
        elif stage in ("SCAN", "COMPRESSION_SCAN"):
            L.append("  ETA estimée : indisponible pendant l'inventaire (volume total inconnu)")
        else:
            L.append("  ETA estimée : en attente d'une mesure de débit")
        progression_ms = st.get("progression_ms")
        if isinstance(progression_ms, (int, float)):
            age_progression = max(0.0, (maintenant_ms - float(progression_ms)) / 1000.0)
            L.append(f"  Dernière progression mesurée : il y a {_fmt_duree(age_progression)}")
        elif isinstance(st.get("updated_ms"), (int, float)) and not termine:
            age_statut = max(0.0, (maintenant_ms - float(st["updated_ms"])) / 1000.0)
            L.append(f"  Dernier point enregistré par cette version : il y a {_fmt_duree(age_statut)}")
        L.append(f"  Dernier battement du suivi : il y a {_fmt_duree(age_s)}")
    resume = st.get("resume")
    if termine and isinstance(resume, dict):
        L.append("  " + "-" * 60)
        gard = resume.get("deposes")
        if callable(gard):  # robustesse si jamais un objet non sérialisé
            gard = None
        L.append(f"  Gardees coffre : {resume.get('deposes', resume.get('entrees', '?'))}"
                 f"  |  ecartees : {resume.get('quarantaine', '?')}"
                 f"  |  doublons : {resume.get('doublons', '?')}")
    L.append("  " + "-" * 60)
    L.extend(lignes_du_plan(plan))
    L.append("=" * 64)
    L.append("  q = quitter")
    return L


def _quitter_demande(duree: float) -> bool:
    try:
        import msvcrt
    except ImportError:
        time.sleep(duree)
        return False
    fin = time.time() + duree
    while time.time() < fin:
        if msvcrt.kbhit() and msvcrt.getch() in (b"q", b"Q"):
            return True
        time.sleep(0.05)
    return False


def boucle(chemin: Path, *, intervalle: float = 1.0, racine: Path | None = None) -> int:
    fin_affichee = 0
    # La racine du depot : le plan de tranches y est relu a chaque rafraichissement. C'est un
    # petit JSON, et le relire a chaque cycle le montre des que le certificateur l'a ecrit --
    # sans quoi il faudrait quitter et relancer le suivi pour le voir apparaitre.
    racine = Path(racine) if racine is not None else Path(__file__).resolve().parents[1]
    sonde = _SondeDebitLecture()
    sonde_progression = _SondeAvancementStatut()
    while True:
        st = lire_statut(chemin)
        plan = lire_le_plan(racine)
        certificateur_actif, io_brut = _inspecter_processus_verrou(racine)
        lecture = sonde.actualiser(io_brut)
        progression = sonde_progression.actualiser(st)
        os.system("cls" if os.name == "nt" else "clear")
        print("\n".join(rendre(st, maintenant_ms=time.time() * 1000, plan=plan,
                              certificateur_actif=certificateur_actif,
                              lecture_processus=lecture, progression_lot=progression)),
              flush=True)
        # Une fois terminé, on garde l'écran quelques cycles puis on sort.
        if st and st.get("termine") and certificateur_actif is not True:
            fin_affichee += 1
            if fin_affichee >= 5:
                return 0
        else:
            fin_affichee = 0
        if _quitter_demande(intervalle):
            return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--statut", default=str(STATUT), help="chemin du SUIVI_COFFRE.json")
    ap.add_argument("--intervalle", type=float, default=1.0)
    a = ap.parse_args(argv)
    try:
        if os.name == "nt":
            try:
                ctypes.windll.kernel32.SetConsoleTitleW("ALINA - SUIVI COFFRE EN DIRECT")
            except (AttributeError, OSError):
                pass
        return boucle(Path(a.statut), intervalle=max(0.2, a.intervalle))
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
