"""Registre des fichiers de collecte : exclusions par conception et versions des règles.

Un fichier écarté l'est ICI, avec son motif visible ; rien n'est ignoré en silence.
"""
from __future__ import annotations

from typing import Any


#: Fichiers de collecte VOLONTAIREMENT non certifiés, avec leur motif. Tout autre fichier
#: non reconnu est signalé « INCONNU » par le scelleur : plus aucun oubli silencieux.
FICHIERS_NON_CERTIFIES: dict[str, tuple[str, str]] = {
    "explorer_inferred_fills.jsonl": (
        "INFERENCE", "fills DÉDUITS de l'explorer (certifie=false) : une estimation n'entre jamais au coffre"),
    "metaorder_shadow_ledger.jsonl": (
        "DERIVE", "registre de simulation « shadow » calculé à partir des fills : produit dérivé, pas une observation"),
    "metaorder_l2_tape.jsonl": (
        "DERIVE", "jointure fill + carnet autour des métaordres : dérivée de flux déjà certifiés (fills, L2)"),
    "fills_journal.jsonl": (
        "REDONDANT", "journal des fills WebSocket déjà certifiés via vault_fills_live.jsonl"),
    "lead_lag_event_decisions.jsonl": (
        "HORS_PERIMETRE", "famille Lead-Lag : DISABLED_BY_SCOPE, aucune preuve Copy-Vault n'en dépend"),
    "raw_l2_lifecycle.jsonl": (
        "DIAGNOSTIC", "journal technique des abonnements L2 (pas une donnée de marché)"),
    "userfills_integrity_diagnostics.jsonl": (
        "DIAGNOSTIC", "diagnostics d'intégrité du collecteur de fills (pas une donnée de marché)"),
    "leader_fills_bruts.jsonl": (
        "DERIVE", "journal des votes de leaders écrit par le moteur (ni prix ni taille, lignes de test) : "
                  "pas une observation de marché"),
    "userfills_unclassified.jsonl": (
        "DIAGNOSTIC", "trames userFills que le collecteur n'a pas pu classer (charge brute gardée pour enquête)"),
    "recap_historique.jsonl": (
        "DIAGNOSTIC", "récapitulatif d'état du projet (tests, positions) : pas une donnée de marché"),
    "raw_probe_ledger.jsonl": (
        "DERIVE", "journal de décisions du moteur PAPER (sonde brute) : sortie de simulation, pas une observation"),
    "exploratory_paper_ledger.jsonl": (
        "DERIVE", "journal de décisions du moteur PAPER exploratoire : sortie de simulation, pas une observation"),
    "discovery_probe_ledger.jsonl": (
        "DERIVE", "journal de décisions du moteur PAPER (sonde de découverte) : sortie de simulation"),
}


def _nom_de_base(nom_fichier: str) -> str:
    base = str(nom_fichier).replace(chr(92), "/").rsplit("/", 1)[-1]
    return base[:-3] if base.endswith(".gz") else base


def nouvellement_accepte(nom_fichier: str, norm: dict[str, Any]) -> bool:
    """La ligne certifiée était-elle REJETÉE par la règle précédente de ce fichier ?

    Sert au rattrapage d'un ruban archivé déjà scellé avec l'ancienne règle : seules les lignes
    que cette règle écartait à tort sont déposées, les autres sont déjà au coffre.
    * BBO v1 n'acceptait que les transactions (``px``) : les cotations sont nouvelles ;
    * fills WebSocket v1 exigeait ``observed_at_ms`` : ceux qui s'appuient sur l'heure de
      réception sont nouveaux ;
    * tout autre fichier versionné (portefeuilles de vaults) était rejeté en bloc : tout est nouveau.
    """
    base = _nom_de_base(nom_fichier)
    if base in ("bbo_tape.jsonl", "copy_vault_bbo_tape.jsonl", "copy_vault_bbo_lane.jsonl"):
        return norm.get("type_ligne") == "QUOTE"
    if base == "vault_fills_live.jsonl":
        return norm.get("observation_field") == "received_at_ms"
    return True


def motif_non_certifie(nom_fichier: str) -> tuple[str, str] | None:
    """(catégorie, explication) si le fichier est écarté PAR CONCEPTION, sinon ``None``."""
    return FICHIERS_NON_CERTIFIES.get(_nom_de_base(nom_fichier))


#: Version du certificateur par famille. Quand la règle d'une famille change (ici : les
#: instantanés de vault, rejetés en bloc avant la v2), un fichier déjà « traité » avec une
#: version plus ancienne doit être recertifié même si son contenu n'a pas changé.
VERSIONS_CERTIFICATEUR: dict[str, int] = {
    "vault_snapshots.jsonl": 2,     # portefeuilles complets (rejetés « coin_absent » en v1)
    "vault_fills_live.jsonl": 2,    # fills WebSocket (rejetés faute d'observed_at_ms en v1)
    "bbo_tape.jsonl": 2,            # cotations bid/ask Hyperliquid (rejetées « px_invalide » en v1)
    "copy_vault_bbo_tape.jsonl": 2,
    "copy_vault_bbo_lane.jsonl": 2,
    "vault_ledger.jsonl": 2,        # retraits à montant inconnu (rejetés « montant_invalide » en v1)
    "explorer_tx_tape.jsonl": 2,    # flux ignoré jusqu'ici (aucune règle en v1)
}


def version_certificateur(nom_fichier: str) -> int:
    """Version courante de la règle de certification du fichier (1 par défaut).

    Indexée par NOM de fichier : corriger la règle d'un flux ne force à recertifier que ce
    flux, pas toute sa famille (les autres fichiers ont déjà été déposés correctement)."""
    return int(VERSIONS_CERTIFICATEUR.get(_nom_de_base(nom_fichier), 1))
