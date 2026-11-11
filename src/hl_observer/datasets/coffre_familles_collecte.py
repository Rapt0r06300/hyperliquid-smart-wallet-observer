"""Certification des flux de collecte étendus : explorer, flux de capital des vaults,
microstructure dense, portefeuilles complets des vaults.

Mêmes règles que ``coffre_certifie`` : une ligne invalide part en quarantaine, jamais au coffre.
"""
from __future__ import annotations

from typing import Any

from hl_observer.datasets.coffre_socle import (
    PASS,
    QUARANTAINE,
    REPARE,
    _FUTUR_TOLERANCE_MS,
    _adresse,
    _canonical_coin,
    _entier_positif,
    _nombre_fini,
)


def certifier_explorer_tx(record: Any, *, source: str, now_ms: int,
                          ) -> tuple[dict[str, Any] | None, str, str]:
    """Transaction observée sur l'explorer : qui a fait quoi, quand, vu quand.

    Sert à la découverte de leaders et à la mesure de couverture (qui est actif sans être
    suivi). Exige l'instant d'observation : une transaction sans ``observed_at_ms`` ne peut
    pas être datée causalement."""
    if not isinstance(record, dict):
        return None, QUARANTAINE, "non_objet"
    user = _adresse(record.get("user"))
    if user is None:
        return None, QUARANTAINE, "user_absent_ou_invalide"
    action = str(record.get("action_type") or "").strip()
    if not action:
        return None, QUARANTAINE, "action_absente"
    ts = _entier_positif(record.get("time"))
    if ts is None:
        return None, QUARANTAINE, "timestamp_absent"
    obs = _entier_positif(record.get("observed_at_ms"))
    if obs is None:
        return None, QUARANTAINE, "observation_absente"
    if max(ts, obs) > now_ms + _FUTUR_TOLERANCE_MS:
        return None, QUARANTAINE, "timestamp_futur"
    out: dict[str, Any] = dict(record)
    out.update({"user": user, "action_type": action, "time": ts, "ts_ms": ts, "observed_at_ms": obs,
                "source": str(record.get("source") or source)})
    return out, (REPARE if record.get("user") != user else PASS), ""


def certifier_vault_ledger(record: Any, *, source: str, now_ms: int,
                           ) -> tuple[dict[str, Any] | None, str, str]:
    """Mouvement de capital d'un vault (dépôt / retrait). Historique REST : factuel, non causal.

    Indispensable pour ne pas confondre une variation de NAV due au trading avec un simple
    dépôt ou retrait. Un montant ABSENT (l'API ne chiffre pas tous les retraits) est conservé
    comme inconnu (``None`` + ``montant_connu=False``) : l'événement est réel, on sait qu'un
    retrait a eu lieu. Un montant présent mais illisible est rejeté. Jamais de flux à 0."""
    if not isinstance(record, dict):
        return None, QUARANTAINE, "non_objet"
    vault = _adresse(record.get("vault"))
    if vault is None:
        return None, QUARANTAINE, "vault_absent_ou_invalide"
    ts = _entier_positif(record.get("ts_ms"))
    if ts is None:
        return None, QUARANTAINE, "timestamp_absent"
    if ts > now_ms + _FUTUR_TOLERANCE_MS:
        return None, QUARANTAINE, "timestamp_futur"
    genre = str(record.get("type") or "").strip()
    if not genre:
        return None, QUARANTAINE, "type_absent"
    delta = None
    if record.get("delta_usd") is not None:
        delta = _nombre_fini(record.get("delta_usd"))
        if delta is None:
            return None, QUARANTAINE, "montant_invalide"
    out: dict[str, Any] = dict(record)
    out.update({"vault": vault, "ts_ms": ts, "type": genre, "delta_usd": delta,
                "montant_connu": delta is not None,
                "causal_forward_eligible": False, "source": str(record.get("source") or source)})
    return out, (REPARE if record.get("vault") != vault or record.get("delta_usd") != delta else PASS), ""


def _checksum_micro_valide(record: dict[str, Any]) -> bool:
    """Revérifie la somme de contrôle posée par le collecteur de microstructure.

    Même calcul qu'à l'écriture : SHA-256 (12 premiers hex) du JSON trié de la ligne SANS son
    champ ``checksum``. Une ligne altérée après collecte est ainsi détectée et rejetée."""
    import hashlib
    import json

    attendu = record.get("checksum")
    if not isinstance(attendu, str) or len(attendu) != 12:
        return False
    corps = {k: v for k, v in record.items() if k != "checksum"}
    calcule = hashlib.sha256(json.dumps(corps, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:12]
    return calcule == attendu


def _socle_micro(record: Any, now_ms: int) -> tuple[dict[str, Any] | None, str]:
    """Contrôles communs aux trois flux de microstructure : coin, horloges, intégrité."""
    if not isinstance(record, dict):
        return None, "non_objet"
    coin = _canonical_coin(record.get("coin"))
    if not coin:
        return None, "coin_absent"
    exch = _entier_positif(record.get("ts_ex"))
    recu = _entier_positif(record.get("ts_wall_ms"))
    if exch is None or recu is None:
        return None, "timestamp_absent"
    if max(exch, recu) > now_ms + _FUTUR_TOLERANCE_MS:
        return None, "timestamp_futur"
    if not _checksum_micro_valide(record):
        return None, "checksum_invalide"
    out = dict(record)
    out["coin"] = coin
    # noms communs aux autres familles : instant exchange et instant de réception (observation)
    out["exchange_ts_ms"], out["received_at_ms"], out["ts_ms"] = exch, recu, exch
    return out, ""


def certifier_micro_bbo(record: Any, *, source: str, now_ms: int,
                        ) -> tuple[dict[str, Any] | None, str, str]:
    """Meilleur bid / ask Hyperliquid (flux dense). Carnet croisé ou taille illisible : rejet."""
    out, raison = _socle_micro(record, now_ms)
    if out is None:
        return None, QUARANTAINE, raison
    bid, ask = _nombre_fini(record.get("bid")), _nombre_fini(record.get("ask"))
    if bid is None or ask is None or bid <= 0 or ask <= 0:
        return None, QUARANTAINE, "bbo_cotation_invalide"
    if ask < bid:
        return None, QUARANTAINE, "bbo_croise"
    for champ in ("bid_sz", "ask_sz"):
        taille = _nombre_fini(record.get(champ))
        if taille is None or taille < 0:
            return None, QUARANTAINE, "bbo_taille_invalide"
    return out, PASS, ""


def certifier_micro_l2(record: Any, *, source: str, now_ms: int,
                       ) -> tuple[dict[str, Any] | None, str, str]:
    """Carnet L2 pleine profondeur ``[[prix, taille, nb_ordres], ...]``.

    Exige des deux côtés des niveaux finis, des prix strictement ordonnés (bids décroissants,
    asks croissants) et un haut de carnet non croisé : sinon le carnet n'est pas rejouable."""
    out, raison = _socle_micro(record, now_ms)
    if out is None:
        return None, QUARANTAINE, raison
    hauts: list[float] = []
    for cote, descendant in (("bids", True), ("asks", False)):
        niveaux = record.get(cote)
        if not isinstance(niveaux, list) or not niveaux:
            return None, QUARANTAINE, "niveaux_l2_invalides"
        precedent: float | None = None
        for niveau in niveaux:
            if not isinstance(niveau, (list, tuple)) or len(niveau) < 2:
                return None, QUARANTAINE, "niveaux_l2_invalides"
            prix, taille = _nombre_fini(niveau[0]), _nombre_fini(niveau[1])
            if prix is None or taille is None or prix <= 0 or taille < 0:
                return None, QUARANTAINE, "niveaux_l2_invalides"
            if precedent is not None and (prix >= precedent if descendant else prix <= precedent):
                return None, QUARANTAINE, "niveaux_l2_desordonnes"
            precedent = prix
        hauts.append(float(niveaux[0][0]))
    if hauts[1] < hauts[0]:
        return None, QUARANTAINE, "marche_croisee"
    out["bid"], out["ask"] = hauts[0], hauts[1]
    return out, PASS, ""


def certifier_micro_trade(record: Any, *, source: str, now_ms: int,
                          ) -> tuple[dict[str, Any] | None, str, str]:
    """Transaction publique Hyperliquid : prix, taille, sens de l'agresseur (+1 achat / -1 vente)."""
    out, raison = _socle_micro(record, now_ms)
    if out is None:
        return None, QUARANTAINE, raison
    px, sz = _nombre_fini(record.get("px")), _nombre_fini(record.get("sz"))
    if px is None or px <= 0:
        return None, QUARANTAINE, "px_invalide"
    if sz is None or sz <= 0:
        return None, QUARANTAINE, "sz_invalide"
    if record.get("side") not in (-1, 1):
        return None, QUARANTAINE, "sens_inconnu"
    return out, PASS, ""


FENETRES_PORTFOLIO = ("day", "week", "month", "allTime")


def certifier_portfolio_history(record: Any, *, source: str, now_ms: int,
                                ) -> tuple[dict[str, Any] | None, str, str]:
    """Tranche de courbe valeur / PnL d'un vault (``vaultDetails.portfolio``), relue après coup.

    Une ligne = les points NOUVEAUX d'une fenêtre, observés à ``observed_at_ms``. Règles :
    horodatages strictement croissants et jamais postérieurs à l'observation (un point du futur
    est impossible) ; chaque point porte au moins une grandeur finie ; une grandeur absente reste
    ``None`` (inconnue), jamais 0. Un seul point illisible invalide TOUTE la tranche : une courbe
    amputée fausserait en silence les rendements calculés dessus. Historique non causal : il
    sert à mesurer une persistance, jamais à dater un signal en direct."""
    if not isinstance(record, dict):
        return None, QUARANTAINE, "non_objet"
    vault = _adresse(record.get("vault"))
    if vault is None:
        return None, QUARANTAINE, "vault_absent_ou_invalide"
    fenetre = record.get("fenetre")
    if fenetre not in FENETRES_PORTFOLIO:
        return None, QUARANTAINE, "fenetre_inconnue"
    obs = _entier_positif(record.get("observed_at_ms"))
    if obs is None:
        return None, QUARANTAINE, "observation_absente"
    if obs > now_ms + _FUTUR_TOLERANCE_MS:
        return None, QUARANTAINE, "timestamp_futur"
    points = record.get("points")
    if not isinstance(points, list) or not points:
        return None, QUARANTAINE, "points_absents"
    # Seule la fenêtre « vie entière » porte un PnL cumulé par nature ; pour les autres, la ligne
    # doit déclarer que le collecteur l'a recalé sur la base cumulée (schéma v2).
    pnl_cumule = fenetre == "allTime" or record.get("pnl_base") == "CUMUL_DEPUIS_CREATION"
    normalises: list[list[Any]] = []
    precedent = 0
    for point in points:
        if not isinstance(point, (list, tuple)) or len(point) != 3:
            return None, QUARANTAINE, "point_invalide"
        brut_ts = point[0]
        if isinstance(brut_ts, bool) or not isinstance(brut_ts, int) or brut_ts <= 0:
            return None, QUARANTAINE, "point_timestamp_invalide"
        if brut_ts <= precedent:
            return None, QUARANTAINE, "points_desordonnes"
        if brut_ts > obs:
            return None, QUARANTAINE, "point_posterieur_a_l_observation"
        grandeurs: list[float | None] = []
        for brut in point[1:]:
            if brut is None:
                grandeurs.append(None)
                continue
            valeur = _nombre_fini(brut)
            if valeur is None:
                return None, QUARANTAINE, "point_grandeur_invalide"
            grandeurs.append(valeur)
        if grandeurs[0] is None and grandeurs[1] is None:
            return None, QUARANTAINE, "point_sans_grandeur"
        if grandeurs[1] is not None and not pnl_cumule:
            # PnL relatif au début d'une fenêtre glissante : non comparable d'une fenêtre à l'autre
            return None, QUARANTAINE, "pnl_base_non_cumulee"
        normalises.append([brut_ts, grandeurs[0], grandeurs[1]])
        precedent = brut_ts
    volume = record.get("vlm_fenetre_usd")
    if volume is not None:
        volume = _nombre_fini(volume)
        if volume is None or volume < 0:
            return None, QUARANTAINE, "volume_invalide"
    out: dict[str, Any] = dict(record)
    out.update({
        "vault": vault, "fenetre": fenetre, "observed_at_ms": obs, "points": normalises,
        "first_ts_ms": normalises[0][0], "ts_ms": normalises[-1][0], "n_points": len(normalises),
        "vlm_fenetre_usd": volume, "causal_forward_eligible": False,
        "source": str(record.get("source") or source),
    })
    repare = (record.get("vault") != vault or record.get("points") != normalises
              or record.get("ts_ms") != normalises[-1][0] or record.get("n_points") != len(normalises))
    return out, (REPARE if repare else PASS), ""


SCHEMA_SNAPSHOT_VAULT = "hypersmart.copy_vault_portfolio_snapshot.v1"


def certifier_snapshot_vault(record: Any, *, source: str, now_ms: int,
                             ) -> tuple[dict[str, Any] | None, str, str]:
    """Certifie un instantané de PORTEFEUILLE de vault : une ligne = toutes ses positions.

    C'est la cible d'une réplication d'inventaire (portefeuille complet + NAV). Le format
    réel du collecteur est ``{vault, ts_ms, nav_usd, positions: [{coin, szi, entryPx, ...}]}`` ;
    il était auparavant aiguillé vers le certificateur de fills et rejeté en bloc
    (``coin_absent``). Règles : une position illisible invalide TOUT l'instantané (un
    portefeuille amputé serait un faux portefeuille) ; une liste vide est valide (vault à
    plat) ; une NAV absente reste inconnue (``None``), jamais 0. ``ts_ms`` est l'instant de
    lecture de l'état : il vaut à la fois instant d'événement et d'observation.
    """
    if not isinstance(record, dict):
        return None, QUARANTAINE, "non_objet"
    vault = str(record.get("vault") or "").strip().lower()
    if not vault.startswith("0x") or len(vault) < 10:
        return None, QUARANTAINE, "vault_absent_ou_invalide"
    ts = _entier_positif(record.get("ts_ms"))
    if ts is None:
        return None, QUARANTAINE, "timestamp_absent"
    if ts > now_ms + _FUTUR_TOLERANCE_MS:
        return None, QUARANTAINE, "timestamp_futur"
    positions = record.get("positions")
    if not isinstance(positions, list):
        return None, QUARANTAINE, "positions_absentes"
    repare = False
    normalisees: list[dict[str, Any]] = []
    coins_vus: set[str] = set()
    for position in positions:
        if not isinstance(position, dict):
            return None, QUARANTAINE, "position_invalide"
        coin = _canonical_coin(position.get("coin"))
        if not coin:
            return None, QUARANTAINE, "position_coin_absent"
        if coin in coins_vus:
            return None, QUARANTAINE, "position_coin_duplique"
        szi = _nombre_fini(position.get("szi"))
        if szi is None:
            return None, QUARANTAINE, "position_szi_invalide"
        coins_vus.add(coin)
        ligne = dict(position)
        repare = repare or ligne.get("coin") != coin or ligne.get("szi") != szi
        ligne["coin"] = coin
        ligne["szi"] = szi
        normalisees.append(ligne)
    nav = record.get("nav_usd")
    if nav is not None:
        nav = _nombre_fini(nav)
        if nav is None:
            return None, QUARANTAINE, "nav_invalide"
    out: dict[str, Any] = dict(record)
    out.update({
        "vault": vault, "ts_ms": ts, "nav_usd": nav, "positions": normalisees,
        "n_positions": len(normalisees), "schema_version": SCHEMA_SNAPSHOT_VAULT,
        "source": str(record.get("source") or source),
    })
    return out, (REPARE if repare else PASS), ""
