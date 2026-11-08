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


def nettoyer_session(root: Path) -> None:
    """Arrêt PROPRE piloté par Python (robuste au piège Ctrl+C du .cmd).

    Fait TOUT le nettoyage ici — avant que le batch puisse être tué par la réponse
    O au prompt « Terminer O/N ? » : stoppe les collecteurs, dépose au coffre certifié,
    remet la session à zéro (archive), génère le rapport. Idempotent.
    """
    global _nettoyage_fait
    if _nettoyage_fait:
        return
    _nettoyage_fait = True
    data = root / "runtime" / "data"
    env = {**os.environ, "PYTHONPATH": str(root / "src"), "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}

    def _py(rel: str, *args: str, timeout: float = 240) -> None:
        cible = root / rel
        if not cible.exists():
            return
        try:
            subprocess.run([sys.executable, "-B", str(cible), "--root", str(root), *args],
                           cwd=str(root), env=env, timeout=timeout,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except (OSError, subprocess.SubprocessError):
            pass

    def _kill(*cmd: str) -> None:
        try:
            subprocess.run(list(cmd), timeout=30, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except (OSError, subprocess.SubprocessError):
            pass

    print("\n  [arret] Stop des collecteurs, CERTIFICATION (runtime/data -> coffre_certifie), "
          "reset et rapport...", flush=True)
    try:
        (data / "stop_collecteurs.flag").write_text("1", encoding="utf-8")
    except OSError:
        pass
    # 1) stopper les collecteurs (lease invalide + workers), puis explorer/poll/superviseur
    _py("tools/watch_economic_collectors.py", "--stop", timeout=60)
    for pidf in ("explorer_autonome.pid", "poll_leaders.pid"):
        p = data / pidf
        try:
            pid = p.read_text(encoding="utf-8").strip()
            if pid:
                _kill("taskkill", "/PID", pid, "/T", "/F")
            p.unlink()
        except OSError:
            pass
    for titre in ("ALINA-SUPERVISOR", "ALINA-EXPLORER-AUTO", "ALINA-POLL-LEADERS"):
        _kill("taskkill", "/FI", f"WINDOWTITLE eq {titre}*", "/T", "/F")
    # 2) certifier -> coffre, 3) archiver (reset a zero), 4) rapport
    _py("tools/sceller_coffre_local.py")
    _py("tools/archiver_tapes.py")
    _py("tools/rapport_collecteurs.py")
    try:
        (data / "collecteurs.lock").unlink()
        (data / "stop_collecteurs.flag").unlink()
    except OSError:
        pass
    print("  [arret] TERMINE. runtime/data certifie -> runtime/coffre_certifie (le labo y lit), "
          "session reset, rapport: runtime/logs/rapport_collecteurs.log", flush=True)


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
