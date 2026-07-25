"""VÉRIFICATEUR OOS SHADOW — LOCAL, STRICTEMENT READ-ONLY (rectif Flo 25/07).

Ce module LIT UNIQUEMENT des fichiers locaux (tape `shadow_l2_v3` + ledger `metaorder_shadow`).
Il **n'ouvre AUCUNE connexion réseau**, **ne relance rien**, **ne modifie pas le runtime** (collecteur,
moteur, config, config_hash RAW : tous intacts). Ses sorties vont dans un dossier de RAPPORTS séparé,
jamais dans `runtime/data/`.

Cadre PRÉ-ENREGISTRÉ et FIGÉ (forward-only), décidé par Flo :
  • population = JOINTURE `tape shadow_l2_v3` × `ledger metaorder_shadow`, par `metaorder_id` ;
  • filtre = stade LEDGER ∈ {CONTINUATION, LATE_STAGE}, OFI mesurable (tape), L2 éligible (tape), taker ;
  • unité statistique = `metaorder_id` unique (jamais les fills) ;
  • chronologie = 1ᵉʳ fill du métaordre L2-éligible+OFI-mesurable, `fill_exchange_time` > `t_prereg` ;
  • fenêtre A = les 30 premiers métaordres éligibles après `t_prereg` ;
  • embargo FIXE de 5 min ; fenêtre B = les 30 suivants dont `t_ordre ≥ A_fin + embargo` ;
  • le vérificateur AFFICHE seulement les compteurs tant que |B| < 30 ; à |B| = 30 il génère UNE seule
    fois le rapport préliminaire (bornes FIGÉES + `checkpoint_hash`), puis pose un verrou `.done`.
  • AUCUNE promotion si l'IC bas clusterisé (OOS, fenêtre B) n'est pas > 0.

Pas de re-découpage médian, pas d'arrêt opportuniste : les fenêtres sont définies par COMPTE (30 puis 30),
jamais par « quand le résultat est favorable ».
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path

# --- import des briques testées de metaorder_shadow (stats clusterisées, coûts L2) -----------------
_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
from hl_observer.experimental import metaorder_shadow as MS          # noqa: E402
from hl_observer.experimental import metaorder_l2_tape as MT          # noqa: E402

SCHEMA = "checkpoint_oos_shadow_v1"
TAILLE_FENETRE = 30
EMBARGO_MS = 300_000.0                    # embargo FIXE de 5 min entre A et B
PLAFOND_L2_MS = MT.LATENCE_PLAFOND_ELIGIBLE_MS
STADES_CIBLES = ("CONTINUATION", "LATE_STAGE")

TAPE_REL = Path("runtime") / "data" / "metaorder_l2_tape.jsonl"
LEDGER_REL = Path("runtime") / "data" / "metaorder_shadow_ledger.jsonl"
SORTIE_REL = Path("runtime") / "rapports" / "checkpoint_oos_shadow"   # RAPPORTS uniquement (pas runtime/data)


# ================================ pré-registration (immuable) =====================================
def _spec_canonique(t_prereg_ms: int) -> dict:
    return {
        "schema": SCHEMA,
        "t_prereg_ms": int(t_prereg_ms),
        "population": "jointure tape shadow_l2_v3 x ledger metaorder_shadow, par metaorder_id",
        "filtre": {"stade_in": list(STADES_CIBLES), "ofi_mesurable": True,
                   "l2_eligible": True, "maker_taker": "taker"},
        "unite": "metaorder_id",
        "chronologie": "1er fill du metaordre L2-eligible+OFI-mesurable, fill_exchange_time > t_prereg_ms",
        "fenetre_A": {"taille": TAILLE_FENETRE, "regle": "30 premiers metaordres eligibles apres t_prereg"},
        "embargo_ms": EMBARGO_MS,
        "fenetre_B": {"taille": TAILLE_FENETRE, "regle": "30 suivants dont t_ordre >= A_fin + embargo"},
        "eligibilite_l2": {"regle": "book_exchange_time >= fill_exchange_time ET 0 <= latence_pipeline_ms <= plafond",
                           "plafond_ms": PLAFOND_L2_MS},
        "horizon_ms": MS.HORIZON_FWD_MS,
        "fee_ar_base_bps": MS.FEE_AR_BASE_BPS,
        "fees_tiers": list(MS.FEES_TIERS_DEFAUT),
        "notionals": list(MS.NOTIONALS_DEFAUT),
        "copy_notional_usd": MS.COPY_NOTIONAL_USD,
        "regle_promotion": "AUCUNE promotion si IC bas clusterise (OOS fenetre B) <= 0",
        "one_shot": True,
        "note_immuable": "ecrit une seule fois; jamais recalcule; pas de re-decoupage median; pas d'arret opportuniste",
    }


def checkpoint_hash(spec: dict) -> str:
    """SHA-256 déterministe de la spec canonique (hors champs dérivés)."""
    canon = json.dumps({k: spec[k] for k in sorted(spec) if k not in ("checkpoint_hash", "checkpoint_id")},
                       sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def assurer_preregistration(sortie: Path, *, t_prereg_ms: int | None = None) -> dict:
    """Charge la pré-registration si elle existe ; sinon la CRÉE **une seule fois** (t_prereg = maintenant),
    puis la fige. Immuable : jamais réécrite si présente."""
    sortie.mkdir(parents=True, exist_ok=True)
    p = sortie / "preregistration.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    spec = _spec_canonique(t_prereg_ms if t_prereg_ms is not None else int(time.time() * 1000))
    h = checkpoint_hash(spec)
    spec["checkpoint_hash"] = h
    spec["checkpoint_id"] = "ckpt-oos-shadow-" + h[:12]
    spec["cree_ts_ms"] = int(time.time() * 1000)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(spec, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(p)                                                    # écriture atomique
    return spec


# ================================ chargement read-only ============================================
def _iter_jsonl(path: Path):
    if not path.exists():
        return
    with path.open(encoding="utf-8", errors="ignore") as fh:
        for ligne in fh:
            ligne = ligne.strip()
            if not ligne:
                continue
            try:
                yield json.loads(ligne)
            except (ValueError, TypeError):
                continue


def eligibilite_tape(tape_path: Path, *, plafond_ms: float = PLAFOND_L2_MS) -> dict:
    """Par metaorder_id : plus TÔT `fill_exchange_time` d'un fill **L2-éligible ET OFI mesurable** (OK),
    le signe OFI à cette entrée, et le carnet d'entrée BRUT (pour les coûts exécutables). Read-only."""
    out: dict = {}
    for d in _iter_jsonl(tape_path):
        if d.get("schema_version") != MT.SCHEMA_VERSION:
            continue
        if (d.get("type") or "fill") != "fill":
            continue
        mid = d.get("metaorder_id")
        if not mid:
            continue
        elig = MT.est_eligible(d, plafond_ms=plafond_ms)
        ofi_ok = d.get("ofi_statut") == "OK"
        if not (elig and ofi_ok):
            continue
        fe = d.get("fill_exchange_time")
        if not isinstance(fe, (int, float)):
            continue
        cur = out.get(mid)
        if cur is None or fe < cur["t_ordre"]:
            out[mid] = {"t_ordre": float(fe),
                        "ofi_signe": 1 if (d.get("ofi_top5") or 0) > 0 else (-1 if (d.get("ofi_top5") or 0) < 0 else 0),
                        "entree": d.get("entree")}
    return out


def _book_depuis_entree(entree: dict | None) -> dict | None:
    """Reconstruit un carnet {levels:[bids,asks]} depuis les niveaux BRUTS [px,sz,n] de la tape."""
    if not entree or not entree.get("bids") or not entree.get("asks"):
        return None
    def col(niv):
        return [{"px": str(x[0]), "sz": str(x[1])} for x in niv if isinstance(x, (list, tuple)) and len(x) >= 2]
    b, a = col(entree["bids"]), col(entree["asks"])
    return {"levels": [b, a]} if b and a else None


def slices_ledger_cibles(ledger_path: Path) -> dict:
    """Par metaorder_id : liste des slices LEDGER de stade CIBLE (CONTINUATION/LATE), taker, `pnl_net_bps`
    présent. Ces slices sont déjà au FORMAT `signaux` de metaorder_shadow (réutilisation directe)."""
    out: dict = {}
    for d in _iter_jsonl(ledger_path):
        if d.get("stade") not in STADES_CIBLES:
            continue
        if d.get("maker_taker") != "taker":
            continue
        if d.get("pnl_net_bps") is None:
            continue
        mid = d.get("metaorder_id")
        if not mid:
            continue
        out.setdefault(mid, []).append(d)
    return out


# ================================ population + fenêtres (figées) ===================================
def population_ordonnee(tape_idx: dict, ledger_idx: dict, *, t_prereg_ms: float) -> list:
    """Métaordres uniques de la JOINTURE, filtrés + FORWARD-only (t_ordre > t_prereg), triés chronologiquement.
    Chaque item : {metaorder_id, t_ordre, ofi_signe, entree(book brut), slices(ledger)}."""
    pop = []
    for mid, elig in tape_idx.items():
        slices = ledger_idx.get(mid)
        if not slices:                                               # doit exister des DEUX côtés (jointure)
            continue
        if elig["t_ordre"] <= t_prereg_ms:                          # STRICTEMENT après la pré-registration
            continue
        pop.append({"metaorder_id": mid, "t_ordre": elig["t_ordre"], "ofi_signe": elig["ofi_signe"],
                    "entree": elig["entree"], "slices": slices})
    pop.sort(key=lambda x: (x["t_ordre"], x["metaorder_id"]))        # tie-break déterministe
    return pop


def affecter_fenetres(pop: list, *, taille: int = TAILLE_FENETRE, embargo_ms: float = EMBARGO_MS) -> dict:
    """A = 30 premiers ; A_fin = t_ordre du 30ᵉ ; B = 30 premiers dont t_ordre >= A_fin + embargo.
    Défini par COMPTE (jamais par le résultat) → pas d'arrêt opportuniste. Bornes FIGÉES une fois pleines."""
    A = pop[:taille]
    a_complete = len(A) >= taille
    a_fin = A[-1]["t_ordre"] if a_complete else None
    seuil_b = (a_fin + embargo_ms) if a_complete else None
    reste = [p for p in pop[taille:] if seuil_b is not None and p["t_ordre"] >= seuil_b]
    B = reste[:taille]
    return {"A": A, "B": B, "a_complete": a_complete, "b_complete": len(B) >= taille,
            "a_fin_ts": a_fin, "seuil_b_ts": seuil_b,
            "nA": min(len(A), taille), "nB": len(B)}


def compteurs(prereg: dict, fen: dict) -> dict:
    """SEULEMENT des compteurs (aucun IC, PnL ni verdict tant que |B| < 30)."""
    return {
        "checkpoint_id": prereg.get("checkpoint_id"),
        "checkpoint_hash": prereg.get("checkpoint_hash"),
        "t_prereg_ms": prereg.get("t_prereg_ms"),
        "nA": fen["nA"], "cible_A": TAILLE_FENETRE, "A_complete": fen["a_complete"],
        "A_fin_ts": fen["a_fin_ts"], "embargo_ms": EMBARGO_MS, "seuil_B_ts": fen["seuil_b_ts"],
        "nB": fen["nB"], "cible_B": TAILLE_FENETRE, "B_complete": fen["b_complete"],
        "pret_pour_rapport": bool(fen["a_complete"] and fen["b_complete"]),
        "mesure_ts_ms": int(time.time() * 1000),
    }


# ================================ rapport préliminaire (one-shot) ==================================
def _signaux(items: list) -> list:
    """Aplati les slices ledger des métaordres d'une fenêtre → liste de `signaux` (format metaorder_shadow)."""
    out = []
    for it in items:
        out.extend(it["slices"])
    return out


def _ic_net(items: list) -> dict:
    """IC clusterisé (par metaorder_id) du PnL net des slices de la fenêtre."""
    paires = [(s.get("metaorder_id"), s.get("pnl_net_bps")) for it in items for s in it["slices"]
              if s.get("pnl_net_bps") is not None]
    return MS.bootstrap_clusterise(paires)


def _capacite_prouvee(items: list) -> dict:
    """Par palier de notional : net_i = alpha_i − coût_L2(notional) − frais ; IC bas clusterisé.
    Capacité prouvée = plus grand notional dont l'IC bas > 0 (sinon 0). Coût depuis le carnet d'entrée tape."""
    caps = {}
    for notional in MS.NOTIONALS_DEFAUT:
        paires = []
        for it in items:
            book = _book_depuis_entree(it.get("entree"))
            for s in it["slices"]:
                alpha = s.get("alpha_vs_marche_bps")
                sens = s.get("sens") or 0
                if alpha is None or not book:
                    continue
                comp = MS.cout_composants(book, notional, sens, MS.FEE_AR_BASE_BPS)
                if not comp:
                    continue
                net = alpha - comp["cout_ar_bps"]
                paires.append((s.get("metaorder_id"), net))
        boot = MS.bootstrap_clusterise(paires)
        caps[str(int(notional))] = {"net_moy_bps": boot["moy"], "ic_bas": boot["ic_bas"],
                                    "ic_haut": boot["ic_haut"], "n_metaordres": boot["n_clusters"]}
    prouvee = 0.0
    for notional in MS.NOTIONALS_DEFAUT:
        ic = caps[str(int(notional))]["ic_bas"]
        if ic is not None and ic > 0:
            prouvee = notional
    return {"par_palier": caps, "capacite_prouvee_usd": prouvee}


def generer_rapport(prereg: dict, fen: dict, sortie: Path) -> dict:
    """Génère UNE seule fois le rapport préliminaire (bornes figées). Idempotent via verrou `.done`.
    AUCUNE promotion si l'IC bas OOS (fenêtre B) n'est pas > 0."""
    done = sortie / ".rapport.done"
    if done.exists():
        return {"deja_genere": True}
    A, B = fen["A"], fen["B"]
    ic_A, ic_B = _ic_net(A), _ic_net(B)
    placebo_B = MS.bootstrap_clusterise(
        [(s.get("metaorder_id"), s.get("alpha_vs_marche_bps")) for it in B for s in it["slices"]
         if s.get("alpha_vs_marche_bps") is not None])
    par_stade_B = MS.stats_par_stade(_signaux(B))
    par_vault_B = MS.agreger_par(_signaux(B), "vault")
    par_coin_B = MS.agreger_par(_signaux(B), "coin")
    # avec / sans OFI (signe OFI mesuré à l'entrée, tape)
    B_ofi_pos = [it for it in B if it.get("ofi_signe", 0) > 0]
    B_ofi_neg = [it for it in B if it.get("ofi_signe", 0) <= 0]
    capa = _capacite_prouvee(B)
    ic_bas_B = ic_B.get("ic_bas")
    promu = bool(ic_bas_B is not None and ic_bas_B > 0 and capa["capacite_prouvee_usd"] > 0)
    verdict = "PROMOTION_POSSIBLE" if promu else "PAS_DE_PROMOTION_IC_BAS_NON_POSITIF"

    rapport = {
        "schema": SCHEMA, "checkpoint_id": prereg.get("checkpoint_id"),
        "checkpoint_hash": prereg.get("checkpoint_hash"),
        "genere_ts_ms": int(time.time() * 1000), "one_shot": True,
        "bornes_figees": {
            "t_prereg_ms": prereg.get("t_prereg_ms"),
            "A_debut_ts": A[0]["t_ordre"], "A_fin_ts": fen["a_fin_ts"],
            "embargo_ms": EMBARGO_MS, "B_seuil_ts": fen["seuil_b_ts"],
            "B_debut_ts": B[0]["t_ordre"], "B_fin_ts": B[-1]["t_ordre"],
            "A_metaorder_ids": [it["metaorder_id"] for it in A],
            "B_metaorder_ids": [it["metaorder_id"] for it in B],
        },
        "n_metaordres": {"A": len(A), "B": len(B)},
        "pnl_net_bps": {"A_ic": ic_A, "B_ic": ic_B},
        "roi_net_pct_B": (round(ic_B["moy"] / 100.0, 4) if ic_B.get("moy") is not None else None),
        "pnl_net_usd_moy_B": (round(ic_B["moy"] / 10000.0 * MS.COPY_NOTIONAL_USD, 4)
                              if ic_B.get("moy") is not None else None),
        "placebo_alpha_marche_B_ic": placebo_B,
        "couverture_l2_synchronisee": "100% par construction (population = fills L2-eligibles+OFI mesurable)",
        "resultats_avec_ofi_positif_B": _ic_net(B_ofi_pos), "resultats_sans_ofi_positif_B": _ic_net(B_ofi_neg),
        "par_stade_B": par_stade_B, "par_vault_B": par_vault_B, "par_coin_B": par_coin_B,
        "capacite": capa,
        "verdict": verdict,
        "regle": "PRÉLIMINAIRE — aucune promotion si l'IC bas clusterisé (OOS fenêtre B) n'est pas > 0.",
    }
    (sortie / "RAPPORT_OOS_SHADOW_PRELIMINAIRE.json").write_text(
        json.dumps(rapport, indent=2, ensure_ascii=False), encoding="utf-8")
    (sortie / "RAPPORT_OOS_SHADOW_PRELIMINAIRE.md").write_text(_markdown(rapport), encoding="utf-8")
    done.write_text(json.dumps({"genere_ts_ms": rapport["genere_ts_ms"],
                                "checkpoint_hash": rapport["checkpoint_hash"]}), encoding="utf-8")
    return rapport


def _markdown(r: dict) -> str:
    b = r["bornes_figees"]; icB = r["pnl_net_bps"]["B_ic"]
    L = [f"# Rapport OOS shadow — PRÉLIMINAIRE ({r['checkpoint_id']})", "",
         f"checkpoint_hash `{r['checkpoint_hash']}` · one-shot · bornes figées.", "",
         f"- Fenêtre A : {r['n_metaordres']['A']} métaordres · [{int(b['A_debut_ts'])} → {int(b['A_fin_ts'])}]",
         f"- Embargo : {int(b['embargo_ms']/1000)} s · seuil B {int(b['B_seuil_ts'])}",
         f"- Fenêtre B (OOS) : {r['n_metaordres']['B']} métaordres · [{int(b['B_debut_ts'])} → {int(b['B_fin_ts'])}]", "",
         "## PnL net (fenêtre B, OOS)",
         f"- moyenne {icB.get('moy')} bps · IC95 [{icB.get('ic_bas')} ; {icB.get('ic_haut')}] · "
         f"n_métaordres={icB.get('n_clusters')}",
         f"- ROI net ~{r.get('roi_net_pct_B')} % · PnL net moyen ~{r.get('pnl_net_usd_moy_B')} $ / métaordre "
         f"(copie {int(MS.COPY_NOTIONAL_USD)} $)",
         f"- Placebo alpha marché : IC95 [{r['placebo_alpha_marche_B_ic'].get('ic_bas')} ; "
         f"{r['placebo_alpha_marche_B_ic'].get('ic_haut')}]",
         f"- Avec OFI>0 : moy {r['resultats_avec_ofi_positif_B'].get('moy')} bps · "
         f"Sans : {r['resultats_sans_ofi_positif_B'].get('moy')} bps",
         f"- Capacité prouvée (IC bas>0) : **{r['capacite']['capacite_prouvee_usd']} $**", "",
         f"## Verdict : **{r['verdict']}**", "", r["regle"]]
    return "\n".join(L)


# ================================ CLI (read-only) =================================================
def executer(racine: str | Path) -> dict:
    """Point d'entrée read-only : (1) assure la pré-registration figée ; (2) join tape×ledger ;
    (3) fenêtres ; (4) compteurs ; (5) rapport one-shot si B=30. Ne renvoie QUE des compteurs tant que B<30."""
    racine = Path(racine)
    sortie = racine / SORTIE_REL
    prereg = assurer_preregistration(sortie)
    tape_idx = eligibilite_tape(racine / TAPE_REL)
    ledger_idx = slices_ledger_cibles(racine / LEDGER_REL)
    pop = population_ordonnee(tape_idx, ledger_idx, t_prereg_ms=prereg["t_prereg_ms"])
    fen = affecter_fenetres(pop)
    cpt = compteurs(prereg, fen)
    cpt["n_population_eligible"] = len(pop)
    (sortie / "status.json").write_text(json.dumps(cpt, indent=2, ensure_ascii=False), encoding="utf-8")
    if cpt["pret_pour_rapport"]:
        rap = generer_rapport(prereg, fen, sortie)
        cpt["rapport"] = "genere" if not rap.get("deja_genere") else "deja_present"
        cpt["verdict"] = rap.get("verdict")
    return cpt


def _racine_defaut() -> Path:
    for c in (Path(__file__).resolve().parents[1], Path.cwd()):
        if (c / TAPE_REL).exists() or (c / "runtime").exists():
            return c
    return Path(__file__).resolve().parents[1]


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Vérificateur OOS shadow — read-only, aucun réseau.")
    ap.add_argument("--racine", default=str(_racine_defaut()))
    args = ap.parse_args()
    c = executer(args.racine)
    print(f"[checkpoint OOS shadow] {c['checkpoint_id']}  hash={c['checkpoint_hash'][:12]}")
    print(f"  t_prereg={c['t_prereg_ms']}  population_eligible={c['n_population_eligible']}")
    print(f"  fenêtre A : {c['nA']}/{c['cible_A']}  (complète={c['A_complete']})")
    if c["A_complete"]:
        print(f"  embargo {int(EMBARGO_MS/1000)}s → seuil B={int(c['seuil_B_ts'])}")
    print(f"  fenêtre B : {c['nB']}/{c['cible_B']}  (complète={c['B_complete']})")
    print(f"  prêt pour rapport : {c['pret_pour_rapport']}"
          + (f"  → rapport {c.get('rapport')} · verdict {c.get('verdict')}" if c["pret_pour_rapport"] else ""))
    print("  SÉCURITÉ : read-only · 0 réseau · 0 ordre réel · runtime intact.")
