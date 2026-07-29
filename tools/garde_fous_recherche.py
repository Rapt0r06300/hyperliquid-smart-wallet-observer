"""PROVENANCE, EXPLORATIONS P2 ET GARDE-FOUS « NE PAS COPIER » (IDEA-71, 78 → 91).

Trois familles réunies parce qu'elles servent la même chose : empêcher un beau chiffre de passer pour une
preuve.

  • IDEA-71 : les autres marchés servent de CONTRÔLE QUALITÉ, jamais de signal automatique ;
  • IDEA-78 : manifeste de campagne (Git HEAD, dirty, Python, deps, config éco, hash fee/fill, sources) ;
  • IDEA-79 : erreur de scanner ≠ zéro événement — une panne doit rougir la santé, pas passer pour un
    marché calme ;
  • IDEA-80 : synthétique = plomberie — `data_origin=SYNTHETIC` ⇒ `promotable=false`, jamais champion ;
  • IDEA-81 → 85 : cadres exploratoires P2 (prix × probabilité, MM vs directionnel, adverse selection
    conditionnée aux metaorders, horloges de lead-lag, bibliothèque de rejeu d'erreurs) ;
  • IDEA-86 → 91 : les six garde-fous du thread 0x_Punisher, encodés en RÈGLES vérifiables (limites WS
    Hyperliquid, seuils en bps et non en cents, aucun wallet réel, marketing ≠ preuve, MM/ladder à
    falsifier, comparaison live/backtest détaillée).

Calcul pur : 0 réseau, 0 ordre, paper-only.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

# ─────────────────────── IDEA-71 : cross-source sanity checking ───────────────────────
def sanity_cross_source(*, prix_hl: float, prix_autres: dict, ecart_max_pct: float = 1.5) -> dict:
    """IDEA-71 — les autres marchés servent UNIQUEMENT à valider la qualité de la donnée Hyperliquid.
    Un mouvement HL non confirmé ailleurs devient `DATA_QUALITY_UNCERTAIN` — et surtout PAS un signal
    d'arbitrage : `signal_autorise` est toujours False."""
    try:
        p = float(prix_hl)
    except (TypeError, ValueError):
        return {"statut": "DATA_QUALITY_UNCERTAIN", "motif": "PRIX_HL_INVALIDE", "signal_autorise": False}
    ecarts = {}
    for nom, v in (prix_autres or {}).items():
        try:
            x = float(v)
        except (TypeError, ValueError):
            continue
        if x > 0:
            ecarts[nom] = round(abs(p - x) / x * 100.0, 6)
    if not ecarts:
        return {"statut": "DATA_QUALITY_UNCERTAIN", "motif": "AUCUNE_SOURCE_DE_CONTROLE",
                "signal_autorise": False}
    divergentes = [n for n, e in ecarts.items() if e > float(ecart_max_pct)]
    confirme = not divergentes
    return {"statut": ("CONFIRME" if confirme else "DATA_QUALITY_UNCERTAIN"),
            "ecarts_pct": ecarts, "sources_divergentes": divergentes,
            "signal_autorise": False,      # JAMAIS : une source externe ne devient pas un signal
            "usage": "controle de qualite uniquement"}


# ─────────────────────── IDEA-78/79/80 : provenance, scanner, synthétique ───────────────────────
def manifeste_campagne(racine: Path, *, config_economique: dict | None = None,
                       fee_model_hash: str | None = None, fill_model_hash: str | None = None,
                       sources: dict | None = None, schema_versions: dict | None = None) -> dict:
    """IDEA-78 — manifeste reproductible. `git_dirty=True` est une INFORMATION, pas une faute : mais un
    résultat produit sur un arbre sale doit le dire."""
    import platform
    import sys

    def _git(*args, timeout=8):
        """Rend la sortie de git, ou None si git n'a PAS repondu.

        `None` (inconnu) et `""` (sortie vide, ex. arbre propre) sont deux choses
        differentes : les confondre ferait passer un timeout pour un arbre propre.
        Sur un disque lent, `subprocess.run(timeout=)` peut rester bloque APRES le
        kill en attendant un process en I/O ininterruptible : on tue sans attendre.
        """
        proc = None
        try:
            proc = subprocess.Popen(["git", *args], cwd=str(racine),
                                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                    text=True)
            out, _ = proc.communicate(timeout=timeout)
            if proc.returncode != 0:
                return None
            return (out or "").strip()
        except Exception:  # noqa: BLE001
            if proc is not None:
                try:
                    proc.kill()
                except Exception:  # noqa: BLE001
                    pass
            return None

    head = _git("rev-parse", "HEAD")
    statut = _git("status", "--porcelain")
    # tri-etat : True (sale) / False (propre) / None (git muet -> INCONNU)
    sale = None if statut is None else bool(statut.strip())
    if sale:
        avertissement = "arbre git SALE : resultat non reproductible tel quel"
    elif sale is None:
        avertissement = "etat git INCONNU (git n'a pas repondu) : traite comme NON reproductible"
    else:
        avertissement = None
    return {"git_head": head or None, "git_dirty": sale,
            "python": sys.version.split()[0], "plateforme": platform.system(),
            "config_economique": dict(config_economique or {}),
            "fee_model_hash": fee_model_hash, "fill_model_hash": fill_model_hash,
            "sources": dict(sources or {}), "schema_versions": dict(schema_versions or {}),
            # deny-by-default : inconnu n'est jamais traite comme propre
            "reproductible": bool(head) and sale is False,
            "avertissement": avertissement}


def etat_ingestion(*, n_nouveaux_evenements: int | None, erreur_scanner: str | None = None) -> dict:
    """IDEA-79 — distingue ZERO_NEW_EVENTS (marché calme, santé verte) de DATA_INGESTION_FAILED (panne,
    santé ROUGE, aucune promotion). Confondre les deux, c'est prendre une panne pour un marché calme."""
    if erreur_scanner:
        return {"statut": "DATA_INGESTION_FAILED", "sante": "ROUGE", "promotion_autorisee": False,
                "erreur": str(erreur_scanner)[:200],
                "motif": "panne de collecte — surtout pas interprete comme un marche calme"}
    if n_nouveaux_evenements is None:
        return {"statut": "DATA_INGESTION_FAILED", "sante": "ROUGE", "promotion_autorisee": False,
                "motif": "compte d'evenements inconnu"}
    if int(n_nouveaux_evenements) == 0:
        return {"statut": "ZERO_NEW_EVENTS", "sante": "VERTE", "promotion_autorisee": True,
                "motif": "aucune nouvelle donnee — collecte saine"}
    return {"statut": "OK", "sante": "VERTE", "promotion_autorisee": True,
            "n_nouveaux_evenements": int(n_nouveaux_evenements)}


def verrou_synthetique(resultat: dict) -> dict:
    """IDEA-80 — un résultat issu de données SYNTHETIC ne peut jamais devenir champion, PASS_PRE_FORWARD,
    PASS_FORWARD_PAPER, PnL réel ou pépite du dashboard. La plomberie se teste, elle ne se promeut pas."""
    origine = str((resultat or {}).get("data_origin", "UNKNOWN")).upper()
    synth = origine in ("SYNTHETIC", "FIXTURE", "FAKE")
    interdits = ("PASS_PRE_FORWARD", "PASS_FORWARD_PAPER", "CHAMPION", "PEPITE")
    verdict = str((resultat or {}).get("verdict", "")).upper()
    violation = synth and verdict in interdits
    return {"data_origin": origine, "synthetique": synth,
            "promotable": (not synth) and origine == "REAL",
            "violation": violation,
            "verdict_corrige": ("SHADOW_SYNTHETIQUE" if violation else verdict or None),
            "motif": ("donnee synthetique : plomberie uniquement" if synth else "donnee reelle")}


# ─────────────────────── IDEA-81 → 85 : cadres exploratoires P2 ───────────────────────
def esperance_entree(*, qualite_prix_bps: float, probabilite_succes: float, gain_attendu_bps: float,
                     couts_bps: float) -> dict:
    """IDEA-81 — prix × probabilité : l'espérance conjointe, pas le filtre naïf « acheter plus bas ».
    Un meilleur prix qui s'accompagne d'une probabilité effondrée est un piège."""
    try:
        p = float(probabilite_succes)
        g, c, q = float(gain_attendu_bps), float(couts_bps), float(qualite_prix_bps)
    except (TypeError, ValueError):
        return {"mesurable": False, "motif": "ENTREES_INVALIDES"}
    if not 0.0 <= p <= 1.0:
        return {"mesurable": False, "motif": "PROBABILITE_HORS_BORNES"}
    esp = p * g - (1 - p) * abs(g) - c + q
    return {"mesurable": True, "esperance_bps": round(esp, 4), "rentable": esp > 0,
            "note": "un meilleur prix ne compense pas une probabilite effondree"}


def comparer_styles(nets_par_style: dict, *, min_n: int = 30) -> dict:
    """IDEA-82 — taker directionnel vs maker vs ladder vs hybride, sur LES MÊMES données, LES MÊMES coûts
    et LES MÊMES règles. Sans cette symétrie, la comparaison ne vaut rien."""
    import statistics
    lignes = []
    for style, nets in (nets_par_style or {}).items():
        xs = [float(x) for x in (nets or []) if isinstance(x, (int, float))]
        lignes.append({"style": style, "n": len(xs),
                       "net_median_bps": (round(statistics.median(xs), 4) if xs else None),
                       "concluant": len(xs) >= int(min_n)})
    concluants = [l for l in lignes if l["concluant"] and l["net_median_bps"] is not None]
    return {"lignes": sorted(lignes, key=lambda l: -(l["net_median_bps"] or -1e9)),
            "gagnant": (max(concluants, key=lambda l: l["net_median_bps"])["style"] if concluants else None),
            "exige": "memes donnees, memes couts, memes regles"}


def adverse_selection_par_stade(observations) -> dict:
    """IDEA-83 — croise stade du metaorder, flux résiduel et markout : l'adverse selection n'est pas une
    constante, elle dépend de l'endroit où l'on entre dans l'exécution d'un gros ordre."""
    import statistics
    paquets = {}
    for o in (observations or []):
        st = o.get("stade_execution")
        mk = o.get("markout_bps")
        if st is None or not isinstance(mk, (int, float)):
            continue
        tranche = "0-33%" if st < 0.33 else ("33-66%" if st < 0.66 else "66-100%")
        paquets.setdefault(tranche, []).append(float(mk))
    lignes = [{"tranche": t, "n": len(v), "markout_median_bps": round(statistics.median(v), 4)}
              for t, v in sorted(paquets.items())]
    return {"lignes": lignes,
            "tranche_la_plus_toxique": (min(lignes, key=lambda l: l["markout_median_bps"])["tranche"]
                                        if lignes else None)}


def horloges_lead_lag() -> dict:
    """IDEA-84 — horloges à tester, PRÉ-ENREGISTRÉES : transitions de seconde, minute, 5 min, quart d'heure.
    Les déclarer d'avance empêche d'aller pêcher l'horloge qui arrange après avoir vu les résultats."""
    return {"horloges": ("DEBUT_SECONDE", "DEBUT_MINUTE", "DEBUT_5MIN", "DEBUT_15MIN"),
            "pre_enregistrees": True, "exige_oos": True,
            "n_essais": 4}


def bibliotheque_erreurs(journal_resume: dict | None = None) -> dict:
    """IDEA-85 — scénarios de stress réalistes, alimentés par le journal opérationnel RÉEL quand il existe
    (voir `journal_operationnel.scenarios_pour_replay`). Une stratégie doit survivre à ce qui est
    RÉELLEMENT arrivé avant toute promotion forte."""
    base = ("reconnect", "delayed_feed", "missing_l2", "stale_bbo", "partial_fill",
            "latency_spike", "gap", "bad_snapshot")
    observes = list((journal_resume or {}).get("par_type", {}).keys())
    return {"scenarios_catalogue": base, "n_catalogue": len(base),
            "incidents_reellement_observes": observes,
            "source": ("journal_operationnel" if observes else "catalogue_par_defaut"),
            "exige_avant_promotion_forte": True}


# ─────────────────────── IDEA-86 → 91 : garde-fous « ne pas copier » ───────────────────────
#: limites Hyperliquid connues au moment de l'écriture — à revérifier dans la doc officielle avant usage.
LIMITES_HL = {"ws_connexions_par_ip": 10, "ws_nouvelles_par_minute": 30, "subscriptions": 1000,
              "users_uniques_subscriptions": 10, "messages_par_minute": 2000, "l2_niveaux": 20}


def verifier_plan_websockets(n_connexions: int, *, nouvelles_par_minute: int = 0,
                             subscriptions: int = 0) -> dict:
    """IDEA-86 — 100–300 WebSockets (thread Polymarket) est IMPOSSIBLE sur Hyperliquid. On vérifie le plan
    contre les limites documentées et on recommande peu de connexions robustes + multiplexage."""
    violations = []
    if int(n_connexions) > LIMITES_HL["ws_connexions_par_ip"]:
        violations.append("CONNEXIONS>%d" % LIMITES_HL["ws_connexions_par_ip"])
    if int(nouvelles_par_minute) > LIMITES_HL["ws_nouvelles_par_minute"]:
        violations.append("NOUVELLES_PAR_MINUTE>%d" % LIMITES_HL["ws_nouvelles_par_minute"])
    if int(subscriptions) > LIMITES_HL["subscriptions"]:
        violations.append("SUBSCRIPTIONS>%d" % LIMITES_HL["subscriptions"])
    return {"conforme": not violations, "violations": violations, "limites": dict(LIMITES_HL),
            "recommandation": "peu de connexions robustes + multiplexage + quality scoring"}


def convertir_seuil_polymarket(seuil_cents: float) -> dict:
    """IDEA-87 — un seuil en cents Polymarket (5¢/15¢/0¢/100¢) N'A PAS de sens sur un perp Hyperliquid.
    On refuse la conversion et on renvoie les unités correctes à utiliser."""
    return {"transposable": False, "seuil_cents": seuil_cents,
            "motif": "un marche de prediction en cents ne se transpose pas a un perp",
            "unites_correctes": ("bps", "volatilite", "spread", "profondeur", "age_ms")}


def verifier_absence_wallet(config: dict) -> dict:
    """IDEA-88 — même pour un dry-run, HyperSmart n'utilise AUCUN wallet, AUCUNE clé, AUCUNE signature."""
    interdits = ("private_key", "mnemonic", "seed", "wallet_address", "signer", "api_secret")
    presents = [k for k in interdits if (config or {}).get(k)]
    return {"conforme": not presents, "champs_interdits_presents": presents,
            "motif": ("OK — aucun wallet, aucune cle, aucune signature" if not presents
                      else "CONFIG INTERDITE: %s" % ",".join(presents))}


def poids_preuve(source: str, *, chiffre=None) -> dict:
    """IDEA-89 — un PnL public / un win-rate de thread est une INSPIRATION, jamais une validation.
    Seule une mesure interne, OOS, sur nos données et nos coûts, a valeur de preuve."""
    s = str(source).upper()
    interne = s in ("MESURE_INTERNE", "OOS_INTERNE", "FORWARD_PAPER")
    return {"source": s, "valeur_de_preuve": interne,
            "role": ("PREUVE" if interne else "INSPIRATION"),
            "chiffre": chiffre,
            "motif": ("mesure interne reproductible" if interne
                      else "chiffre externe/marketing — ne valide RIEN chez nous")}


def hypothese_falsifiable(nom: str, *, prediction: str, critere_kill: str,
                          pre_enregistre: bool = False) -> dict:
    """IDEA-90 — « le market making gagne » n'est pas une vérité : c'est une hypothèse. Elle doit porter
    une prédiction et un critère de KILL, tous deux PRÉ-ENREGISTRÉS avant de voir les résultats."""
    manque = [n for n, v in (("prediction", prediction), ("critere_kill", critere_kill)) if not v]
    return {"hypothese": nom, "prediction": prediction, "critere_kill": critere_kill,
            "pre_enregistre": bool(pre_enregistre),
            "valide": not manque and bool(pre_enregistre),
            "motif": ("OK" if (not manque and pre_enregistre)
                      else "NON_FALSIFIABLE: %s" % (",".join(manque) or "non pre-enregistree"))}


#: métriques à comparer SÉPARÉMENT entre live et backtest (IDEA-91).
METRIQUES_LIVE_VS_BACKTEST = ("n_signaux", "fill_rate", "pnl", "roi", "drawdown", "couts",
                              "slippage", "profit_factor", "win_rate", "markouts")


def comparer_live_backtest(live: dict, backtest: dict, *, tolerance_relative: float = 0.10) -> dict:
    """IDEA-91 — interdit la règle vague « live ≈ backtest à 3 % ». On compare CHAQUE métrique séparément
    et on liste celles qui divergent ; une métrique absente est signalée, pas ignorée."""
    lignes, manquantes = [], []
    for m in METRIQUES_LIVE_VS_BACKTEST:
        a, b = (live or {}).get(m), (backtest or {}).get(m)
        if not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
            manquantes.append(m)
            continue
        base = max(abs(float(b)), 1e-9)
        ecart = abs(float(a) - float(b)) / base
        lignes.append({"metrique": m, "live": a, "backtest": b,
                       "ecart_relatif": round(ecart, 6),
                       "diverge": ecart > float(tolerance_relative)})
    divergentes = [l["metrique"] for l in lignes if l["diverge"]]
    return {"lignes": lignes, "metriques_divergentes": divergentes, "metriques_manquantes": manquantes,
            "coherent": (not divergentes and not manquantes),
            "motif": "comparaison metrique par metrique — jamais un pourcentage global unique"}


__all__ = ["sanity_cross_source", "manifeste_campagne", "etat_ingestion", "verrou_synthetique",
           "esperance_entree", "comparer_styles", "adverse_selection_par_stade", "horloges_lead_lag",
           "bibliotheque_erreurs", "LIMITES_HL", "verifier_plan_websockets",
           "convertir_seuil_polymarket", "verifier_absence_wallet", "poids_preuve",
           "hypothese_falsifiable", "METRIQUES_LIVE_VS_BACKTEST", "comparer_live_backtest"]
