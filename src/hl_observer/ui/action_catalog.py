from __future__ import annotations

from hl_observer.ui.schemas import ActionCatalogItem


ACTION_GROUPS: dict[str, list[tuple[str, str, str]]] = {
    "Verifier": [
        ("doctor", "Verifier le logiciel", "Controle configuration locale et posture securite."),
        ("safety_audit", "Audit securite", "Cherche secrets, /exchange et chemins interdits."),
        ("init_db", "Preparer la base", "Cree les tables manquantes sans supprimer les donnees."),
    ],
    "Sources": [
        ("scrape_leaderboard", "Lire leaderboard", "Tente une lecture publique sans accepter les adresses tronquees."),
        ("probe_leaderboard_network", "Tester extraction reseau", "Probe read-only de la page leaderboard."),
        ("extract_leaderboard_dom", "Tester extraction DOM", "Analyse DOM preparee, sans inventer d'adresse."),
        ("import_leaderboard", "Importer leaderboard", "Import local CSV/JSON/TXT d'adresses completes."),
        ("validate_leaderboard_addresses", "Valider adresses", "Rejette les adresses tronquees et invalides."),
        ("leaderboard_candidates", "Creer candidats", "Cree les candidats leaderboard complets disponibles."),
        ("probe_explorer", "Lire explorer", "Inspecte l'Explorer public et affiche les limites/extractions."),
        ("scrape_explorer", "Scanner transactions", "Tente de structurer les transactions Explorer visibles."),
        ("import_explorer", "Importer explorer", "Import local CSV/JSON/TXT de transactions ou adresses completes."),
        ("explorer_candidates", "Candidats explorer", "Cree des candidats depuis transactions Explorer valides."),
        ("revalidate_explorer_wallets", "Revalider explorer", "Verifie les wallets Explorer par garde full-address."),
        ("explorer_tape", "Voir transactions", "Affiche la tape locale des transactions Explorer."),
    ],
    "Rechercher": [
        ("discover_markets", "Decouvrir les marches", "Univers multi-assets via meta/allMids."),
        ("discover_wallets", "Rechercher les wallets", "Discovery automatique priorisant leaderboard."),
        ("bootstrap_top_wallets", "Construire Top 500", "Top 500 honnete avec wallets complets disponibles."),
        ("autoscan_start", "Relancer auto-scan", "Cycle auto-pilot read-only."),
    ],
    "Scanner": [
        ("scan_wallet_queue", "Scanner la file de wallets", "File progressive avec limites et reprise."),
        ("backfill_selected_wallets", "Backfill selectionnes", "Backfill lecture seule multi-coins."),
    ],
    "Comprendre les profits": [
        ("analyze_openings", "Analyser les ouvertures", "Detecte OPEN/ADD/FLIP."),
        ("analyze_closings", "Analyser les fermetures", "Detecte REDUCE/CLOSE/FLIP."),
        ("rank_opening_patterns", "Classer ouvertures rentables", "Rejette les echantillons trop faibles."),
        ("profile_wallet_styles", "Profiler styles wallets", "Resume styles et coins favoris."),
        ("generate_trader_playbooks", "Generer playbooks", "Regles observe-only et paper-first."),
    ],
    "Suivre en paper": [
        ("generate_follow_signals", "Generer signaux paper", "Cree signaux paper depuis ouvertures valides."),
        ("apply_adaptive_risk_filter", "Appliquer filtre de risque", "Bloque si risque/liquidite/age echouent."),
        ("paper_follow", "Lancer paper-follow", "Cree ordres simules uniquement."),
        ("paper_follow_report", "Rapport paper-follow", "Synthese des suivis paper."),
    ],
    "Classer": [
        ("score_wallets_simple", "Noter les wallets", "Score local deterministe."),
        ("detect_signals_simple", "Chercher les signaux", "Detection locale sans execution."),
        ("show_rejected_candidates", "Voir candidats rejetes", "Raisons de rejet."),
    ],
    "Simuler": [
        ("paper_run", "Simulation paper", "Smoke path paper uniquement."),
        ("paper_report", "Rapport paper", "Rapport paper local."),
        ("reset_simulation_session", "Remise a zero simulation", "Efface positions virtuelles et historique P&L local."),
        ("testnet_check", "Verifier testnet", "Testnet reste verrouille par defaut."),
    ],
    "Donnees": [
        ("export_top_wallets", "Exporter Top 500", "Export local quand disponible."),
        ("export_leaderboard", "Exporter leaderboard", "Export local des lignes stockees."),
        ("export_explorer", "Exporter explorer", "Export local des transactions stockees."),
        ("clear_ui_logs", "Nettoyer affichage", "Nettoie seulement les logs UI temporaires."),
    ],
}


def build_action_catalog() -> list[ActionCatalogItem]:
    items: list[ActionCatalogItem] = []
    for group, actions in ACTION_GROUPS.items():
        for action_id, label, description in actions:
            items.append(
                ActionCatalogItem(
                    action_id=action_id,
                    label=label,
                    group=group,
                    description=description,
                    enabled=True,
                    safety_level="read_only" if "paper" not in action_id else "paper_only",
                    expected_result="Resultat structure, log UI et aucune action dangereuse.",
                    icon="shield" if "safety" in action_id or "testnet" in action_id else "terminal",
                    test_id=f"action-{action_id}",
                )
            )
    return items
