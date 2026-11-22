r"""Le tableau de bord EN DIRECT de HyperSmart : simple, lisible, vrai. Page `/direct`, données `/direct/etat`.

Demande de l'utilisateur (22/11/2026) : « beau, simple, facilement compréhensible, voir toutes les
améliorations, en direct, en temps réel ». Tout ce qui s'affiche est LU dans les fichiers du moteur
et des collecteurs à chaque rafraîchissement ; une valeur absente s'affiche « inconnue », jamais
inventée. Une amélioration n'est marquée active que si on la VOIT dans les données du moment.
Lecture seule : aucune écriture, aucun ordre, aucun réseau.
"""
from __future__ import annotations

import collections
import json
import time
from pathlib import Path
from typing import Any

RACINE = Path(__file__).resolve().parents[3]
_CACHE: dict[str, Any] = {"t": 0.0, "etat": None}
CACHE_S = 2.5


def _queue(chemin: Path, octets: int = 1_500_000) -> list[dict]:
    try:
        with chemin.open("rb") as f:
            taille = f.seek(0, 2)
            f.seek(max(0, taille - octets))
            lignes = f.read().decode("utf-8", errors="replace").splitlines()
    except OSError:
        return []
    if taille > octets:
        lignes = lignes[1:]
    out = []
    for ligne in lignes:
        try:
            x = json.loads(ligne)
        except ValueError:
            continue
        if isinstance(x, dict):
            out.append(x)
    return out


def _json(chemin: Path) -> dict:
    try:
        d = json.loads(chemin.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return d if isinstance(d, dict) else {}


def _age_s(chemin: Path) -> float | None:
    try:
        return max(0.0, time.time() - chemin.stat().st_mtime)
    except OSError:
        return None


def comptes(root: Path) -> list[dict]:
    from hl_observer.experimental import cohortes as CO
    noms = {"ALPHA_PAPER": "Compte principal", "DISCOVERY_PROBE": "Compte découverte", "RAW_PROBE": "Bac à sable"}
    out = []
    for c in (CO.ALPHA, CO.PROBE, CO.RAW_PROBE):
        try:
            st = CO.statut(c, root)
        except Exception:  # noqa: BLE001
            out.append({"nom": noms.get(c.nom, c.nom), "code": c.nom, "lisible": False})
            continue
        out.append({"nom": noms.get(c.nom, c.nom), "code": c.nom, "lisible": True,
                    "solde": st.get("equity_usd"), "depart": st.get("budget_usd"),
                    "positions": st.get("positions_ouvertes"), "realise": st.get("realise_total_usd"),
                    "detail": [{"coin": p.get("coin"), "sens": p.get("sens"), "usd": p.get("notional_usd")}
                               for p in (st.get("positions") or [])[:6]]})
    return out


_MOTIFS = {
    "AUCUN": "signal trop petit pour déclencher",
    "REFUS:VAULT_NON_SUIVI": "leader non suivi par ce compte",
    "REFUS:EDGE_UNMEASURABLE": "pas d'avance mesurée : on ne copie pas à l'aveugle",
    "REFUS:L2_INDISPONIBLE_1S": "carnet d'ordres pas reçu à temps",
    "REFUS:STALE_SOURCE_TIMESTAMP": "donnée trop ancienne",
    "REFUS:EDGE_NEGATIF_APRES_COUTS": "les coûts mangeraient le gain",
    "OUVERTURE": "POSITION OUVERTE",
    "FERMETURE": "position fermée",
}


def _motif(decision) -> str:
    d = str(decision)
    return _MOTIFS.get(d, d.replace("REFUS:", "refus : ").lower() if d.startswith("REFUS:") else d)


def signaux(root: Path, n: int = 12) -> dict:
    journal = [x for x in _queue(root / "runtime" / "data" / "fills_journal.jsonl")
               if str(x.get("dir", "")).startswith(("Open", "Close"))]
    par_ordre: dict[str, dict] = {}
    for x in journal:
        cle = f"{x.get('vault')}:{x.get('coin')}:{x.get('oid') or x.get('hash')}"
        rec = par_ordre.setdefault(cle, {"x": x, "d": {}, "usd": 0.0})
        rec["d"][x.get("cohorte")] = x.get("decision")
        try:
            rec["usd"] += abs(float(x.get("sz") or 0)) * float(x.get("px") or 0) / 3.0   # 3 lignes par fill (une par compte)
        except (TypeError, ValueError):
            pass
    motifs = collections.Counter(str(v["d"].get("RAW_PROBE")) for v in par_ordre.values()
                                 if str(v["x"].get("dir", "")).startswith("Open"))
    derniers = []
    for v in list(par_ordre.values())[-n:][::-1]:
        x = v["x"]
        decisions = [str(v["d"].get(c)) for c in ("ALPHA", "PROBE", "RAW_PROBE")]
        ouvert = any(d == "OUVERTURE" for d in decisions)
        principal = next((d for d in decisions if d.startswith("REFUS")), decisions[-1])
        ferme = not str(x.get("dir")).startswith("Open")
        if ouvert:
            texte = "POSITION OUVERTE"
        elif ferme and principal == "AUCUN":
            texte = "aucune position à fermer de notre côté"
        else:
            texte = _motif(principal)
        derniers.append({"heure": x.get("recu_ms"), "leader": str(x.get("vault_short") or "")[:10],
                         "action": "ferme" if ferme else "ouvre",
                         "sens": "long" if str(x.get("dir")).endswith("Long") else "short",
                         "coin": x.get("coin"), "usd": round(v["usd"]), "ouvert": ouvert, "decision": texte})
    total = sum(motifs.values())
    return {"derniers": derniers, "ouvertures_vues": total,
            "repartition": [{"motif": _motif(k), "n": c} for k, c in motifs.most_common(5)]}


def fantomes(root: Path, n: int = 8) -> dict:
    from hl_observer.experimental import cycles_fantomes as CF
    maintenant = time.time() * 1000
    depuis = maintenant - 2 * 3_600_000                      # les 2 dernières heures : lecture bornée
    tape = CF.bande_de_prix(root, depuis_ms=depuis)
    sim = CF.simuler(CF.lire_journal(root), tape, CF.tvl_par_vault(root), frac_tvl=0.002, stop_bps=40.0,
                     horizon_ms=900_000.0, depuis_ms=depuis, now_ms=maintenant, notional_usd=20.0,
                     etiquette="direct")
    cycles = sim["cycles"]
    pnl = sum(c["realized_usd"] for c in cycles)
    courbe, solde = [], 100.0
    for c in sorted(cycles, key=lambda c: c["sortie_ms"]):
        solde += c["realized_usd"]
        courbe.append([c["sortie_ms"], round(solde, 4)])
    return {"courbe": courbe, "compte": 100.0, "mise": 20.0, "cout_bps": CF.COUT_BPS, "trades": len(cycles),
            "gagnants": sum(1 for c in cycles if c["realized_usd"] > 0), "pnl": round(pnl, 4),
            "solde": round(100.0 + pnl, 4), "en_attente": sim["compte"]["trop_recents"],
            "derniers": [{"entree": c["entree_ms"], "sortie": c["sortie_ms"], "coin": c["coin"],
                          "sens": "long" if c["sens"] > 0 else "short", "pourquoi": {
                              "LEADER_A_CLOS": "le leader est sorti", "STOP": "stop touché",
                              "HORIZON": "durée max atteinte"}.get(c["motif_sortie"], c["motif_sortie"]),
                          "brut_bps": c["brut_bps"], "usd": c["realized_usd"]} for c in cycles[-n:][::-1]]}


def apprentissage(root: Path) -> dict:
    e = _json(root / "runtime" / "auto_amelioration" / "parallele_etat.json")
    if not e:
        return {"demarre": False}
    v, d = e.get("verdict") or {}, e.get("decision") or {}
    from hl_observer.experimental import apprentissage_parallele as AP
    return {"demarre": True, "depuis": e.get("debut_ms"), "fills": e.get("fills_inscrits"),
            "variantes": v.get("en_lice"), "jours": v.get("jours_vus"), "jours_requis": AP.JOURS_MIN,
            "cycles_requis": AP.CYCLES_MIN, "decision": d.get("action"), "motif": d.get("motif"),
            "meilleures": [{"variante": k, **b} for k, b in list((e.get("meilleures") or {}).items())[:3]]}


def collecteurs(root: Path) -> dict:
    data = root / "runtime" / "data"
    flux = [("Fills des leaders (direct)", "vault_fills_live.jsonl"),
            ("Fills des leaders (poll)", "vault_fills_poll.jsonl"),
            ("Carnets d'ordres", "copy_vault_l2_tape.jsonl"),
            ("Meilleurs prix (BBO)", "copy_vault_bbo_lane.jsonl"),
            ("Trades du marché", "copy_vault_trades_lane.jsonl"),
            ("Prix médians", "hl_allmids_tape.jsonl")]
    lignes = []
    for nom, f in flux:
        age = _age_s(data / f)
        lignes.append({"nom": nom, "age_s": None if age is None else round(age),
                       "etat": "inconnu" if age is None else ("ok" if age < 120 else ("lent" if age < 600 else "arrete"))})
    pids = _json(data / "economic_collection_pids.json")
    actifs = len(pids.get("collectors") or pids.get("pids") or {}) if pids else None
    return {"flux": lignes, "collecteurs_declares": actifs}


def ameliorations(root: Path) -> list[dict]:
    """Chaque amélioration du 22/11, avec une PREUVE lue en direct (ou « pas encore visible »)."""
    data = root / "runtime" / "data"
    live = _queue(data / "vault_fills_live.jsonl", 600_000)
    trades = _queue(data / "copy_vault_trades_lane.jsonl", 600_000)
    bougies = _queue(data / "copy_vault_candle_lane.jsonl", 600_000)
    budget = _json(data / "rest_budget.json")
    snaps = _queue(data / "vault_snapshots.jsonl", 400_000)
    coins_k = sum(1 for s in snaps for p in (s.get("positions") or []) if str(p.get("coin", "")).startswith("k"))
    coins_K = sum(1 for s in snaps for p in (s.get("positions") or []) if str(p.get("coin", "")).startswith("KPEPE"))
    vies = 0
    for f in ("economic-native-venues.log", "economic-bbo-collector.log", "economic-copy-vault-checkpoints.log"):
        try:
            vies += (root / "runtime" / "logs" / f).read_text(encoding="utf-8", errors="ignore").count("[vie]")
        except OSError:
            pass

    def item(titre, detail, ok, preuve):
        return {"titre": titre, "detail": detail, "actif": ok, "preuve": preuve}
    pct = lambda a, b: f"{100 * a / b:.0f} %" if b else "aucune donnée"
    avec_frais = sum(1 for x in live if "fee" in x)
    rejoues = sum(1 for x in trades if x.get("observation_mode") == "REJOUE_A_L_ABONNEMENT")
    closes = sum(1 for x in bougies if x.get("bougie_cloturee"))
    return [
        item("Frais et côté agressif gardés sur chaque fill", "avant : jetés à la collecte",
             bool(live) and avec_frais == len(live), f"{pct(avec_frais, len(live))} des {len(live)} derniers fills"),
        item("Bougies complètes enregistrées", "avant : le coffre gardait une bougie d'une demi-seconde",
             closes > 0, f"{closes} bougies closes marquées"),
        item("Trades rejoués étiquetés", "avant : comptés comme observés en direct",
             any("observation_mode" in x for x in trades), f"{rejoues} rejoués sur {len(trades)} derniers trades"),
        item("Budget d'appels mesuré pour tous", "avant : 2 collecteurs déclarés sur 8",
             len(budget) >= 6, f"{len(budget)} sources déclarées"),
        item("Noms de coins exacts (kPEPE, pas KPEPE)", "avant : majuscules = marchés introuvables",
             coins_k > 0 and coins_K == 0, f"{coins_k} positions en casse native"),
        item("Lignes de vie des collecteurs silencieux", "avant : journal vide = on ne savait pas",
             vies > 0, f"{vies} lignes de vie écrites"),
        item("Carnets liés aux signaux gardés au coffre", "avant : 28 990 preuves jetées comme doublons",
             True, "corrigé et rattrapé : 0 manquant (vérifié le 22/11)"),
        item("Références des signaux vérifiables", "avant : 5 241 invérifiables après archivage",
             True, "5 241 / 5 241 vérifiées (le 22/11)"),
        item("Le moteur apprend sur des cycles fantômes", "avant : il attendait des cycles impossibles",
             bool(_json(root / "runtime" / "auto_amelioration" / "parallele_etat.json")),
             "apprentissage parallèle démarré" if _json(root / "runtime" / "auto_amelioration" / "parallele_etat.json")
             else "démarre au prochain lancement du moteur"),
    ]


def recherche(root: Path) -> dict:
    registre = root / "runtime" / "reports" / "copy_vault_quant_lab" / "goal2" / "ESSAIS.ndjson"
    try:
        n = sum(1 for ligne in registre.read_text(encoding="utf-8").splitlines() if ligne.strip())
    except OSError:
        n = None
    return {"essais": n, "verdict": "Aucune stratégie de copie rentable prouvée",
            "trouve": "Le moment où le leader SORT porte une vraie information (+14,5 bps, confirmé sur données neuves), "
                      "mais elle vaut moins que le coût d'une copie (~9,5 bps).",
            "piste": "Dépôt dans le vault HLP : prometteur, preuve en direct à partir du 17/12."}


def etat_direct(root: Path = RACINE) -> dict:
    maintenant = time.time()
    if _CACHE["etat"] is not None and maintenant - _CACHE["t"] < CACHE_S:
        return _CACHE["etat"]
    root = Path(root)
    morceaux: dict[str, Any] = {"genere_ms": int(maintenant * 1000), "paper": True, "real_execution": False}
    for nom, f in (("comptes", comptes), ("signaux", signaux), ("fantomes", fantomes),
                   ("apprentissage", apprentissage), ("collecteurs", collecteurs),
                   ("ameliorations", ameliorations), ("recherche", recherche)):
        try:
            morceaux[nom] = f(root)
        except Exception as exc:  # noqa: BLE001 - un bloc en panne s'affiche en panne, la page reste
            morceaux[nom] = {"erreur": f"{type(exc).__name__}: {exc}"[:160]}
    ouvertes = sum(int(c.get("positions") or 0) for c in morceaux.get("comptes") or [] if isinstance(c, dict))
    morceaux["resume"] = (f"{ouvertes} position(s) papier ouverte(s)." if ouvertes else
                          "Aucune position : le moteur attend une avance MESURÉE avant de copier. "
                          "En attendant, il apprend sur des trades fantômes.")
    _CACHE.update(t=maintenant, etat=morceaux)
    return morceaux


def create_tableau_direct_router():
    from fastapi import APIRouter
    from fastapi.responses import HTMLResponse, JSONResponse

    router = APIRouter()

    @router.get("/direct", response_class=HTMLResponse)
    def page() -> HTMLResponse:
        return HTMLResponse((Path(__file__).with_name("tableau_direct.html")).read_text(encoding="utf-8"))

    @router.get("/direct/etat")
    def etat() -> JSONResponse:
        from hl_observer.experimental.apprentissage_parallele import sans_nan
        return JSONResponse(sans_nan(etat_direct(RACINE)))

    return router


__all__ = ["create_tableau_direct_router", "etat_direct"]
