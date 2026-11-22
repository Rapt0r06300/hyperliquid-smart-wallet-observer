r"""LE MOTEUR EN DIRECT — ce qu'il voit, ce qu'il décide, ce qu'il apprend. Lecture seule, rafraîchi.

    tools\python\python.exe tools\moteur_en_direct.py            (Ctrl+C pour quitter)

Trois blocs :
1. les comptes PAPIER (ALPHA 300 USD, PROBE 100 USD, bac à sable 20 USD) : solde, positions, réalisé ;
2. les derniers signaux de leaders et la décision du moteur pour chacun, avec son motif ;
3. les trades FANTÔMES de l'apprentissage (règle du bac à sable simulée sur les vrais fills et les vrais
   prix), sur un compte fictif de 100 USD. Ils sont marqués FANTÔME : aucun n'est un trade du moteur.

Le moteur ne trade en papier réel que lorsqu'une avance est MESURÉE : tant que rien n'est prouvé,
l'écran montre surtout des refus motivés. C'est voulu, et c'est dit en tête d'écran.
Aucune écriture, aucun ordre, aucun réseau.
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import sys
import time
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
if str(RACINE / "src") not in sys.path:
    sys.path.insert(0, str(RACINE / "src"))

from hl_observer.experimental import cohortes as CO  # noqa: E402
from hl_observer.experimental import cycles_fantomes as CF  # noqa: E402

COMPTE_FANTOME_USD = 100.0
MISE_FANTOME_USD = 20.0


def _heure(ms) -> str:
    try:
        return time.strftime("%H:%M:%S", time.localtime(float(ms) / 1000))
    except (TypeError, ValueError, OSError):
        return "--:--:--"


def _queue(chemin: Path, octets: int = 2_000_000) -> list[dict]:
    try:
        with chemin.open("rb") as f:
            taille = f.seek(0, 2)
            f.seek(max(0, taille - octets))
            brut = f.read().decode("utf-8", errors="replace").splitlines()
    except OSError:
        return []
    if taille > octets:
        brut = brut[1:]
    out = []
    for ligne in brut:
        try:
            out.append(json.loads(ligne))
        except ValueError:
            continue
    return out


def comptes(root: Path) -> list[str]:
    lignes = []
    for c in (CO.ALPHA, CO.PROBE, CO.RAW_PROBE):
        try:
            st = CO.statut(c, root)
        except Exception as exc:  # noqa: BLE001
            lignes.append(f"  {c.nom:<16} illisible ({type(exc).__name__})")
            continue
        lignes.append(f"  {c.nom:<16} solde {st.get('equity_usd', 0):>8.2f} USD / {st.get('budget_usd', 0):>6.0f}"
                      f" | positions {st.get('positions_ouvertes', 0)} | realise {st.get('realise_total_usd', 0):+.2f} USD")
        for p in (st.get("positions") or [])[:5]:
            lignes.append(f"      ouverte : {p.get('coin')} {p.get('sens')} {p.get('notional_usd')} USD")
    return lignes


def signaux(root: Path, n: int) -> tuple[list[str], collections.Counter]:
    journal = [x for x in _queue(root / CF.JOURNAL) if str(x.get("dir", "")).startswith(("Open", "Close"))]
    par_fill: dict[str, dict] = {}
    for x in journal:
        cle = str(x.get("hash") or x.get("tid"))
        par_fill.setdefault(cle, {"x": x, "d": {}})["d"][x.get("cohorte")] = x.get("decision")
    motifs = collections.Counter()
    for v in par_fill.values():
        if str(v["x"].get("dir", "")).startswith("Open"):
            motifs[str(v["d"].get("RAW_PROBE"))] += 1
    lignes = []
    for v in list(par_fill.values())[-n:]:
        x, d = v["x"], v["d"]
        try:
            usd = abs(float(x.get("sz") or 0)) * float(x.get("px") or 0)
        except (TypeError, ValueError):
            usd = 0.0
        lignes.append(f"  {_heure(x.get('recu_ms'))} {str(x.get('vault_short') or '')[:10]} {x.get('dir', ''):<12}"
                      f"{str(x.get('coin')):<10}{usd:>10,.0f} USD | ALPHA {str(d.get('ALPHA'))[:22]:<22}"
                      f" PROBE {str(d.get('PROBE'))[:22]:<22} BAC {str(d.get('RAW_PROBE'))[:26]}")
    return lignes, motifs


def fantomes(root: Path, n: int) -> list[str]:
    try:
        from hl_observer.experimental.copy_edge_forward import charger_prix_tape
        tape = charger_prix_tape(root) or {}
    except Exception:  # noqa: BLE001
        tape = {}
    sim = CF.simuler(CF.lire_journal(root), tape, CF.tvl_par_vault(root), frac_tvl=0.002, stop_bps=40.0,
                     horizon_ms=900_000.0, depuis_ms=0, now_ms=time.time() * 1000,
                     notional_usd=MISE_FANTOME_USD, etiquette="direct")
    cycles = sim["cycles"]
    solde = COMPTE_FANTOME_USD + sum(c["realized_usd"] for c in cycles)
    gagnants = sum(1 for c in cycles if c["realized_usd"] > 0)
    lignes = [f"  compte FANTOME {COMPTE_FANTOME_USD:.0f} USD, mise {MISE_FANTOME_USD:.0f} USD par trade, cout {CF.COUT_BPS:.0f} bps"
              f" | {len(cycles)} trades | gagnants {gagnants} | solde {solde:.2f} USD ({solde - COMPTE_FANTOME_USD:+.2f})"
              f" | en attente de resolution : {sim['compte']['trop_recents']}"]
    for c in cycles[-n:]:
        lignes.append(f"  FANTOME {_heure(c['entree_ms'])}->{_heure(c['sortie_ms'])} {c['coin']:<10}"
                      f"{'LONG ' if c['sens'] > 0 else 'SHORT'} {c['motif_sortie']:<14} brut {c['brut_bps']:>+7.1f} bps"
                      f" -> {c['realized_usd']:+.4f} USD")
    return lignes


def apprentissage(root: Path) -> list[str]:
    try:
        e = json.loads((root / "runtime" / "auto_amelioration" / "parallele_etat.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ["  apprentissage parallele : pas encore de passage (il tourne dans la passe du moteur)"]
    v = e.get("verdict") or {}
    d = e.get("decision") or {}
    lignes = [f"  depuis {_heure(e.get('debut_ms'))} | fills juges {e.get('fills_inscrits')} | variantes en lice {v.get('en_lice')}"
              f" | jours {v.get('jours_vus')} | decision {d.get('action')} — {d.get('motif')}"]
    for lab, b in list((e.get("meilleures") or {}).items())[:3]:
        lignes.append(f"    {lab:<34} {b.get('cycles')} cycles / {b.get('jours')} j | moyenne {b.get('moyenne_usd')}"
                      f" | borne basse {b.get('bas')}")
    return lignes


def ecran(root: Path, n: int) -> str:
    sig, motifs = signaux(root, n)
    blocs = [
        f"MOTEUR EN DIRECT — PAPIER, aucun ordre reel — {time.strftime('%H:%M:%S')}",
        "Le moteur ne trade en papier que si une avance est MESUREE ; sinon il refuse, avec un motif.",
        "", "COMPTES PAPIER", *comptes(root),
        "", f"DERNIERS SIGNAUX DE LEADERS ({n}) ET DECISIONS", *sig,
        "  decisions du bac a sable sur les ouvertures : " + ", ".join(f"{k} x{v}" for k, v in motifs.most_common(5)),
        "", "TRADES FANTOMES (simulation de la regle du bac a sable, 15 min, sortie miroir)", *fantomes(root, n),
        "", "APPRENTISSAGE PARALLELE (45 variantes)", *apprentissage(root),
    ]
    return "\n".join(blocs)


def main(argv: list[str] | None = None) -> int:
    for flux in (sys.stdout, sys.stderr):
        try:  # noqa: SIM105
            flux.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--racine", default=str(RACINE))
    p.add_argument("--lignes", type=int, default=12)
    p.add_argument("--intervalle", type=float, default=15.0)
    p.add_argument("--une-fois", action="store_true")
    a = p.parse_args(argv)
    root = Path(a.racine)
    try:
        while True:
            texte = ecran(root, a.lignes)
            if not a.une_fois:
                os.system("cls" if os.name == "nt" else "clear")
            print(texte, flush=True)
            if a.une_fois:
                return 0
            time.sleep(max(2.0, a.intervalle))
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
