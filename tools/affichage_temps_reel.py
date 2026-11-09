#!/usr/bin/env python3
"""ECRAN UNIQUE — tout ce que les collecteurs recoltent, en temps reel.

Decouvre AUTOMATIQUEMENT tous les flux `.jsonl` de `runtime/data/` (toutes les ameliorations :
fills WS/poll/noeud/TWAP/estimes, L2, BBO, trades, bougies, positions, explorer, venues,
asset-ctx, liquidations, vaults, etc.), affiche pour chacun le total + le debit + la fraicheur,
l'etat des collecteurs (superviseur / poll / explorer) et les derniers fills. Lecture seule :
n'ecrit rien, n'interfere pas. Ctrl+C pour quitter.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import subprocess
import sys
import time
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]

# Libelles lisibles pour les flux connus : nom_fichier -> (libelle, est_flux_de_fills)
LABELS: dict[str, tuple[str, bool]] = {
    "vault_fills_live.jsonl": ("Fills WS (live)", True),
    "vault_fills_poll.jsonl": ("Fills poll (REST)", True),
    "vault_fills.jsonl": ("Fills consolides", True),
    "leader_fills_bruts.jsonl": ("Fills leaders bruts", True),
    "node_fills_tape.jsonl": ("Fills noeud local", True),
    "explorer_inferred_fills.jsonl": ("Fills estimes explorer", True),
    "copy_vault_twap_lane.jsonl": ("Fills TWAP", True),
    "fills_journal.jsonl": ("Journal fills", True),
    "copy_vault_l2_tape.jsonl": ("Carnets L2", False),
    "raw_l2_lifecycle.jsonl": ("L2 cycle de vie", False),
    "metaorder_l2_tape.jsonl": ("L2 metaordres", False),
    "bbo_tape.jsonl": ("BBO (top of book)", False),
    "copy_vault_bbo_lane.jsonl": ("BBO lane", False),
    "copy_vault_trades_lane.jsonl": ("Trades marche", False),
    "copy_vault_candle_lane.jsonl": ("Bougies (OHLCV)", False),
    "copy_vault_positions_lane.jsonl": ("Positions leaders", False),
    "vault_snapshots.jsonl": ("Snapshots vaults", False),
    "vault_episodes.jsonl": ("Episodes vaults", False),
    "vault_ledger.jsonl": ("Ledger vaults", False),
    "explorer_tx_tape.jsonl": ("Explorer (activite)", False),
    "asset_ctx_tape.jsonl": ("Asset-ctx (OI/funding)", False),
    "hl_allmids_tape.jsonl": ("Prix (allMids)", False),
    "carnet_venues.jsonl": ("Carnets venues", False),
    "dispersion_venues.jsonl": ("Dispersion venues", False),
    "liquidations_confirmees.jsonl": ("Liquidations", False),
    "overshoots_liquidation.jsonl": ("Overshoots liquidation", False),
    "lead_lag_event_decisions.jsonl": ("Lead-lag decisions", False),
    "metaorder_shadow_ledger.jsonl": ("Metaorder shadow", False),
    "userfills_integrity_diagnostics.jsonl": ("Diag. integrite fills", False),
    "userfills_unclassified.jsonl": ("Fills non classes", False),
    "recap_historique.jsonl": ("Recap historique", False),
}

# Flux produits PAR LOT (batch), pas en continu : le collecteur `backfill-fills`
# (tools/backfill_vault_fills.py) ne tourne qu'une fois toutes les 4 h (interval=14400s).
# Entre deux passes, un debit "0.0/s" et un age qui grimpe sont NORMAUX, pas un blocage.
# On les affiche comme un lot avec l'heure de la prochaine passe ; si la passe est en
# retard (collecteur mort), l'ecran le signale explicitement.
CADENCE_LOT: dict[str, float] = {
    "vault_ledger.jsonl": 14400.0,
    "vault_episodes.jsonl": 14400.0,
    "vault_fills.jsonl": 14400.0,
}


def _duree_courte(secondes: float) -> str:
    s = int(secondes)
    if s and s % 3600 == 0:
        return f"{s // 3600}h"
    if s and s % 60 == 0:
        return f"{s // 60}min"
    return f"{s}s"


def _frais_lot(chemin: str, cadence: float, maj: float | None, maintenant: float) -> str:
    """Libelle de fraicheur pour un flux par lot : prochaine passe, ou retard si due."""
    dernier: float | None
    try:
        dernier = os.path.getmtime(chemin)   # survit aux redemarrages de l'ecran
    except OSError:
        dernier = maj
    cad = _duree_courte(cadence)
    if not dernier:
        return f"lot {cad}"
    prochaine = dernier + cadence
    hpro = time.strftime("%H:%M", time.localtime(prochaine))
    reste = prochaine - maintenant
    if reste >= 0:
        return f"lot {cad} - prochaine ~{hpro}"
    return f"lot {cad} - attendue ~{hpro} (RETARD {int((-reste) // 60)}min)"


def label_pour(nom: str) -> tuple[str, bool]:
    if nom in LABELS:
        return LABELS[nom]
    base = nom[:-6] if nom.endswith(".jsonl") else nom
    joli = base.replace("_", " ").strip()
    joli = (joli[:1].upper() + joli[1:]) if joli else nom
    return joli, ("fill" in nom.lower())


def _nb(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def formater_fill(obj: dict) -> str | None:
    """Rend une ligne lisible pour un fill, ou None si non pertinent."""
    coin = obj.get("coin")
    px = _nb(obj.get("px") or obj.get("price"))
    sz = _nb(obj.get("sz") or obj.get("size"))
    if not coin or px is None or sz is None:
        return None
    signe = obj.get("signe")
    side = str(obj.get("side") or "").strip().lower()
    ag = str(obj.get("aggressor_side") or "").strip().lower()
    dire = str(obj.get("dir") or "").strip().lower()
    if signe in (1, "1") or side in ("b", "buy", "bid") or ag.startswith("b") or dire.startswith(("open long", "close short")):
        sens = "ACHAT"
    elif signe in (-1, "-1") or side in ("a", "s", "sell", "ask") or ag.startswith("s") or dire.startswith(("open short", "close long")):
        sens = "VENTE"
    else:
        sens = "  -  "
    vault = str(obj.get("vault") or obj.get("user") or "")
    court = (vault[:6] + ".." + vault[-4:]) if len(vault) > 12 else vault
    ts = obj.get("ts_ms") or obj.get("exchange_ts_ms") or obj.get("observed_at_ms") or obj.get("time")
    heure = "  --:--  "
    if isinstance(ts, (int, float)) and ts > 1e12:
        try:
            heure = datetime.datetime.fromtimestamp(ts / 1000).strftime("%H:%M:%S")
        except (OSError, ValueError, OverflowError):
            pass
    valeur = px * sz
    return f"{heure}  {sens:<5} {str(coin):<7} px={px:<11.6g} sz={sz:<11.6g} ~{valeur:>9.0f}$  {court}"


def _cls():
    os.system("cls" if os.name == "nt" else "clear")


_nettoyage_fait = False


# Marqueurs identifiant un process COLLECTEUR du projet (à arrêter sur stop).
_MARQUEURS_COLLECTEUR = (
    "watch_economic_collectors", "collecter_", "explorer_autonome",
    "poll_leaders", "_run_supervisor", "_run_poll", "_run_explorer", "_run_asset_ctx",
)
# Jamais tuer ceci même si le chemin projet matche (pas des collecteurs) :
# l'écran lui-même, le scellage détaché, la sync, le labo.
_MARQUEURS_EXCLUS = (
    "affichage_temps_reel", "sceller_coffre_local", "archiver_tapes",
    "rapport_collecteurs", "sync_complete_clone", "alina_git_code_sync",
    "pousser-github", "alina_quant_lab", "alina_sync_complete",
)


def _pids_collecteurs_a_tuer(processus, *, self_pid, racine) -> list[int]:
    """Sélectionne les PID de collecteurs du projet à arrêter — FONCTION PURE.

    ``processus`` : itérable de ``(pid:int, cmdline:str)``. On ne retient qu'un
    process dont la ligne de commande référence ``racine`` ET un marqueur
    collecteur ; jamais le process courant (``self_pid``) ni un marqueur exclu
    (écran, scellage, sync, labo). Indépendant de l'état de campagne (qui peut
    ne lister aucun pid). Insensible à la casse et au sens des slashes.
    """
    racine_norm = str(racine).replace("\\", "/").casefold().rstrip("/")
    a_tuer: set[int] = set()
    for pid, cmd in processus:
        try:
            pid = int(pid)
        except (TypeError, ValueError):
            continue
        if pid <= 0 or pid == int(self_pid):
            continue
        c = (cmd or "").replace("\\", "/").casefold()
        if racine_norm and racine_norm not in c:
            continue
        if any(x in c for x in _MARQUEURS_EXCLUS):
            continue
        if any(m in c for m in _MARQUEURS_COLLECTEUR):
            a_tuer.add(pid)
    return sorted(a_tuer)


def _lister_processus_projet(timeout: float = 30) -> list[tuple[int, str]]:
    """[(pid, cmdline)] des python/cmd (Windows) ; [] ailleurs ou en cas d'erreur."""
    if os.name != "nt":
        return []
    ps = (
        "Get-CimInstance Win32_Process -Filter \"Name='python.exe' or Name='py.exe' "
        "or Name='cmd.exe'\" | ForEach-Object { \"$($_.ProcessId)`t$($_.CommandLine)\" }"
    )
    try:
        done = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                              capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return []
    res: list[tuple[int, str]] = []
    for ligne in (done.stdout or "").splitlines():
        pid, _, cmd = ligne.partition("\t")
        pid = pid.strip()
        if pid.isdigit():
            res.append((int(pid), cmd))
    return res


def _arreter_collecteurs(root: Path, *, timeout: float = 60) -> list[int]:
    """Arrêt IMMÉDIAT et garanti des collecteurs du projet. Ne bloque jamais sur
    du travail lourd ; renvoie les PID tués."""
    def _run(*cmd: str, t: float = 30) -> None:
        try:
            subprocess.run(list(cmd), timeout=t,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except (OSError, subprocess.SubprocessError):
            pass

    data = root / "runtime" / "data"
    try:
        (data / "stop_collecteurs.flag").write_text("1", encoding="utf-8")
    except OSError:
        pass
    # 1) invalider le bail (les survivants sortent en secondes)
    cible = root / "tools" / "watch_economic_collectors.py"
    if cible.exists():
        try:
            subprocess.run([sys.executable, "-B", str(cible), "--root", str(root), "--stop"],
                           cwd=str(root), timeout=timeout,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except (OSError, subprocess.SubprocessError):
            pass
    # 2) balayage robuste : tuer tout collecteur du projet encore vivant (arbre),
    #    indépendamment de l'état de campagne (qui peut être vide) et du titre de fenêtre.
    tues: list[int] = []
    for pid in _pids_collecteurs_a_tuer(_lister_processus_projet(),
                                        self_pid=os.getpid(), racine=root):
        _run("taskkill", "/PID", str(pid), "/T", "/F")
        tues.append(pid)
    # 3) fenêtres nommées éventuelles + nettoyage des fichiers d'état
    for titre in ("ALINA-SUPERVISOR", "ALINA-EXPLORER-AUTO", "ALINA-POLL-LEADERS", "ALINA-ASSET-CTX"):
        _run("taskkill", "/FI", f"WINDOWTITLE eq {titre}*", "/T", "/F")
    for nom in ("explorer_autonome.pid", "poll_leaders.pid", "collecteurs.lock", "stop_collecteurs.flag"):
        try:
            (data / nom).unlink()
        except OSError:
            pass
    return tues


def _lancer_scellage_detache(root: Path):
    """Scellage coffre -> archivage -> rapport dans un process DÉTACHÉ (non bloquant).

    Lourd : sorti du chemin d'arrêt pour garantir une fermeture instantanée. Survit
    à la fermeture de l'écran et du .cmd. Ordre garanti (sceller AVANT archiver/reset).
    Renvoie le chemin du log, ou None si rien à lancer.
    """
    scripts = [str(root / "tools" / s) for s in
               ("sceller_coffre_local.py", "archiver_tapes.py", "rapport_collecteurs.py")
               if (root / "tools" / s).exists()]
    if not scripts:
        return None
    log = root / "runtime" / "logs" / "arret_scellage.log"
    try:
        log.parent.mkdir(parents=True, exist_ok=True)
        fh = open(log, "a", encoding="utf-8")
    except OSError:
        fh = subprocess.DEVNULL
    # Un python détaché qui enchaîne les scripts en ordre (évite tout quoting cmd).
    chaine = (
        "import subprocess,sys;"
        f"scripts={scripts!r};root={str(root)!r};"
        "[subprocess.run([sys.executable,'-B',s,'--root',root],cwd=root) for s in scripts]"
    )
    flags = 0
    if os.name == "nt":
        flags = (getattr(subprocess, "DETACHED_PROCESS", 0)
                 | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
    try:
        subprocess.Popen([sys.executable, "-B", "-c", chaine], cwd=str(root),
                         stdout=fh, stderr=subprocess.STDOUT,
                         creationflags=flags, close_fds=True)
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    return log


def nettoyer_session(root: Path) -> None:
    """Arrêt PROPRE piloté par Python, INSTANTANÉ et garanti.

    Chemin d'arrêt découplé : (1) on stoppe immédiatement TOUS les collecteurs du
    projet (balayage par ligne de commande + kill arbre), puis (2) on lance le
    scellage/archivage/rapport — lourd — en TÂCHE DE FOND détachée. Ainsi un Ctrl+C
    (ou 'q') ne se coince jamais sur le scellage, et aucun collecteur n'est laissé
    orphelin. Idempotent.
    """
    global _nettoyage_fait
    if _nettoyage_fait:
        return
    _nettoyage_fait = True
    print("\n  [arret] Stop IMMEDIAT de tous les collecteurs du projet...", flush=True)
    tues = _arreter_collecteurs(root)
    print(f"  [arret] {len(tues)} collecteur(s) arrete(s). Collecte stoppee.", flush=True)
    log = _lancer_scellage_detache(root)
    # Marqueur : le .cmd sait que le nettoyage est pris en charge (pas de double
    # scellage). Le lanceur le supprime au prochain demarrage.
    try:
        (root / "runtime" / "data" / ".session_nettoyee").write_text("1", encoding="utf-8")
    except OSError:
        pass
    if log:
        print("  [arret] Certification + archivage lances EN TACHE DE FOND (non bloquant).",
              flush=True)
        print("          Suivi en direct : double-clic  SUIVI_COFFRE.cmd  (%, debit, ETA)", flush=True)
        print(f"          (log brut : {log})", flush=True)
    else:
        print("  [arret] (scellage non lance : scripts absents)", flush=True)


def _attendre_ou_quitter(duree: float) -> bool:
    """Attend `duree` secondes ; renvoie True si l'utilisateur a appuye sur 'q'.

    Sur Windows, 'q' permet un arret PROPRE sans declencher le prompt cmd
    « Terminer le programme (O/N) ? » (qui, repondu O, tue le batch avant le
    nettoyage et laisse les collecteurs de fond orphelins).
    """
    try:
        import msvcrt  # Windows uniquement
    except ImportError:
        time.sleep(duree)
        return False
    fin = time.time() + duree
    while time.time() < fin:
        if msvcrt.kbhit():
            touche = msvcrt.getch()
            if touche in (b"q", b"Q"):
                return True
        time.sleep(0.05)
    return False


def _et(ok: bool) -> str:
    return "ACTIF " if ok else "arrete"


def boucle(data_dir: Path, *, intervalle: float = 2.0, n_derniers: int = 10) -> int:
    offsets: dict[str, int] = {}
    totaux: dict[str, int] = {}
    precedents: dict[str, int] = {}
    maj_ts: dict[str, float] = {}
    meta: dict[str, tuple[str, bool]] = {}   # path -> (label, est_fill)
    premiere_vue: set[str] = set()
    derniers_fills: list[str] = []
    total_initial: int | None = None
    try:
        while True:
            for fich in sorted(data_dir.glob("*.jsonl")):
                cle = str(fich)
                if cle not in meta:
                    meta[cle] = label_pour(fich.name)
                    totaux.setdefault(cle, 0)
                    precedents.setdefault(cle, 0)
                est_fill = meta[cle][1]
                try:
                    taille = fich.stat().st_size
                except OSError:
                    continue
                pos = offsets.get(cle, 0)
                if taille < pos:            # fichier reecrit -> repart de 0
                    pos = 0
                if taille <= pos:
                    offsets[cle] = pos
                    continue
                try:
                    with fich.open("r", encoding="utf-8", errors="replace") as fh:
                        fh.seek(pos)
                        nouveau = fh.read()
                        offsets[cle] = fh.tell()
                except OSError:
                    continue
                if nouveau.strip():
                    maj_ts[cle] = time.time()
                for ligne in nouveau.splitlines():
                    ligne = ligne.strip()
                    if not ligne:
                        continue
                    totaux[cle] += 1
                    if est_fill:
                        try:
                            obj = json.loads(ligne)
                        except (ValueError, TypeError):
                            continue
                        if isinstance(obj, dict):
                            txt = formater_fill(obj)
                            if txt:
                                derniers_fills.append(txt)
            derniers_fills[:] = derniers_fills[-n_derniers:]

            # --- rendu ---
            _cls()
            maintenant = time.time()
            print("=" * 74)
            print("  ALINA - ECRAN UNIQUE : TOUS LES COLLECTEURS + TOUTES LES DONNEES")
            print(f"  {time.strftime('%Y-%m-%d %H:%M:%S')}    >>> Appuyez sur  q  pour ARRETER proprement <<<")
            print("=" * 74)
            sup = (data_dir / "collecteurs.lock").exists()
            poll = (data_dir / "poll_leaders.pid").exists()
            expl = (data_dir / "explorer_autonome.pid").exists()
            print(f"  Superviseur: {_et(sup)}    Poll leaders: {_et(poll)}    "
                  f"Explorer auto: {_et(expl)}")
            print("-" * 74)

            actifs = sorted(meta, key=lambda c: (-(totaux.get(c, 0) > 0), -totaux.get(c, 0), c))
            grand_total = 0
            vides = 0
            for cle in actifs:
                label = meta[cle][0]
                t = totaux.get(cle, 0)
                grand_total += t
                if t == 0:
                    vides += 1
                    continue
                nom = os.path.basename(cle)
                cadence_lot = CADENCE_LOT.get(nom)
                if cadence_lot:   # flux par lot : "0.0/s" entre passes est NORMAL
                    premiere_vue.add(cle)
                    precedents[cle] = t
                    frais = _frais_lot(cle, cadence_lot, maj_ts.get(cle), maintenant)
                    print(f"    {label:<24} {t:>10d}  [{frais}]")
                    continue
                if cle not in premiere_vue:   # 1re frame : pas de debit gonfle par l'historique
                    premiere_vue.add(cle)
                    precedents[cle] = t
                    dps = 0.0
                else:
                    dps = (t - precedents.get(cle, 0)) / intervalle
                    precedents[cle] = t
                barre = "*" if dps > 0 else " "
                age = maintenant - maj_ts[cle] if cle in maj_ts else None
                if age is None:
                    frais = "    --   "
                elif age < intervalle * 1.5:
                    frais = "a l'instant"
                else:
                    frais = f"il y a {int(age):>4d}s"
                print(f"  {barre} {label:<24} {t:>10d}  ({dps:>6.1f}/s)  {frais}")
            if vides:
                print(f"    (+ {vides} flux encore vides, en attente de donnees)")
            if total_initial is None:
                total_initial = grand_total
            print("-" * 74)
            print(f"  TOTAL : {grand_total:>11d} enregistrements   |   "
                  f"NOUVEAUX cette session : {grand_total - total_initial:>8d}")
            print("=" * 74)
            print(f"  Derniers fills :")
            if derniers_fills:
                for f in derniers_fills:
                    print(f"   {f}")
            else:
                print("   (en attente de fills...)")
            print("=" * 74, flush=True)
            if _attendre_ou_quitter(intervalle):
                nettoyer_session(data_dir.parent.parent)
                return 0
    except KeyboardInterrupt:
        # Ctrl+C : on nettoie IMMEDIATEMENT depuis Python, avant que le prompt
        # « Terminer O/N ? » du .cmd ne puisse tuer le batch sans nettoyage.
        nettoyer_session(data_dir.parent.parent)
        return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Ecran unique temps reel de la collecte (lecture seule).")
    p.add_argument("--root", default=str(RACINE))
    p.add_argument("--intervalle", type=float, default=2.0)
    args = p.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    data_dir = Path(args.root) / "runtime" / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return boucle(data_dir, intervalle=max(0.5, args.intervalle))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
