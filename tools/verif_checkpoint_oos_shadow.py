"""VÉRIFICATEUR OOS SHADOW — 100 % LOCAL, STRICTEMENT READ-ONLY (rectif Flo 25/07).

Conçu pour être lancé par le **Planificateur de tâches Windows** toutes les 30 min. Le chemin par défaut
(compteurs) n'utilise que la **bibliothèque standard** : AUCUN modèle Claude, AUCUN appel API, AUCUN réseau,
AUCUNE modification du runtime (collecteur/moteur/config/config_hash RAW intacts), AUCUN redémarrage.

À chaque exécution il :
  1. lit UNIQUEMENT des fichiers locaux (tape `shadow_l2_v3` + ledger `metaorder_shadow`) ;
  2. joint par `metaorder_id` et applique la pré-registration FIGÉE (forward-only) ;
  3. met à jour les compteurs A/B dans `status.json` ;
  4. crée **une seule fois** `CHECKPOINT_OOS_ATTEINT.txt` (+ `bornes_figees.json`) quand la fenêtre B
     atteint 30 — SANS calculer d'IC/PnL/verdict.

L'ANALYSE (IC clusterisé, coûts exécutables, placebo, capacité, avec/sans OFI) est faite SÉPARÉMENT par
Claude en mode `--rapport` UNIQUEMENT après l'apparition de la sentinelle. Le vérificateur non surveillé
ne l'exécute jamais (import de metaorder_shadow différé au seul mode `--rapport`).

Cadre PRÉ-ENREGISTRÉ et FIGÉ : population = jointure tape×ledger ; stade LEDGER ∈ {CONTINUATION, LATE_STAGE} ;
OFI mesurable + L2 éligible (tape) ; taker ; unité = `metaorder_id` unique ; chronologie = 1ᵉʳ fill éligible
> t_prereg ; fenêtre A = 30 premiers ; embargo FIXE 5 min ; fenêtre B = 30 suivants. Pas de re-découpage,
pas d'arrêt opportuniste (fenêtres définies par COMPTE). AUCUNE promotion si l'IC bas OOS n'est pas > 0.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

SCHEMA = "checkpoint_oos_shadow_v1"
SCHEMA_TAPE = "shadow_l2_v3"
TAILLE_FENETRE = 30
EMBARGO_MS = 300_000.0                     # embargo FIXE de 5 min entre A et B
PLAFOND_L2_MS = 2000.0                     # plafond de latence pipeline pour l'éligibilité L2 (pré-enregistré)
HORIZON_FWD_MS = 300_000.0
FEE_AR_BASE_BPS = 9.0                      # scénario conservateur (taker A/R)
FEES_TIERS = (9.0, 7.0, 5.0)
NOTIONALS = (10.0, 25.0, 50.0, 100.0, 250.0, 500.0)
COPY_NOTIONAL_USD = 500.0
STADES_CIBLES = ("CONTINUATION", "LATE_STAGE")

TAPE_REL = Path("runtime") / "data" / "metaorder_l2_tape.jsonl"
LEDGER_REL = Path("runtime") / "data" / "metaorder_shadow_ledger.jsonl"
SORTIE_REL = Path("runtime") / "rapports" / "checkpoint_oos_shadow"   # RAPPORTS uniquement (jamais runtime/data)


# ================================ pré-registration (immuable) =====================================
def _spec_canonique(t_prereg_ms: int) -> dict:
    return {
        "schema": SCHEMA, "t_prereg_ms": int(t_prereg_ms),
        "population": "jointure tape shadow_l2_v3 x ledger metaorder_shadow, par metaorder_id",
        "filtre": {"stade_in": list(STADES_CIBLES), "ofi_mesurable": True, "l2_eligible": True,
                   "maker_taker": "taker"},
        "unite": "metaorder_id",
        "chronologie": "1er fill du metaordre L2-eligible+OFI-mesurable, fill_exchange_time > t_prereg_ms",
        "fenetre_A": {"taille": TAILLE_FENETRE, "regle": "30 premiers metaordres eligibles apres t_prereg"},
        "embargo_ms": EMBARGO_MS,
        "fenetre_B": {"taille": TAILLE_FENETRE, "regle": "30 suivants dont t_ordre >= A_fin + embargo"},
        "eligibilite_l2": {"regle": "book_exchange_time >= fill_exchange_time ET 0 <= latence_pipeline_ms <= plafond",
                           "plafond_ms": PLAFOND_L2_MS},
        "horizon_ms": HORIZON_FWD_MS, "fee_ar_base_bps": FEE_AR_BASE_BPS, "fees_tiers": list(FEES_TIERS),
        "notionals": list(NOTIONALS), "copy_notional_usd": COPY_NOTIONAL_USD,
        "regle_promotion": "AUCUNE promotion si IC bas clusterise (OOS fenetre B) <= 0",
        "one_shot": True,
        "note_immuable": "ecrit une seule fois; pas de re-decoupage median; pas d'arret opportuniste",
    }


def checkpoint_hash(spec: dict) -> str:
    canon = json.dumps({k: spec[k] for k in sorted(spec) if k not in ("checkpoint_hash", "checkpoint_id")},
                       sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def assurer_preregistration(sortie: Path, *, t_prereg_ms: int | None = None) -> dict:
    """Charge la pré-registration si présente ; sinon la CRÉE une seule fois (t_prereg = maintenant) et la fige."""
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
    tmp.replace(p)
    return spec


# ================================ lecture read-only (stdlib pur) ==================================
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


def _tape_eligible(d: dict, *, plafond_ms: float = PLAFOND_L2_MS) -> bool:
    """Éligibilité L2 (inline, sans dépendance) : carnet postérieur au fill ET latence pipeline 0..plafond."""
    fe, be, lat = d.get("fill_exchange_time"), d.get("book_exchange_time"), d.get("latence_pipeline_ms")
    return (isinstance(fe, (int, float)) and isinstance(be, (int, float)) and be >= fe
            and isinstance(lat, (int, float)) and 0.0 <= lat <= plafond_ms)


def eligibilite_tape(tape_path: Path, *, plafond_ms: float = PLAFOND_L2_MS) -> dict:
    """Par metaorder_id : plus TÔT `fill_exchange_time` d'un fill **L2-éligible ET OFI mesurable** (OK),
    le signe OFI à cette entrée et le carnet d'entrée BRUT (pour les coûts, en mode rapport). Read-only."""
    out: dict = {}
    for d in _iter_jsonl(tape_path):
        if d.get("schema_version") != SCHEMA_TAPE or (d.get("type") or "fill") != "fill":
            continue
        mid = d.get("metaorder_id")
        if not mid or not (_tape_eligible(d, plafond_ms=plafond_ms) and d.get("ofi_statut") == "OK"):
            continue
        fe = float(d["fill_exchange_time"])
        cur = out.get(mid)
        if cur is None or fe < cur["t_ordre"]:
            of = d.get("ofi_top5") or 0
            out[mid] = {"t_ordre": fe, "ofi_signe": (1 if of > 0 else (-1 if of < 0 else 0)),
                        "entree": d.get("entree")}
    return out


def slices_ledger_cibles(ledger_path: Path) -> dict:
    """Par metaorder_id : slices LEDGER de stade CIBLE (CONTINUATION/LATE), taker, `pnl_net_bps` présent
    (déjà au format `signaux` de metaorder_shadow)."""
    out: dict = {}
    for d in _iter_jsonl(ledger_path):
        if d.get("stade") not in STADES_CIBLES or d.get("maker_taker") != "taker" or d.get("pnl_net_bps") is None:
            continue
        mid = d.get("metaorder_id")
        if mid:
            out.setdefault(mid, []).append(d)
    return out


# ================================ population + fenêtres (figées) ===================================
def population_ordonnee(tape_idx: dict, ledger_idx: dict, *, t_prereg_ms: float) -> list:
    pop = []
    for mid, elig in tape_idx.items():
        slices = ledger_idx.get(mid)
        if not slices or elig["t_ordre"] <= t_prereg_ms:            # jointure + STRICTEMENT après t_prereg
            continue
        pop.append({"metaorder_id": mid, "t_ordre": elig["t_ordre"], "ofi_signe": elig["ofi_signe"],
                    "entree": elig["entree"], "slices": slices})
    pop.sort(key=lambda x: (x["t_ordre"], x["metaorder_id"]))
    return pop


def affecter_fenetres(pop: list, *, taille: int = TAILLE_FENETRE, embargo_ms: float = EMBARGO_MS) -> dict:
    A = pop[:taille]
    a_complete = len(A) >= taille
    a_fin = A[-1]["t_ordre"] if a_complete else None
    seuil_b = (a_fin + embargo_ms) if a_complete else None
    reste = [p for p in pop[taille:] if seuil_b is not None and p["t_ordre"] >= seuil_b]
    B = reste[:taille]
    return {"A": A, "B": B, "a_complete": a_complete, "b_complete": len(B) >= taille,
            "a_fin_ts": a_fin, "seuil_b_ts": seuil_b, "nA": min(len(A), taille), "nB": len(B)}


def compteurs(prereg: dict, fen: dict, n_pop: int) -> dict:
    return {"checkpoint_id": prereg.get("checkpoint_id"), "checkpoint_hash": prereg.get("checkpoint_hash"),
            "t_prereg_ms": prereg.get("t_prereg_ms"), "n_population_eligible": n_pop,
            "nA": fen["nA"], "cible_A": TAILLE_FENETRE, "A_complete": fen["a_complete"], "A_fin_ts": fen["a_fin_ts"],
            "embargo_ms": EMBARGO_MS, "seuil_B_ts": fen["seuil_b_ts"],
            "nB": fen["nB"], "cible_B": TAILLE_FENETRE, "B_complete": fen["b_complete"],
            "pret_pour_rapport": bool(fen["a_complete"] and fen["b_complete"]), "mesure_ts_ms": int(time.time() * 1000)}


def _figer_bornes(prereg: dict, fen: dict) -> dict:
    A, B = fen["A"], fen["B"]
    return {"checkpoint_id": prereg.get("checkpoint_id"), "checkpoint_hash": prereg.get("checkpoint_hash"),
            "t_prereg_ms": prereg.get("t_prereg_ms"), "fige_ts_ms": int(time.time() * 1000),
            "A_debut_ts": A[0]["t_ordre"], "A_fin_ts": fen["a_fin_ts"], "embargo_ms": EMBARGO_MS,
            "B_seuil_ts": fen["seuil_b_ts"], "B_debut_ts": B[0]["t_ordre"], "B_fin_ts": B[-1]["t_ordre"],
            "A_metaorder_ids": [it["metaorder_id"] for it in A], "B_metaorder_ids": [it["metaorder_id"] for it in B]}


# ================================ alerte ONE-SHOT (fenêtre + son + fichier Bureau) =================
MSG_ALERTE = "HyperSmart : checkpoint OOS atteint — retourne voir Claude"


def _bureau(racine: str | Path) -> Path:
    """Localise le Bureau de l'utilisateur. Le projet est dans …\\Bureau\\Projet invest → le parent EST le
    Bureau. Sinon fallback USERPROFILE\\Desktop|Bureau, sinon le parent (toujours écrivable)."""
    p = Path(racine).parent
    cands = []
    if p.name.lower() in ("desktop", "bureau"):
        cands.append(p)
    up = os.environ.get("USERPROFILE") or os.environ.get("HOME") or os.path.expanduser("~")
    cands += [Path(up) / "Desktop", Path(up) / "Bureau", p]
    for c in cands:
        try:
            if c.exists():
                return c
        except OSError:
            pass
    return p


def _fenetre_et_son(texte: str, titre: str) -> str:
    """Affiche une fenêtre Windows + joue le son système UNE fois, en processus DÉTACHÉ (non bloquant).
    Hors Windows : ne fait rien (retourne 'non_windows'). N'accède à AUCUN réseau."""
    if sys.platform != "win32":
        return "non_windows"
    try:
        import base64
        import subprocess
        ps = ("Add-Type -AssemblyName System.Windows.Forms,System.Drawing; "
              "[System.Media.SystemSounds]::Asterisk.Play(); "
              "[System.Windows.Forms.MessageBox]::Show('" + texte.replace("'", "''") + "','"
              + titre.replace("'", "''") + "','OK','Information') | Out-Null")
        enc = base64.b64encode(ps.encode("utf-16-le")).decode("ascii")
        DETACHED = 0x00000008                                        # DETACHED_PROCESS : ne bloque pas la tâche
        subprocess.Popen(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                          "-WindowStyle", "Hidden", "-EncodedCommand", enc], creationflags=DETACHED, close_fds=True)
        return "affichee"
    except Exception as exc:                                         # noqa: BLE001 — une alerte ne doit JAMAIS casser la tâche
        return "erreur:" + str(exc)[:60]


def alerter_checkpoint(prereg: dict, bornes: dict, racine: str | Path, sortie: Path) -> str:
    """Alerte ONE-SHOT (verrou `.alerte.done`) : fichier Bureau très visible + fenêtre + son. Idempotent :
    ne se déclenche qu'une seule fois même aux exécutions suivantes. N'accède à AUCUN réseau."""
    lock = sortie / ".alerte.done"
    if lock.exists():
        return "deja_alertee"
    nA = len(bornes.get("A_metaorder_ids") or [])
    nB = len(bornes.get("B_metaorder_ids") or [])
    rapport_md = sortie / "RAPPORT_OOS_SHADOW_PRELIMINAIRE.md"
    contenu = (
        "HyperSmart — CHECKPOINT OOS SHADOW ATTEINT\n"
        "==========================================\n"
        f"Date            : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"checkpoint_id   : {prereg.get('checkpoint_id')}\n"
        f"checkpoint_hash : {prereg.get('checkpoint_hash')}\n"
        f"Fenetre A / B   : {nA}/30  /  {nB}/30  (metaordres uniques L2-eligibles)\n"
        f"Rapport (a generer par Claude) : {rapport_md}\n"
        f"Sentinelle      : {sortie / 'CHECKPOINT_OOS_ATTEINT.txt'}\n"
        "\n>> Retourne voir Claude et demande le rapport OOS shadow (mode --rapport).\n"
        "   Aucune promotion si l'IC bas OOS n'est pas strictement > 0.\n")
    try:
        (_bureau(racine) / "CHECKPOINT_OOS_ATTEINT.txt").write_text(contenu, encoding="utf-8")
    except OSError:
        pass
    etat_fenetre = _fenetre_et_son(MSG_ALERTE, "HyperSmart")
    lock.write_text(json.dumps({"alerte_ts_ms": int(time.time() * 1000), "fenetre": etat_fenetre}), encoding="utf-8")
    return "alertee"


def tester_notification() -> str:
    """`--test-notification` : teste UNIQUEMENT l'affichage (fenêtre + son). NE crée AUCUNE sentinelle (ni
    runtime ni Bureau), NE modifie AUCUN compteur, NE pose AUCUN verrou. Message préfixé [TEST] (honnêteté)."""
    return _fenetre_et_son("[TEST] " + MSG_ALERTE, "HyperSmart (test)")


# ================================ chemin par DÉFAUT : compteurs + sentinelle =======================
def executer(racine: str | Path) -> dict:
    """Chemin NON SURVEILLÉ (Planificateur Windows) : compteurs → status.json ; à B=30 (1re fois) écrit la
    sentinelle CHECKPOINT_OOS_ATTEINT.txt + bornes_figees.json. **Aucun IC, aucun réseau, aucun import lourd.**"""
    racine = Path(racine)
    sortie = racine / SORTIE_REL
    prereg = assurer_preregistration(sortie)
    tape_idx = eligibilite_tape(racine / TAPE_REL)
    ledger_idx = slices_ledger_cibles(racine / LEDGER_REL)
    pop = population_ordonnee(tape_idx, ledger_idx, t_prereg_ms=prereg["t_prereg_ms"])
    fen = affecter_fenetres(pop)
    cpt = compteurs(prereg, fen, len(pop))
    (sortie / "status.json").write_text(json.dumps(cpt, indent=2, ensure_ascii=False), encoding="utf-8")

    sentinelle = sortie / "CHECKPOINT_OOS_ATTEINT.txt"
    bornes_p = sortie / "bornes_figees.json"
    if cpt["pret_pour_rapport"]:
        if not sentinelle.exists():
            bornes = _figer_bornes(prereg, fen)
            bornes_p.write_text(json.dumps(bornes, indent=2, ensure_ascii=False), encoding="utf-8")
            sentinelle.write_text(
                "CHECKPOINT OOS SHADOW ATTEINT\n"
                f"checkpoint_id   : {prereg.get('checkpoint_id')}\n"
                f"checkpoint_hash : {prereg.get('checkpoint_hash')}\n"
                f"atteint_ts_ms   : {cpt['mesure_ts_ms']}\n"
                f"fenetre A       : 30 metaordres [{int(bornes['A_debut_ts'])} -> {int(bornes['A_fin_ts'])}]\n"
                f"embargo         : {int(EMBARGO_MS/1000)} s\n"
                f"fenetre B (OOS) : 30 metaordres [{int(bornes['B_debut_ts'])} -> {int(bornes['B_fin_ts'])}]\n"
                "-> ANALYSE PAR CLAUDE UNIQUEMENT (mode --rapport). Aucune promotion si IC bas OOS <= 0.\n"
                "   Le verificateur local NE calcule PAS l'IC : il ne fait que signaler.\n",
                encoding="utf-8")
            cpt["sentinelle"] = "creee"
        else:
            cpt["sentinelle"] = "deja_presente"
            bornes = json.loads(bornes_p.read_text(encoding="utf-8")) if bornes_p.exists() else _figer_bornes(prereg, fen)
        cpt["alerte"] = alerter_checkpoint(prereg, bornes, racine, sortie)   # ONE-SHOT (fenêtre + son + fichier Bureau)
    return cpt


# ================================ mode --rapport : ANALYSE (Claude seulement) ======================
def _book_depuis_entree(entree: dict | None) -> dict | None:
    if not entree or not entree.get("bids") or not entree.get("asks"):
        return None
    def col(niv):
        return [{"px": str(x[0]), "sz": str(x[1])} for x in niv if isinstance(x, (list, tuple)) and len(x) >= 2]
    b, a = col(entree["bids"]), col(entree["asks"])
    return {"levels": [b, a]} if b and a else None


def generer_rapport(racine: str | Path) -> dict:
    """ANALYSE OOS (Claude seulement) : réutilise metaorder_shadow (IC clusterisé, coûts L2). Lit les bornes
    FIGÉES (bornes_figees.json). Idempotent via `.rapport.done`. AUCUNE promotion si l'IC bas OOS n'est pas > 0."""
    racine = Path(racine)
    sortie = racine / SORTIE_REL
    done = sortie / ".rapport.done"
    if done.exists():
        return {"deja_genere": True}
    bornes_p = sortie / "bornes_figees.json"
    if not bornes_p.exists():
        return {"erreur": "checkpoint non atteint (bornes_figees.json absent)"}
    bornes = json.loads(bornes_p.read_text(encoding="utf-8"))
    prereg = json.loads((sortie / "preregistration.json").read_text(encoding="utf-8"))

    # import DIFFÉRÉ : le chemin non surveillé ne le charge jamais
    _src = Path(__file__).resolve().parents[1] / "src"
    if str(_src) not in sys.path:
        sys.path.insert(0, str(_src))
    from hl_observer.experimental import metaorder_shadow as MS

    tape_idx = eligibilite_tape(racine / TAPE_REL)
    ledger_idx = slices_ledger_cibles(racine / LEDGER_REL)
    def items(ids):
        out = []
        for mid in ids:
            e = tape_idx.get(mid)
            if e and ledger_idx.get(mid):
                out.append({"metaorder_id": mid, "ofi_signe": e["ofi_signe"], "entree": e["entree"],
                            "slices": ledger_idx[mid]})
        return out
    A, B = items(bornes["A_metaorder_ids"]), items(bornes["B_metaorder_ids"])

    def ic_net(its):
        return MS.bootstrap_clusterise([(s.get("metaorder_id"), s.get("pnl_net_bps")) for it in its for s in it["slices"]
                                        if s.get("pnl_net_bps") is not None])

    def capacite(its):
        caps = {}
        for notional in NOTIONALS:
            paires = []
            for it in its:
                book = _book_depuis_entree(it.get("entree"))
                if not book:
                    continue
                for s in it["slices"]:
                    alpha, sens = s.get("alpha_vs_marche_bps"), (s.get("sens") or 0)
                    comp = MS.cout_composants(book, notional, sens, FEE_AR_BASE_BPS) if alpha is not None else None
                    if comp:
                        paires.append((s.get("metaorder_id"), alpha - comp["cout_ar_bps"]))
            caps[str(int(notional))] = MS.bootstrap_clusterise(paires)
        prouvee = 0.0
        for notional in NOTIONALS:
            ic = caps[str(int(notional))]["ic_bas"]
            if ic is not None and ic > 0:
                prouvee = notional
        return {"par_palier": caps, "capacite_prouvee_usd": prouvee}

    ic_A, ic_B = ic_net(A), ic_net(B)
    placebo_B = MS.bootstrap_clusterise([(s.get("metaorder_id"), s.get("alpha_vs_marche_bps"))
                                         for it in B for s in it["slices"] if s.get("alpha_vs_marche_bps") is not None])
    signaux_B = [s for it in B for s in it["slices"]]
    capa = capacite(B)
    ic_bas_B = ic_B.get("ic_bas")
    promu = bool(ic_bas_B is not None and ic_bas_B > 0 and capa["capacite_prouvee_usd"] > 0)
    rap = {
        "schema": SCHEMA, "checkpoint_id": prereg.get("checkpoint_id"), "checkpoint_hash": prereg.get("checkpoint_hash"),
        "genere_ts_ms": int(time.time() * 1000), "one_shot": True, "bornes_figees": bornes,
        "n_metaordres": {"A": len(A), "B": len(B)}, "pnl_net_bps": {"A_ic": ic_A, "B_ic": ic_B},
        "roi_net_pct_B": (round(ic_B["moy"] / 100.0, 4) if ic_B.get("moy") is not None else None),
        "pnl_net_usd_moy_B": (round(ic_B["moy"] / 10000.0 * COPY_NOTIONAL_USD, 4) if ic_B.get("moy") is not None else None),
        "placebo_alpha_marche_B_ic": placebo_B,
        "couverture_l2_synchronisee": "100% par construction (population = fills L2-eligibles + OFI mesurable)",
        "resultats_avec_ofi_positif_B": ic_net([it for it in B if it.get("ofi_signe", 0) > 0]),
        "resultats_sans_ofi_positif_B": ic_net([it for it in B if it.get("ofi_signe", 0) <= 0]),
        "par_stade_B": MS.stats_par_stade(signaux_B), "par_vault_B": MS.agreger_par(signaux_B, "vault"),
        "par_coin_B": MS.agreger_par(signaux_B, "coin"), "capacite": capa,
        "verdict": "PROMOTION_POSSIBLE" if promu else "PAS_DE_PROMOTION_IC_BAS_NON_POSITIF",
        "regle": "PRELIMINAIRE — aucune promotion si l'IC bas clusterise (OOS fenetre B) n'est pas > 0.",
    }
    (sortie / "RAPPORT_OOS_SHADOW_PRELIMINAIRE.json").write_text(json.dumps(rap, indent=2, ensure_ascii=False),
                                                                encoding="utf-8")
    (sortie / "RAPPORT_OOS_SHADOW_PRELIMINAIRE.md").write_text(_markdown(rap), encoding="utf-8")
    done.write_text(json.dumps({"genere_ts_ms": rap["genere_ts_ms"], "checkpoint_hash": rap["checkpoint_hash"]}),
                    encoding="utf-8")
    return rap


def _markdown(r: dict) -> str:
    b = r["bornes_figees"]; icB = r["pnl_net_bps"]["B_ic"]
    return "\n".join([
        f"# Rapport OOS shadow — PRÉLIMINAIRE ({r['checkpoint_id']})", "",
        f"checkpoint_hash `{r['checkpoint_hash']}` · one-shot · bornes figées.", "",
        f"- Fenêtre A : {r['n_metaordres']['A']} métaordres · [{int(b['A_debut_ts'])} → {int(b['A_fin_ts'])}]",
        f"- Embargo : {int(b['embargo_ms']/1000)} s · seuil B {int(b['B_seuil_ts'])}",
        f"- Fenêtre B (OOS) : {r['n_metaordres']['B']} métaordres · [{int(b['B_debut_ts'])} → {int(b['B_fin_ts'])}]", "",
        "## PnL net — fenêtre B (OOS)",
        f"- moyenne {icB.get('moy')} bps · IC95 [{icB.get('ic_bas')} ; {icB.get('ic_haut')}] · n_métaordres={icB.get('n_clusters')}",
        f"- ROI net ~{r.get('roi_net_pct_B')} % · PnL net ~{r.get('pnl_net_usd_moy_B')} $/métaordre (copie {int(COPY_NOTIONAL_USD)} $)",
        f"- Placebo alpha marché : IC95 [{r['placebo_alpha_marche_B_ic'].get('ic_bas')} ; {r['placebo_alpha_marche_B_ic'].get('ic_haut')}]",
        f"- Avec OFI>0 : {r['resultats_avec_ofi_positif_B'].get('moy')} bps · Sans : {r['resultats_sans_ofi_positif_B'].get('moy')} bps",
        f"- Capacité prouvée (IC bas>0) : **{r['capacite']['capacite_prouvee_usd']} $**", "",
        f"## Verdict : **{r['verdict']}**", "", r["regle"]])


def _racine_defaut() -> Path:
    for c in (Path(__file__).resolve().parents[1], Path.cwd()):
        if (c / TAPE_REL).exists() or (c / "runtime").exists():
            return c
    return Path(__file__).resolve().parents[1]


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Vérificateur OOS shadow — LOCAL, read-only, aucun réseau.")
    ap.add_argument("--racine", default=str(_racine_defaut()))
    ap.add_argument("--rapport", action="store_true",
                    help="ANALYSE OOS (Claude uniquement) : à lancer APRÈS l'apparition de CHECKPOINT_OOS_ATTEINT.txt.")
    ap.add_argument("--test-notification", dest="test_notification", action="store_true",
                    help="Teste UNIQUEMENT l'affichage (fenêtre + son). Ne crée aucune sentinelle, ne modifie aucun compteur.")
    a = ap.parse_args()
    if a.test_notification:
        etat = tester_notification()
        print(f"[test-notification] fenêtre+son = {etat} (aucune sentinelle, aucun compteur modifié).")
    elif a.rapport:
        r = generer_rapport(a.racine)
        print("[rapport OOS shadow]", ("déjà généré" if r.get("deja_genere") else r.get("erreur") or r.get("verdict")))
    else:
        c = executer(a.racine)
        print(f"[verif OOS shadow] {c['checkpoint_id']} · A:{c['nA']}/{c['cible_A']} · B:{c['nB']}/{c['cible_B']} "
              f"· population={c['n_population_eligible']} · pret={c['pret_pour_rapport']}"
              + (f" · sentinelle={c.get('sentinelle')}" if c["pret_pour_rapport"] else ""))
        print("  LOCAL · read-only · 0 réseau · 0 modèle Claude · runtime intact.")
