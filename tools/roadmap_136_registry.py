"""Canonical, local-only registry for the 136-task Smart Flow roadmap.

The registry is deliberately data-first and fail-closed.  A task is not
``VERIFIED_DONE`` because a module or a report exists: the verifier requires a
current evidence receipt with commands, tests, proofs and a source SHA.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Final


STATUSES: Final[frozenset[str]] = frozenset(
    {
        "TODO",
        "IN_PROGRESS",
        "VERIFIED_DONE",
        "PARTIAL",
        "BLOCKED",
        "DUPLICATE",
        "SUPERSEDED",
        "HISTORICAL",
        "OUT_OF_SCOPE",
    }
)


@dataclass(frozen=True)
class RoadmapTask:
    task_id: str
    title: str
    lot: str
    priority: str
    weight: float = 1.0
    dependencies: tuple[str, ...] = ()


# Keep the source compact and reviewable.  The task names are copied from the
# user-supplied roadmap; no external task manager is consulted.
_TASK_SOURCE = """
T001|P0|Vérifier le véritable HEAD|01 autorités, inventaire et gouvernance
T002|P0|Lire la hiérarchie des autorités|01 autorités, inventaire et gouvernance
T003|P0|Reconstituer l'architecture réelle|01 autorités, inventaire et gouvernance
T004|P0|Réconcilier les 775 exigences historiques|01 autorités, inventaire et gouvernance
T005|P0|Réconcilier V5 et 776+|01 autorités, inventaire et gouvernance
T006|P0|Inventorier les idées complémentaires|01 autorités, inventaire et gouvernance
T007|P0|Créer la matrice de couverture|01 autorités, inventaire et gouvernance
T008|P0|Réconcilier la documentation|01 autorités, inventaire et gouvernance
T009|P0|Tester PAPER/READ-ONLY|02 sécurité, scope et orchestration
T010|P0|Vérifier Copy-Vault-only|02 sécurité, scope et orchestration
T011|P0|Vérifier les anciens flags expérimentaux|02 sécurité, scope et orchestration
T012|P0|Vérifier le fail-closed|02 sécurité, scope et orchestration
T013|P0|Auditer les phases|02 sécurité, scope et orchestration
T014|P0|Vérifier leases et epochs|02 sécurité, scope et orchestration
T015|P0|Garantir la collecte continue|02 sécurité, scope et orchestration
T016|P0|Éliminer les voies cloud non autorisées|02 sécurité, scope et orchestration
T017|P0|Réconcilier le rapport de clôture|03 bloqueurs actuels et campagnes GitHub
T018|P0|Corriger le comptage global unique des trades|03 bloqueurs actuels et campagnes GitHub
T019|P0|Corriger la preuve globale de clôture|03 bloqueurs actuels et campagnes GitHub
T020|P0|Réconcilier la preuve du scoreboard|03 bloqueurs actuels et campagnes GitHub
T021|P0|Vérifier les campagnes d'analyse non terminales|03 bloqueurs actuels et campagnes GitHub
T022|P0|Auditer les campagnes marché PARTIAL|03 bloqueurs actuels et campagnes GitHub
T023|P0|Auditer les échecs Event Intelligence|03 bloqueurs actuels et campagnes GitHub
T024|P0|Renforcer recovery et publication|03 bloqueurs actuels et campagnes GitHub
T025|P0|Auditer Hyperliquid|04 collecte multi-venues replay-grade
T026|P0|Auditer Binance|04 collecte multi-venues replay-grade
T027|P0|Auditer Bybit|04 collecte multi-venues replay-grade
T028|P0|Auditer OKX|04 collecte multi-venues replay-grade
T029|P0|Auditer Gate et Bitget|04 collecte multi-venues replay-grade
T030|P0|Auditer les autres venues présentes|04 collecte multi-venues replay-grade
T031|P0|Renforcer la couche d'acquisition|04 collecte multi-venues replay-grade
T032|P0|Certifier les contrats par venue|04 collecte multi-venues replay-grade
T033|P0|Vérifier l'identité des données|05 qualification SAFE et réconciliation historique
T034|P0|Vérifier L2/BBO|05 qualification SAFE et réconciliation historique
T035|P0|Vérifier l'intégrité|05 qualification SAFE et réconciliation historique
T036|P0|Réparer les PARTIAL réparables|05 qualification SAFE et réconciliation historique
T037|P0|Exclure les PARTIAL irréparables|05 qualification SAFE et réconciliation historique
T038|P0|Exclure les REJECT|05 qualification SAFE et réconciliation historique
T039|P0|Réconcilier les données historiques|05 qualification SAFE et réconciliation historique
T040|P0|Vérifier le corpus SAFE final|05 qualification SAFE et réconciliation historique
T041|P0|Auditer les quatre surfaces principales|06 AlinaSync, clone et restauration intégrale
T042|P0|Réconcilier le comportement sans argument|06 AlinaSync, clone et restauration intégrale
T043|P0|Vérifier l'inventaire Releases|06 AlinaSync, clone et restauration intégrale
T044|P0|Certifier les téléchargements|06 AlinaSync, clone et restauration intégrale
T045|P0|Certifier la décompression|06 AlinaSync, clone et restauration intégrale
T046|P0|Vérifier budgets et stockage|06 AlinaSync, clone et restauration intégrale
T047|P0|Certifier les rapports et index|06 AlinaSync, clone et restauration intégrale
T048|P0|Tester le parcours opérateur complet|06 AlinaSync, clone et restauration intégrale
T049|P1|Auditer discovery et leaderboard|07 Copy-Vault et reconstruction des wallets
T050|P1|Auditer les vaults|07 Copy-Vault et reconstruction des wallets
T051|P1|Renforcer le scoring des wallets|07 Copy-Vault et reconstruction des wallets
T052|P1|Certifier les observations|07 Copy-Vault et reconstruction des wallets
T053|P1|Certifier le lifecycle|07 Copy-Vault et reconstruction des wallets
T054|P1|Corriger les événements ambigus|07 Copy-Vault et reconstruction des wallets
T055|P1|Renforcer les sorties|07 Copy-Vault et reconstruction des wallets
T056|P1|Vérifier toute la chaîne Copy-Vault|07 Copy-Vault et reconstruction des wallets
T057|P1|Auditer le RiskEngine canonique|08 RiskEngine, ledger et dashboard
T058|P1|Vérifier les capitaux|08 RiskEngine, ledger et dashboard
T059|P1|Vérifier les limites de risque|08 RiskEngine, ledger et dashboard
T060|P1|Vérifier l'exécution PAPER|08 RiskEngine, ledger et dashboard
T061|P1|Vérifier l'exactitude du ledger|08 RiskEngine, ledger et dashboard
T062|P1|Renforcer NO_TRADE|08 RiskEngine, ledger et dashboard
T063|P1|Auditer les affichages HyperSmart|08 RiskEngine, ledger et dashboard
T064|P1|Supprimer les fausses façades|08 RiskEngine, ledger et dashboard
T065|P2|Reproduire les baselines historiques pertinentes|09 amélioration des signaux et des BPS
T066|P2|Tester de meilleurs sous-ensembles de leaders|09 amélioration des signaux et des BPS
T067|P2|Étudier la microstructure|09 amélioration des signaux et des BPS
T068|P2|Étudier les séquences de marché|09 amélioration des signaux et des BPS
T069|P2|Étudier les régimes|09 amélioration des signaux et des BPS
T070|P2|Renforcer l'estimation du signal|09 amélioration des signaux et des BPS
T071|P2|Calculer l'edge net honnêtement|09 amélioration des signaux et des BPS
T072|P2|Organiser le tournoi scientifique|09 amélioration des signaux et des BPS
T073|P3|Auditer les six variantes World Monitor|10 World Monitor et sources financières
T074|P3|Auditer les flux et contrats|10 World Monitor et sources financières
T075|P3|Étudier News et Markets|10 World Monitor et sources financières
T076|P3|Étudier les données boursières|10 World Monitor et sources financières
T077|P3|Étudier la macroéconomie|10 World Monitor et sources financières
T078|P3|Étudier crypto et dérivés|10 World Monitor et sources financières
T079|P3|Étudier géopolitique et économie réelle|10 World Monitor et sources financières
T080|P3|Prioriser les intégrations utiles|10 World Monitor et sources financières
T081|P3|Vérifier les 120 identifiants|11 Event Intelligence et 120 idées
T082|P3|Corriger les chaînes non fonctionnelles|11 Event Intelligence et 120 idées
T083|P3|Normaliser les événements|11 Event Intelligence et 120 idées
T084|P3|Renforcer la qualité des sources|11 Event Intelligence et 120 idées
T085|P3|Garantir les jointures causales|11 Event Intelligence et 120 idées
T086|P3|Relier les événements aux marchés|11 Event Intelligence et 120 idées
T087|P3|Relier les features à Copy-Vault|11 Event Intelligence et 120 idées
T088|P3|Mesurer leur utilité|11 Event Intelligence et 120 idées
T089|P2|Vérifier la console laboratoire|12 laboratoire quantitatif et mémoire
T090|P2|Vérifier le context pack|12 laboratoire quantitatif et mémoire
T091|P2|Certifier Discovery V3.2|12 laboratoire quantitatif et mémoire
T092|P2|Certifier le tournoi|12 laboratoire quantitatif et mémoire
T093|P2|Vérifier l'historique durable|12 laboratoire quantitatif et mémoire
T094|P2|Renforcer les expérimentations|12 laboratoire quantitatif et mémoire
T095|P2|Vérifier les méthodes statistiques|12 laboratoire quantitatif et mémoire
T096|P2|Éviter l'overfitting|12 laboratoire quantitatif et mémoire
T097|P1|Vérifier l'ordonnancement causal|13 replays et backtests déterministes
T098|P1|Vérifier la reconstruction des carnets|13 replays et backtests déterministes
T099|P1|Vérifier le moteur d'exécution simulé|13 replays et backtests déterministes
T100|P1|Vérifier les fills PAPER|13 replays et backtests déterministes
T101|P1|Vérifier les positions et sorties|13 replays et backtests déterministes
T102|P1|Certifier le déterminisme|13 replays et backtests déterministes
T103|P1|Renforcer les tests anti-biais|13 replays et backtests déterministes
T104|P1|Créer ou consolider les golden replays|13 replays et backtests déterministes
T105|P1|Vérifier les gates actuelles|14 OOS, forward et preuves économiques
T106|P1|Vérifier le gel des candidats|14 OOS, forward et preuves économiques
T107|P1|Vérifier OOS|14 OOS, forward et preuves économiques
T108|P1|Vérifier le forward-paper|14 OOS, forward et preuves économiques
T109|P1|Vérifier les coûts all-in|14 OOS, forward et preuves économiques
T110|P1|Vérifier la capacité économique|14 OOS, forward et preuves économiques
T111|P1|Certifier les verdicts|14 OOS, forward et preuves économiques
T112|P1|Préserver les refus honnêtes|14 OOS, forward et preuves économiques
T113|P4|Tester LANCER_COLLECTEURS_COPY_VAULT.cmd|15 certification des cinq CMD
T114|P4|Tester LANCER_LAB_QUANT_COPY_VAULT.cmd|15 certification des cinq CMD
T115|P4|Tester LANCER_HYPERSMART.cmd|15 certification des cinq CMD
T116|P4|Tester POUSSER-GITHUB-FORCE.cmd|15 certification des cinq CMD
T117|P4|Tester ALINA_SYNC_COMPLETE.cmd|15 certification des cinq CMD
T118|P4|Tester les interactions|15 certification des cinq CMD
T119|P4|Tester les échecs|15 certification des cinq CMD
T120|P4|Tester Windows et Linux selon les responsabilités|15 certification des cinq CMD
T121|P4|Vérifier SQLite et stockage|16 performance, sécurité logicielle et CI
T122|P4|Vérifier les performances CPU/RAM/I/O|16 performance, sécurité logicielle et CI
T123|P4|Vérifier la reprise des processus|16 performance, sécurité logicielle et CI
T124|P4|Vérifier la sécurité des dépendances|16 performance, sécurité logicielle et CI
T125|P4|Vérifier Ruff, pytest et coverage|16 performance, sécurité logicielle et CI
T126|P4|Vérifier les gates GitHub|16 performance, sécurité logicielle et CI
T127|P4|Vérifier les workflows complémentaires|16 performance, sécurité logicielle et CI
T128|P4|Vérifier les preuves sur SHA exact|16 performance, sécurité logicielle et CI
T129|P0|Valider collecte vers SAFE vers Release|17 tests E2E, clôture et amélioration continue
T130|P0|Valider clone vers AlinaSync vers laboratoire|17 tests E2E, clôture et amélioration continue
T131|P1|Valider wallet vers signal vers PAPER vers ledger vers dashboard|17 tests E2E, clôture et amélioration continue
T132|P1|Valider événement vers feature vers signal vers ablation vers OOS|17 tests E2E, clôture et amélioration continue
T133|P0|Valider les pannes et le déterminisme|17 tests E2E, clôture et amélioration continue
T134|P0|Exécuter l'audit anti-oubli|17 tests E2E, clôture et amélioration continue
T135|P0|Certifier la clôture technique|17 tests E2E, clôture et amélioration continue
T136|P2|Continuer l'amélioration scientifique|17 tests E2E, clôture et amélioration continue
"""


def _parse_tasks() -> tuple[RoadmapTask, ...]:
    tasks: list[RoadmapTask] = []
    for raw in _TASK_SOURCE.strip().splitlines():
        task_id, priority, title, lot = raw.split("|", 3)
        number = int(task_id[1:])
        dependencies = (f"T{number - 1:03d}",) if number > 1 else ()
        tasks.append(RoadmapTask(task_id, title, lot, priority, 1.0, dependencies))
    return tuple(tasks)


ROADMAP_TASKS: Final[tuple[RoadmapTask, ...]] = _parse_tasks()
ROADMAP_ID: Final[str] = "ALINA_SMART_FLOW_136"
ROADMAP_SOURCE_SHA256: Final[str] = sha256(_TASK_SOURCE.strip().encode("utf-8")).hexdigest()


def task_map() -> dict[str, RoadmapTask]:
    return {task.task_id: task for task in ROADMAP_TASKS}


def validate_registry() -> None:
    ids = [task.task_id for task in ROADMAP_TASKS]
    expected = [f"T{number:03d}" for number in range(1, 137)]
    if ids != expected:
        raise ValueError("roadmap registry must contain T001..T136 exactly once")
    if any(task.weight <= 0 for task in ROADMAP_TASKS):
        raise ValueError("roadmap task weights must be positive")

