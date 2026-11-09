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
import json
import os
import time
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
STATUT = RACINE / "runtime" / "coffre_certifie" / "SUIVI_COFFRE.json"
PERIME_S = 20.0  # au-delà, le statut est considéré "inactif" (aucune certif en cours)


def _fmt_duree(secondes: float) -> str:
    s = int(max(0, secondes))
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m{s % 60:02d}s"
    return f"{s // 3600}h{(s % 3600) // 60:02d}m"


def _fmt_mo(octets: float) -> str:
    return f"{octets / 1048576:.1f} Mo"


def barre(pct: float, largeur: int = 32) -> str:
    pct = max(0.0, min(100.0, float(pct or 0.0)))
    plein = int(round(pct / 100.0 * largeur))
    return "[" + "#" * plein + "-" * (largeur - plein) + "]"


def lire_statut(chemin: Path) -> dict | None:
    try:
        return json.loads(chemin.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def rendre(st: dict | None, *, maintenant_ms: float) -> list[str]:
    """Construit les lignes de l'écran — FONCTION PURE (testable)."""
    L: list[str] = []
    L.append("=" * 64)
    L.append("  ALINA - SUIVI COFFRE : certification -> coffre (temps reel)")
    L.append("=" * 64)
    if not st:
        L.append("  En attente d'une certification...")
        L.append("  (lance 'Certificateur Coffre Fort.cmd' ou arrete les collecteurs)")
        L.append("=" * 64)
        return L
    age_s = max(0.0, (maintenant_ms - float(st.get("updated_ms") or 0)) / 1000.0)
    termine = bool(st.get("termine"))
    stage = str(st.get("stage") or "?")
    pct = float(st.get("pct") or 0.0)
    i, n = int(st.get("i") or 0), int(st.get("n") or 0)
    if termine:
        etat = f"TERMINE (code {st.get('code')})"
    elif age_s > PERIME_S:
        etat = f"INACTIF (pas de maj depuis {_fmt_duree(age_s)})"
    else:
        etat = "EN COURS"
    L.append(f"  Etat   : {etat}")
    L.append(f"  Etape  : {stage}")
    L.append(f"  {barre(pct)}  {pct:5.1f}%")
    if n:
        L.append(f"  Fichiers : {i}/{n}")
    fich = str(st.get("fichier") or "")
    if fich and not termine:
        L.append(f"  En cours : {fich}")
    of, ot = float(st.get("octets_faits") or 0), float(st.get("octets_total") or 0)
    if ot:
        L.append(f"  Volume   : {_fmt_mo(of)} / {_fmt_mo(ot)}")
    deb = float(st.get("debit_mo_s") or 0.0)
    if deb and not termine:
        L.append(f"  Debit    : {deb:.1f} Mo/s")
    if not termine:
        L.append(f"  ETA      : reste ~{_fmt_duree(float(st.get('eta_s') or 0.0))}")
    resume = st.get("resume")
    if termine and isinstance(resume, dict):
        L.append("  " + "-" * 60)
        gard = resume.get("deposes")
        if callable(gard):  # robustesse si jamais un objet non sérialisé
            gard = None
        L.append(f"  Gardees coffre : {resume.get('deposes', resume.get('entrees', '?'))}"
                 f"  |  ecartees : {resume.get('quarantaine', '?')}"
                 f"  |  doublons : {resume.get('doublons', '?')}")
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


def boucle(chemin: Path, *, intervalle: float = 1.0) -> int:
    fin_affichee = 0
    while True:
        st = lire_statut(chemin)
        os.system("cls" if os.name == "nt" else "clear")
        print("\n".join(rendre(st, maintenant_ms=time.time() * 1000)), flush=True)
        # Une fois terminé, on garde l'écran quelques cycles puis on sort.
        if st and st.get("termine"):
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
        return boucle(Path(a.statut), intervalle=max(0.2, a.intervalle))
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
