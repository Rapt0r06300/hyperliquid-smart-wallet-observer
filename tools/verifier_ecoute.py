#!/usr/bin/env python3
"""LES MODES DE PANNE DE L'ECOUTE 4 H -- verifies AVANT qu'ils ne coutent la nuit (2026-07-12).

POURQUOI CET OUTIL
------------------
Une mesure de 4 h qui echoue a 3 h 50 ne coute pas 10 minutes : elle coute la nuit entiere.
Et l'historique du projet est sans appel -- **les pannes de collecte ont TOUJOURS ete
SILENCIEUSES** :

  * le poller de carnet L2 n'a JAMAIS demarre (une liste vide, aucun log) ;
  * le recording des marks s'est arrete a 02h32 sans un mot ;
  * le runner WS mourait au 1er drop... et rendait quand meme un verdict.

Cet outil cherche donc les pannes AVANT, pas apres. Il ne repare rien : il CRIE.

CE QU'IL CONTROLE
-----------------
  1. le processus ecrit-il ENCORE (mtime frais) ?
  2. la borne dure de 200 Mo sera-t-elle atteinte ? (`ecrire()` s'arrete EN SILENCE au-dela)
  3. y a-t-il eu des TROUS dans le flux (deconnexions) ?
  4. le PC va-t-il se mettre en veille et couper le WebSocket ?
  5. KAITO atteindra-t-il les 300 fills dans la fenetre ?

LECTURE SEULE. Aucun ordre, aucune cle. JAMAIS.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hl_observer.backtesting.market_making_flow import (  # noqa: E402
    MIN_TRADES_POUR_CONCLURE,
    fenetre_continue_s,
)
from hl_observer.collection.trades_recorder import MAX_OCTETS  # noqa: E402

DUREE_ECOUTE_S = 240 * 60.0
PIECE = "KAITO"
SILENCE_ALERTE_S = 120.0        # 2 min sans une seule ecriture = anomalie
TROU_ALERTE_S = 60.0            # 1 min sans un seul trade (tous coins) = deconnexion probable


# ===================================================================== les fonctions PURES

def projection_taille(octets: float, ecoule_s: float, duree_s: float = DUREE_ECOUTE_S) -> dict[str, Any]:
    """La borne de 200 Mo sera-t-elle atteinte ? `ecrire()` s'arrete EN SILENCE au-dela.

    Ce n'est pas theorique : un fichier qui cesse d'etre ecrit sans un log, c'est exactement
    la panne du recording des marks (02h32) et celle du carnet L2.
    """
    if ecoule_s <= 0:
        return {"projection_octets": 0.0, "depassera": False, "marge_pct": 100.0}
    proj = octets / ecoule_s * duree_s
    return {
        "projection_octets": proj,
        "depassera": proj >= MAX_OCTETS,
        "marge_pct": max(0.0, 100.0 * (1.0 - proj / MAX_OCTETS)),
    }


def trous_du_flux(horodatages: Sequence[float], *, seuil_s: float = TROU_ALERTE_S) -> list[tuple[float, float]]:
    """(debut, duree) de chaque silence anormal. TOUS coins confondus.

    Sur 49 marches actifs, plus d'une minute sans le moindre trade n'est pas un marche calme :
    c'est une socket morte. Le reconnect doit avoir agi -- ce controle le PROUVE ou l'infirme.
    """
    ts = sorted(float(t) for t in horodatages)
    out = []
    for a, b in zip(ts, ts[1:]):
        if b - a > seuil_s:
            out.append((a, b - a))
    return out


def eta_fills(n_fills: int, fenetre_s: float, restant_s: float,
              cible: int = MIN_TRADES_POUR_CONCLURE) -> dict[str, Any]:
    """Le verdict tombera-t-il dans la fenetre ? Calcule sur le debit OBSERVE, jamais espere."""
    manque = max(0, cible - n_fills)
    if manque == 0:
        return {"eta_s": 0.0, "atteignable": True, "debit_par_min": 0.0}
    if fenetre_s <= 0 or n_fills <= 0:
        return {"eta_s": None, "atteignable": None, "debit_par_min": 0.0}
    debit = n_fills / (fenetre_s / 60.0)
    eta = manque / debit * 60.0
    return {"eta_s": eta, "atteignable": eta <= restant_s, "debit_par_min": debit}


# ===================================================================== les I/O

def _fichier_courant() -> Path | None:
    f = list(ROOT.glob("runtime/replay/trades*.jsonl"))
    return max(f, key=lambda p: p.stat().st_mtime) if f else None


def _veille_windows() -> str:
    """Le PC va-t-il s'endormir et couper le WebSocket ? LECTURE SEULE (on ne change RIEN)."""
    if os.name != "nt":
        return "non applicable (pas Windows)"
    try:
        out = subprocess.run(
            ["powercfg", "/query", "SCHEME_CURRENT", "SUB_SLEEP", "STANDBYIDLE"],
            capture_output=True, text=True, timeout=15, encoding="utf-8", errors="replace",
        ).stdout
    except Exception as exc:
        return "impossible a lire (%s)" % exc
    secondes = None
    for ligne in out.splitlines():
        if "AC Power Setting Index" in ligne or "secteur" in ligne.lower():
            try:
                secondes = int(ligne.split(":")[-1].strip(), 16)
            except ValueError:
                pass
    if secondes is None:
        return "indetermine"
    if secondes == 0:
        return "JAMAIS (bon : le WebSocket ne sera pas coupe)"
    return "APRES %d MIN -> DANGER : la veille coupera le WebSocket" % (secondes // 60)


def main() -> int:  # pragma: no cover  (I/O)
    print()
    print("=" * 74)
    print("  VERIFICATION DE L'ECOUTE -- chercher la panne AVANT qu'elle coute la nuit")
    print("=" * 74)

    f = _fichier_courant()
    if f is None:
        print("\n  [ECHEC] Aucun fichier trades*.jsonl. L'ecoute n'ecrit RIEN.\n")
        return 2

    alertes: list[str] = []
    maintenant = time.time()
    taille = f.stat().st_size
    age_ecriture = maintenant - f.stat().st_mtime

    # ---- lecture du fichier de la session courante
    ts_tous: list[float] = []
    kaito: list[dict] = []
    for ligne in f.open("r", encoding="utf-8", errors="ignore"):
        try:
            t = json.loads(ligne)
        except json.JSONDecodeError:
            continue
        if t.get("snapshot") or not t.get("ts"):
            continue
        ts_tous.append(float(t["ts"]))
        if t.get("coin") == PIECE:
            kaito.append(t)

    if not ts_tous:
        print("\n  [ECHEC] Le fichier existe mais ne contient aucun trade LIVE.\n")
        return 2

    debut = min(ts_tous)
    ecoule = maintenant - debut
    restant = max(0.0, DUREE_ECOUTE_S - ecoule)

    print("\n  Fichier   : %s" % f.name)
    print("  Demarree  : %s   fin prevue : %s"
          % (time.strftime("%Hh%M", time.localtime(debut)),
             time.strftime("%Hh%M", time.localtime(debut + DUREE_ECOUTE_S))))
    print("  Ecoulees  : %.0f min sur 240   (il reste %.0f min)" % (ecoule / 60, restant / 60))

    # ---- 1. le processus ecrit-il ENCORE ?
    print("\n  [1/5] Le processus ecrit-il encore ?")
    if age_ecriture > SILENCE_ALERTE_S:
        alertes.append("PLUS AUCUNE ECRITURE depuis %.0f s -- l'ecoute est MORTE ou gelee"
                       % age_ecriture)
        print("        !! DERNIERE ECRITURE IL Y A %.0f s -- ANORMAL" % age_ecriture)
    else:
        print("        OK -- derniere ecriture il y a %.0f s" % age_ecriture)

    # ---- 2. la borne de 200 Mo
    print("\n  [2/5] La borne dure de 200 Mo (au-dela, l'ecriture s'arrete EN SILENCE)")
    p = projection_taille(taille, ecoule)
    print("        %.2f Mo ecrits -> projection 4 h : %.1f Mo  (marge %.0f %%)"
          % (taille / 1e6, p["projection_octets"] / 1e6, p["marge_pct"]))
    if p["depassera"]:
        alertes.append("LA BORNE DE 200 Mo SERA ATTEINTE -- l'ecriture s'arretera SANS UN MOT")
        print("        !! DEPASSEMENT PREVU")
    else:
        print("        OK")

    # ---- 3. les trous du flux (= deconnexions)
    print("\n  [3/5] Trous dans le flux (une socket morte, sur 49 marches actifs)")
    trous = trous_du_flux(ts_tous)
    fenetre_reelle = fenetre_continue_s(ts_tous)
    if trous:
        perdu = sum(d for _, d in trous)
        print("        %d trou(s) > %.0f s, %.0f s perdues au total :" % (len(trous), TROU_ALERTE_S, perdu))
        for t0, d in trous[-5:]:
            print("          %s pendant %.0f s" % (time.strftime("%Hh%M:%S", time.localtime(t0)), d))
        if perdu > 0.20 * ecoule:
            alertes.append("PLUS DE 20 %% DU TEMPS D'ECOUTE EST PERDU EN TROUS -- reseau instable")
    else:
        print("        OK -- aucun trou : la connexion tient (le reconnect fait son travail)")
    print("        fenetre REELLEMENT observee : %.0f s (sur %.0f s ecoulees)"
          % (fenetre_reelle, ecoule))

    # ---- 4. la veille
    print("\n  [4/5] Mise en veille du PC (elle couperait le WebSocket)")
    v = _veille_windows()
    print("        %s" % v)
    if "DANGER" in v:
        alertes.append("LE PC SE METTRA EN VEILLE -- le WebSocket sera coupe. Regle-le AVANT "
                       "de dormir (Parametres > Alimentation > Veille = Jamais).")

    # ---- 5. KAITO atteindra-t-il 300 fills ?
    print("\n  [5/5] KAITO atteindra-t-il les %d fills necessaires pour CONCLURE ?"
          % MIN_TRADES_POUR_CONCLURE)
    notionnels = sorted(float(t.get("notional_usd") or 0.0) for t in kaito)
    if len(notionnels) < 4:
        print("        trop peu de trades KAITO pour estimer (%d)" % len(notionnels))
    else:
        seuil = notionnels[int(0.75 * len(notionnels))]
        derriere = [t for t in kaito if float(t.get("notional_usd") or 0.0) >= seuil]
        fen_k = fenetre_continue_s([float(t["ts"]) for t in kaito])
        e = eta_fills(len(derriere), fen_k, restant)
        print("        %d trades LIVE -> %d fills a la borne DERRIERE (seuil %.0f $)"
              % (len(kaito), len(derriere), seuil))
        if e["eta_s"] is None:
            print("        ETA : inconnu (aucun debit mesurable -- on n'extrapole PAS depuis rien)")
        else:
            print("        debit %.2f fill/min -> il faudrait encore %.0f min ; il en reste %.0f"
                  % (e["debit_par_min"], e["eta_s"] / 60, restant / 60))
            if not e["atteignable"]:
                alertes.append(
                    "KAITO N'ATTEINDRA PAS 300 FILLS EN 4 H (il faudrait ~%.0f h d'ecoute au "
                    "total). Ce n'est PAS une panne : c'est une reponse -- KAITO est trop peu "
                    "echange. Soit on prolonge l'ecoute, soit on l'accepte."
                    % ((ecoule + e["eta_s"]) / 3600))

    # ---- LE PIEGE
    print("\n" + "-" * 74)
    print("  LE PIEGE QUI NE SE VOIT PAS")
    print("-" * 74)
    print("  Le processus d'ecoute a charge le code Python A SON DEMARRAGE (21h28). Les")
    print("  correctifs ecrits APRES (fenetre continue, tolerance d'horizon, bornes de file)")
    print("  NE SONT PAS dans ce processus. Le verdict qu'il imprimera tout seul a la fin")
    print("  sera calcule avec l'ANCIEN moteur -- celui qui mesurait a travers les trous.")
    print()
    print("  >>> A LA FIN DE L'ECOUTE, LANCE `VERDICT-T1.cmd`. C'est LUI qui fait foi.")
    print("      (Il relit les memes fichiers, avec le code corrige.)")

    print("\n" + "=" * 74)
    if alertes:
        print("  %d POINT(S) A REGARDER :" % len(alertes))
        for a in alertes:
            print("    - %s" % a)
    else:
        print("  RIEN A SIGNALER : l'ecoute tient. Elle ira jusqu'au bout.")
    print("=" * 74 + "\n")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
