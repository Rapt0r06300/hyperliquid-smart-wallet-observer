"""UN RAPPORT QUI CRIE AU LOUP NE SERT A RIEN : c'est ce bruit qui fait rater une vraie panne.

MESURE DU 16/11/2026, sur le rapport reel d'une campagne SAINE :
163 lignes classees critiques, dont 136 `ConnectionResetError` de `native-venues` — qui avait au
meme instant 2,78 M d'ecritures et un battement de 26 s — et une trentaine de `ResourceWarning`.
`MOTIF_GRAVE` les attrapait par « traceback » (present dans le TEXTE du ResourceWarning) et par
« [a-z]+error » (dans ConnectionResetError). Pire : le rapport balayait TOUS les journaux de
`runtime/logs` sans fenetre de temps, donc un journal du 12/11 remontait en tete de « A CORRIGER EN
PRIORITE » quatre jours apres la fin de son run.

Apres correction, sur les memes journaux : 8 erreurs graves — dont un vrai `PermissionError` sur
l'ecriture de l'etat du backfill, qui etait jusque-la ENTERRE sous le bruit.

Pur : aucun reseau. Les journaux sont ecrits dans un dossier temporaire.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
for chemin in (str(RACINE), str(RACINE / "src"), str(RACINE / "tools")):
    if chemin not in sys.path:
        sys.path.insert(0, chemin)

import rapport_collecteurs as RC                    # noqa: E402


# ─────────────── le tri : une reconnexion n'est pas une panne ───────────────
def test_une_reconnexion_websocket_est_de_la_ROUTINE_pas_une_erreur_grave():
    for ligne in (
        "[WORKER] native-venues — PID 7 — ConnectionResetError: [WinError 10054] connexion existante",
        "[micro] deconnexion (sent 1011 (internal error) keepalive ping timeout) -> reconnexion",
        "[micro] deconnexion (no close frame received or sent) -> reconnexion",
    ):
        assert RC.classer(ligne) == "routine", (
            f"classe {RC.classer(ligne)} pour : {ligne[:70]} — un flux WebSocket public se "
            "reconnecte, c'est son fonctionnement normal")


def test_un_resourcewarning_ne_devient_pas_grave_a_cause_du_mot_traceback():
    ligne = "ResourceWarning: Enable tracemalloc to get the object allocation traceback"
    assert RC.classer(ligne) == "routine", (
        "le mot « traceback » est DANS le texte de l'avertissement : c'est ce qui faisait passer "
        "un avertissement de ressource pour un plantage")


def test_un_VRAI_plantage_reste_GRAVE():
    assert RC.classer("Traceback (most recent call last):") == "GRAVE"
    assert RC.classer("PermissionError: [WinError 5] Acces refuse: etat.json.tmp -> etat.json") == "GRAVE", (
        "c'est l'erreur REELLE que le bruit cachait : elle doit rester en priorite")


def test_un_429_reste_un_signal_et_le_bruit_attendu_n_est_pas_compte():
    assert RC.classer("429 too many requests") == "signal"
    assert RC.classer("tout va bien : 1200 lignes ecrites") is None
    assert RC.classer("erreurs: 0") is None, "une ligne qui dit « zero erreur » n'est pas une erreur"


# ─────────────── la fenetre de temps : un journal du 12/11 n'est pas un probleme du 16 ───────────────
def _journal(dossier: Path, nom: str, lignes: list[str], *, age_h: float) -> Path:
    f = dossier / nom
    f.write_text("\n".join(lignes) + "\n", encoding="utf-8")
    quand = time.time() - age_h * 3600.0
    import os
    os.utime(f, (quand, quand))
    return f


def test_un_journal_plus_vieux_que_la_fenetre_part_en_ARCHIVES(tmp_path):
    _journal(tmp_path, "vieux.log", ["Traceback (most recent call last):"], age_h=96.0)
    _journal(tmp_path, "frais.log", ["ValueError: boom aujourd'hui"], age_h=0.5)
    sections, globales = RC._section_logs(tmp_path, time.time(), fenetre_h=24.0)
    textes = "\n".join(sections)
    assert "ARCHIVES" in textes and "vieux.log" in textes
    noms = {nom for _ts, nom, _l, _c in globales}
    assert noms == {"frais.log"}, (
        f"globales = {noms} : un journal de run termine ne doit pas remonter dans les priorites "
        "du jour, sinon on « corrige en priorite » un probleme vieux de quatre jours")


def test_une_tempete_de_reconnexions_est_SIGNALEE_malgre_la_de_escalade(tmp_path):
    """La routine ne doit pas devenir un tapis sous lequel on cache un vrai symptome."""
    lignes = ["[l2] deconnexion (keepalive ping timeout) -> reconnexion"] * (RC.SEUIL_ROUTINE + 5)
    _journal(tmp_path, "orage.log", lignes, age_h=0.1)
    sections, _ = RC._section_logs(tmp_path, time.time(), fenetre_h=24.0)
    textes = "\n".join(sections)
    assert "lignes de ROUTINE" in textes and "A regarder" in textes, (
        f"au-dela de {RC.SEUIL_ROUTINE} reconnexions sur un seul journal, ce n'est plus de la routine")


def test_la_routine_a_sa_propre_section_et_ne_pollue_pas_les_priorites():
    globales = [(time.time(), "a.log", "ConnectionResetError: reset", "routine"),
                (time.time(), "a.log", "Traceback (most recent call last):", "GRAVE")]
    sortie = "\n".join(RC._formater_globales(globales))
    avant_signaux = sortie.index("PETITS SIGNAUX")
    assert sortie.index("ERREURS GRAVES (1 formes, 1 lignes)") < avant_signaux
    assert "ROUTINE DES FLUX PUBLICS (1 formes" in sortie


# ─────────────── les battements : on ne juge que les collecteurs DECLARES ───────────────
def test_un_battement_HORS_REGISTRE_n_est_pas_declare_mort(tmp_path):
    """`lab-ctx` dormait depuis 112 jours : collecteur d'un AUTRE lanceur, pas un mort."""
    hb = tmp_path / "runtime" / "research_lab" / "heartbeats"
    hb.mkdir(parents=True)
    (hb / "bbo-collector.json").write_text(
        json.dumps({"ts_ms": int(time.time() * 1000), "n_ecrites_cumul": 12}), encoding="utf-8")
    (hb / "un-collecteur-retire.json").write_text(
        json.dumps({"ts_ms": int((time.time() - 112 * 86400) * 1000), "n_ecrites_cumul": 5}),
        encoding="utf-8")
    sortie = "\n".join(RC._section_battements(tmp_path, time.time()))
    assert "bbo-collector" in sortie and "VIVANT" in sortie
    assert "HORS REGISTRE" in sortie and "un-collecteur-retire" in sortie
    for ligne in sortie.splitlines():
        if "un-collecteur-retire" in ligne:
            assert "FIGE" not in ligne and "ignore" in ligne


def test_l_age_d_un_battement_se_mesure_a_la_LECTURE_pas_au_debut_du_rapport(tmp_path):
    """Le rapport met des dizaines de secondes a s'ecrire ; les collecteurs battent pendant.

    Avec l'horloge du debut du rapport, les sept battements VIVANTS sortaient a « -34 s | illisible ».
    """
    hb = tmp_path / "runtime" / "research_lab" / "heartbeats"
    hb.mkdir(parents=True)
    (hb / "bbo-collector.json").write_text(
        json.dumps({"ts_ms": int(time.time() * 1000) + 5_000}), encoding="utf-8")   # 5 s dans le futur
    sortie = "\n".join(RC._section_battements(tmp_path, time.time() - 120.0))
    assert "VIVANT" in sortie and "-" not in sortie.split("bbo-collector")[1].split("|")[0], (
        "un age negatif doit etre ramene a zero, pas affiche ni traite comme illisible")


def test_un_battement_illisible_est_dit_illisible_et_non_vivant(tmp_path):
    hb = tmp_path / "runtime" / "research_lab" / "heartbeats"
    hb.mkdir(parents=True)
    (hb / "bbo-collector.json").write_text("pas du json", encoding="utf-8")
    sortie = "\n".join(RC._section_battements(tmp_path, time.time()))
    assert "ILLISIBLE" in sortie and "VIVANT" not in sortie


# ─────────────── les compteurs a ZERO sont de la bonne sante ───────────────
def test_un_compteur_a_zero_n_est_pas_un_avertissement():
    """458 « petits signaux » etaient en majorite des lignes de PROGRESSION saines."""
    for ligne in (
        "[contexte] vivant : 740 positions, 107 portefeuilles, 120 TWAP, 73 carnets, 0 reconnexions",
        "[vaults] portefeuilles leaders lents (fin de passe) : 188 ecrits pour 94 leaders (echecs 0)",
        "[candles] 1d termine : 263/263 deja a jour | debit 100 u/min | 0 refus encaisse(s)",
        "[coffre] 0 doublons, 0 rejets",
    ):
        assert RC.classer(ligne) is None, (
            f"classe {RC.classer(ligne)} : « {ligne[:60]} » annonce que tout va bien")


def test_un_compteur_NON_nul_reste_un_signal():
    assert RC.classer("[l2] 14 reconnexions en 5 min") == "signal"
    assert RC.classer("[poll] echecs 7 sur 220 leaders") == "signal"
    assert RC.classer("[coffre] 45925 doublons ignores") == "signal", (
        "ne pas jeter le bebe avec l'eau du bain : un compteur qui MONTE doit rester visible")


# ─────────────── « 429 restantes » n'est pas un HTTP 429 ───────────────
def test_le_budget_restant_du_rattrapage_n_est_pas_un_rate_limit():
    """Le motif `429` nu attrapait les MINUTES de budget restantes du rattrapage.

    « [funding] R1 37/241 kSHIB + 500 points | 19 min ecoulees, 429 restantes » remplissait la
    section des signaux ET declenchait la recommandation « reduire le debit du poll » — sur une
    campagne qui n'avait encaisse AUCUN refus.
    """
    assert RC.classer("[funding] R1 37/241 kSHIB + 500 points | 19 min ecoulees, 429 restantes") is None
    assert RC.classer("[candles] 4h 8/263 BNB + 5000 bougies | 429 restantes") is None


def test_un_VRAI_rate_limit_est_toujours_attrape():
    for ligne in ("HTTP 429 Too Many Requests", "429 too many requests",
                  "status=429 rate-limit", "[hl] rate-limit atteint, backoff 2s"):
        assert RC.classer(ligne) is not None, f"un vrai 429 ne doit pas passer : {ligne}"


def test_la_regle_d_amelioration_rate_limit_ne_part_plus_sur_un_faux_429():
    motif = RC.REGLES_AMELIORATION[0][0]
    assert not motif.search("19 min ecoulees, 429 restantes")
    assert motif.search("HTTP 429 Too Many Requests")


def test_les_en_tetes_disent_les_LIGNES_pas_seulement_les_FORMES():
    """« 430 distincts » laisse croire a 430 problemes ; le volume doit etre dit."""
    import time as _t
    globales = [(_t.time(), "a.log", "ValueError: boom", "GRAVE")] * 3
    sortie = "\n".join(RC._formater_globales(list(globales)))
    assert "1 formes, 3 lignes" in sortie


# ─────────────── journaux CUMULATIFS : la fenetre se lit par LIGNE ───────────────
def test_une_ligne_du_12_11_dans_un_journal_cumulatif_ne_remonte_pas(tmp_path):
    """`ALL_LAUNCHERS.log` est append-only : mtime de ce matin, contenu du 12/11.

    Une fenetre par FICHIER laissait donc sept lignes du 12/11 en « A CORRIGER EN PRIORITE ».
    """
    import datetime as _dt

    vieux = 'log_schema="3" timestamp_local="12/11/2026 22:53:30,43" status="FAILURE" phase="preflight"'
    frais_dt = _dt.datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    frais = f'log_schema="3" timestamp_local="{frais_dt},00" status="FAILURE" phase="preflight"'
    f = tmp_path / "ALL_LAUNCHERS.log"
    f.write_text(vieux + "\n" + frais + "\n", encoding="utf-8")
    _sections, globales = RC._section_logs(tmp_path, time.time(), fenetre_h=24.0)
    retenues = [l for _ts, _nom, l, _c in globales]
    assert len(retenues) == 1 and "12/11/2026" not in retenues[0], (
        f"retenues = {retenues} : la ligne du 12/11 doit etre ecartee, la fraiche gardee")


def test_le_mot_failure_dans_un_identifiant_n_est_pas_un_echec():
    assert RC.classer('run_id="runtime-audit-failure-2" status="SUCCESS"') is None, (
        "« failure » dans un identifiant de run n'est pas un statut d'echec")


def test_un_vrai_echec_de_lanceur_est_GRAVE():
    """Trou PREEXISTANT : `status=\"FAILURE\"` n'etait attrape par aucun motif."""
    assert RC.classer('event="RESULT" status="FAILURE" phase="preflight"') == "GRAVE"
    assert RC.classer("[NO_GO] Python 3 introuvable") == "GRAVE"


def test_une_ligne_sans_date_propre_suit_la_date_du_FICHIER():
    assert RC.horodatage_de_la_ligne("ValueError: boom") is None, (
        "sans date dans la ligne, c'est le mtime du fichier qui decide — comportement d'origine")


def test_une_heure_CADREE_PAR_UN_ESPACE_est_lue_quand_meme():
    r"""« 14/11/2026  1:18:44 » : avant 10 h, l'heure est cadree par un espace.

    Avec `\d{2}` pour l'heure, ces lignes ne matchaient pas, retombaient sur le mtime du journal
    cumulatif, et repassaient en « A CORRIGER EN PRIORITE » deux jours plus tard.
    """
    ts = RC.horodatage_de_la_ligne('timestamp_local="14/11/2026  1:18:44,17" status="FAILURE"')
    assert ts is not None, "l'heure cadree par un espace doit etre lue"
    import datetime as _dt
    lu = _dt.datetime.fromtimestamp(ts)
    assert (lu.day, lu.month, lu.hour, lu.minute) == (14, 11, 1, 18)
