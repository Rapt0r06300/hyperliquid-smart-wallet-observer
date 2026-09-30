"""[AUD-310/312/314/316/369/381/382/390] Integrite code/pipeline : courbe d'apprentissage OOS (plus de
donnees -> meilleur OOS), MODULES SANS APPELANT (code mort), except TROP LARGES, derive des tasklists,
adaptateur UNIQUE live/replay, COLLECTEURS DOUBLONS, correspondance registre/lanceur/superviseur et
attribution des RESSOURCES par source. stdlib pure, 0 reseau, 0 ordre reel."""
from __future__ import annotations

from typing import Mapping, Sequence


def courbe_apprentissage_oos(points: Sequence[Mapping]) -> dict:
    """Prouve que PLUS DE DONNEES ameliore l'OOS : la perf OOS doit tendre a CROITRE avec la taille du
    dataset (pente de la regression taille->perf >= 0)."""
    pts = sorted(points, key=lambda p: p["taille"])
    n = len(pts)
    if n < 2:
        return {"ameliore": True, "pente": 0.0, "n": n}
    xs = [p["taille"] for p in pts]
    ys = [p["perf_oos"] for p in pts]
    mx, my = sum(xs) / n, sum(ys) / n
    denom = sum((x - mx) ** 2 for x in xs) or 1e-9
    pente = sum((xs[i] - mx) * (ys[i] - my) for i in range(n)) / denom
    return {"ameliore": pente >= 0, "pente": pente, "n": n}


def detecter_modules_sans_appelant(imports: Mapping[str, Sequence[str]], *, points_entree: Sequence[str] = ()) -> dict:
    """Modules SANS APPELANT (code mort) : un module qu'aucun autre n'importe et qui n'est pas un point
    d'entree est probablement mort (ou un cablage manquant)."""
    importes: set = set()
    for cibles in imports.values():
        importes.update(cibles)
    entrees = set(points_entree)
    morts = sorted(m for m in imports if m not in importes and m not in entrees)
    return {"modules_morts": morts, "n": len(morts)}


def scanner_except_larges(lignes: Sequence[str]) -> dict:
    """except TROP LARGES : 'except:' nu ou 'except Exception/BaseException' avalent tout (y compris les
    vrais bugs) -> a signaler pour un traitement cible."""
    suspects = [i for i, ligne in enumerate(lignes)
                if ligne.strip().startswith(("except:", "except Exception", "except BaseException"))]
    return {"except_larges": suspects, "n": len(suspects)}


def detecter_derive_tasklist(items_registre: Sequence[str], items_fichier: Sequence[str]) -> dict:
    """Le fichier de taches doit correspondre au REGISTRE autoritatif. Signale les taches en trop / en
    moins (une tasklist qui derive ment sur l'etat reel)."""
    reg, fic = set(items_registre), set(items_fichier)
    return {"coherent": reg == fic, "manquants_dans_fichier": sorted(reg - fic),
            "en_trop_dans_fichier": sorted(fic - reg)}


def adaptateur_unique_live_replay(adaptateurs_par_source: Mapping[str, Sequence[str]]) -> dict:
    """Une source doit avoir UN SEUL adaptateur pour live ET replay (deux adaptateurs = deux
    comportements qui divergent -> parity live/replay cassee)."""
    doubles = sorted(s for s, a in adaptateurs_par_source.items() if len(set(a)) > 1)
    return {"unifie": len(doubles) == 0, "sources_a_double_adaptateur": doubles}


def detecter_collecteurs_doublons(collecteurs: Sequence[Mapping]) -> dict:
    """Collecteurs DOUBLONS : deux collecteurs sur le meme (venue, stream) se marchent dessus (double
    quota, donnees dupliquees)."""
    vus: dict = {}
    doublons = []
    for c in collecteurs:
        cle = (c.get("venue"), c.get("stream"))
        if cle in vus:
            doublons.append(c.get("nom"))
        else:
            vus[cle] = c.get("nom")
    return {"sans_doublon": len(doublons) == 0, "doublons": sorted(doublons)}


def correspondance_registre_lanceur_superviseur(registre: Sequence[str], lanceur: Sequence[str],
                                                 superviseur: Sequence[str]) -> dict:
    """REGISTRE, ce que le LANCEUR demarre et ce que le SUPERVISEUR surveille doivent coincider. Toute
    divergence = un collecteur non lance, non surveille, ou fantome."""
    r, l, s = set(registre), set(lanceur), set(superviseur)
    return {"coherent": r == l == s, "non_lances": sorted(r - l),
            "non_surveilles": sorted(r - s), "fantomes": sorted((l | s) - r)}


def attribuer_ressources_par_source(mesures: Mapping[str, Mapping]) -> dict:
    """Attribue CPU/RAM/disque/reseau PAR SOURCE : on sait quelle source coute quoi (une source qui
    devore les ressources sans valeur marginale doit sauter)."""
    total = {"cpu": 0.0, "ram_mo": 0.0, "disque_mo": 0.0, "reseau_mo": 0.0}
    for m in mesures.values():
        for k in total:
            total[k] += float(m.get(k, 0.0))
    return {"par_source": {n: dict(m) for n, m in mesures.items()}, "total": total}
