"""S1.3 / R2 — les ORDRES et les FILLS doivent couvrir les MÊMES comptes, sinon l'étude maker est vide.

Mesure du 12/11 : ``copy_vault_order_intent`` voyait « 0 jour, 0 fill, 0 leader pendant le suivi des
carnets d'ordres ». Diagnostic initial : « il manque les données d'ordres ». FAUX. Cause trouvée par
inspection du code : la lane d'ordres suit ``config/copy_vault_leaders.json`` (liste partagée alimentée
par l'explorer) alors que le collecteur de fills LOCAL suit sa propre sélection (≤10 slots WS : CORE +
sentinelles + rotation). Deux ensembles qui se recoupent à peine ⇒ des ordres d'un côté, des fills de
l'autre, et jamais le couple ordre → fill dont l'étude a besoin.

Ces tests verrouillent le correctif :

1. le défaut ne change RIEN (les lanes cloud continuent de lire la liste partagée) ;
2. ``--leaders-source fills`` prend EXACTEMENT les comptes suivis pour les fills ;
3. si cette sélection est vide, on retombe sur la liste partagée **en l'annonçant** — un désalignement
   silencieux est précisément ce qui a coûté la mesure ;
4. la sélection n'est jamais dupliquée : on réutilise ``vaults_suivis`` (source unique de vérité).
"""
from __future__ import annotations

import ast
import sys
import types
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))
sys.path.insert(0, str(RACINE / "src"))
sys.path.insert(0, str(RACINE / "tools"))

OUTIL = RACINE / "tools" / "collecter_contexte_lane.py"


def _module():
    import importlib.util
    spec = importlib.util.spec_from_file_location("contexte_lane_test", OUTIL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


A = "0x" + "a" * 40
B = "0x" + "b" * 40
C = "0x" + "c" * 40


def _ecrire_liste(root: Path, vaults: list[str]) -> str:
    import json
    (root / "config").mkdir(parents=True, exist_ok=True)
    chemin = "config/copy_vault_leaders.json"
    (root / chemin).write_text(json.dumps({"vaults": vaults}), encoding="utf-8")
    return chemin


# ------------------------------------------------------------------ défaut inchangé

def test_par_defaut_on_lit_la_liste_partagee(tmp_path):
    """Les lanes cloud ne doivent RIEN voir changer."""
    mod = _module()
    chemin = _ecrire_liste(tmp_path, [A, B])
    leaders, source, raison = mod.choisir_les_leaders(tmp_path, source=mod.SOURCE_FICHIER,
                                                      chemin=chemin)
    assert leaders == [A, B]
    assert source == mod.SOURCE_FICHIER
    assert chemin in raison


def test_une_source_inconnue_retombe_sur_le_fichier(tmp_path):
    mod = _module()
    chemin = _ecrire_liste(tmp_path, [A])
    leaders, source, _r = mod.choisir_les_leaders(tmp_path, source="n_importe_quoi", chemin=chemin)
    assert leaders == [A] and source == mod.SOURCE_FICHIER


# ------------------------------------------------------------------ alignement demandé

def test_la_source_fills_prend_exactement_les_comptes_suivis_pour_les_fills(tmp_path):
    mod = _module()
    chemin = _ecrire_liste(tmp_path, [A, B])            # la liste partagée dit A et B
    leaders, source, raison = mod.choisir_les_leaders(
        tmp_path, source=mod.SOURCE_FILLS, chemin=chemin,
        selection_fills=lambda _root: [B, C])           # les fills, eux, couvrent B et C
    assert leaders == [B, C]                            # on suit les fills, pas la liste partagée
    assert source == mod.SOURCE_FILLS
    assert "alignes sur les fills" in raison
    assert "1 aussi dans" in raison                     # le recouvrement est rendu VISIBLE


def test_le_recouvrement_nul_est_visible_dans_la_raison(tmp_path):
    """C'est l'information qui manquait : savoir que les deux ensembles ne se touchent pas."""
    mod = _module()
    chemin = _ecrire_liste(tmp_path, [A])
    _l, _s, raison = mod.choisir_les_leaders(tmp_path, source=mod.SOURCE_FILLS, chemin=chemin,
                                             selection_fills=lambda _root: [B, C])
    assert "0 aussi dans" in raison


# ------------------------------------------------------------------ jamais zéro en silence

def test_une_selection_de_fills_vide_retombe_sur_le_fichier_EN_L_ANNONCANT(tmp_path):
    mod = _module()
    chemin = _ecrire_liste(tmp_path, [A, B])
    leaders, source, raison = mod.choisir_les_leaders(tmp_path, source=mod.SOURCE_FILLS,
                                                      chemin=chemin,
                                                      selection_fills=lambda _root: [])
    assert leaders == [A, B]                            # on ne reste pas sans leader
    assert source == mod.SOURCE_FICHIER
    assert "ATTENTION" in raison and "desalignes" in raison


def test_tout_vide_ne_leve_pas(tmp_path):
    mod = _module()
    leaders, _s, _r = mod.choisir_les_leaders(tmp_path, source=mod.SOURCE_FILLS,
                                              chemin="config/absent.json",
                                              selection_fills=lambda _root: [])
    assert leaders == []                                # l'appelant décidera (il affiche « aucun leader »)


# ------------------------------------------------------------------ lecture de la sélection réelle

def test_la_selection_reelle_filtre_et_dedoublonne(monkeypatch, tmp_path):
    """Le filtre applique DELIBEREMENT la meme regle que le chargeur de la liste partagee
    (`0x` + au moins 10 caracteres). Etre plus strict ici creerait une incoherence absurde : un
    meme compte accepte depuis le fichier mais rejete depuis les fills."""
    mod = _module()
    faux = types.ModuleType("collecter_userfills_vaults")
    faux.vaults_suivis = lambda _root: [A, A, B, "pas-une-adresse", "", "0x123", None]
    monkeypatch.setitem(sys.modules, "collecter_userfills_vaults", faux)
    assert mod.leaders_alignes_sur_les_fills(tmp_path) == [A, B]


def test_le_filtre_est_le_MEME_que_celui_de_la_liste_partagee(monkeypatch, tmp_path):
    """Non-regression du choix ci-dessus : les deux sources doivent accepter/rejeter a l'identique."""
    mod = _module()
    douteux = ["0xabcdef1234", "0x123", "pas-une-adresse", ""]
    chemin = _ecrire_liste(tmp_path, douteux)
    faux = types.ModuleType("collecter_userfills_vaults")
    faux.vaults_suivis = lambda _root: list(douteux)
    monkeypatch.setitem(sys.modules, "collecter_userfills_vaults", faux)
    assert mod.leaders_alignes_sur_les_fills(tmp_path) == mod._charger_leaders(tmp_path, chemin)


def test_la_selection_reelle_echoue_ouvert(monkeypatch, tmp_path):
    """Si la sélection est indisponible, on rend [] (puis l'appelant retombe sur le fichier) — jamais
    une exception : l'alignement est un confort, pas un point de panne."""
    mod = _module()
    faux = types.ModuleType("collecter_userfills_vaults")

    def _explose(_root):
        raise RuntimeError("scores illisibles")

    faux.vaults_suivis = _explose
    monkeypatch.setitem(sys.modules, "collecter_userfills_vaults", faux)
    assert mod.leaders_alignes_sur_les_fills(tmp_path) == []


# ------------------------------------------------------------------ CANARI : source unique de vérité

def test_CANARI_on_reutilise_vaults_suivis_sans_dupliquer_la_selection():
    """Dupliquer la logique de sélection (CORE + sentinelles + rotation) garantirait une divergence
    silencieuse le jour où elle change. On exige l'appel de `vaults_suivis`, et l'absence de toute
    re-implémentation (pas de lecture de vaults_scores.json ici)."""
    src = OUTIL.read_text(encoding="utf-8")
    arbre = ast.parse(src)
    fn = next(n for n in arbre.body if isinstance(n, ast.FunctionDef)
              and n.name == "leaders_alignes_sur_les_fills")
    attrs = {n.attr for n in ast.walk(fn) if isinstance(n, ast.Attribute)}
    assert "vaults_suivis" in attrs, "il faut APPELER vaults_suivis (source unique)"
    assert "vaults_scores" not in src, "pas de re-lecture des scores : ce serait une selection dupliquee"
    assert "SENTINELLES" not in src, "pas de re-implementation des sentinelles"


def test_CANARI_le_defaut_reste_le_fichier_partage():
    """Garde-fou de non-regression : si quelqu'un passe le defaut a 'fills', les lanes cloud
    (qui n'ont pas de collecteur de fills local) perdraient leurs leaders."""
    src = OUTIL.read_text(encoding="utf-8")
    assert 'default=SOURCE_FICHIER' in src
    assert 'choices=(SOURCE_FICHIER, SOURCE_FILLS)' in src


# ------------------------------------------------------------------ ligne de vie (choix porteur)

class _Lane:
    positions = 3
    portefeuilles = 1
    twap = 0
    ordres = 7
    reconnects = 0


def test_la_ligne_de_vie_est_emise_a_chaque_intervalle(capsys):
    """Le superviseur juge cette lane sur la fraicheur de son LOG : elle doit parler regulierement."""
    import asyncio
    mod = _module()
    horloge = {"t": 0.0}

    async def dormir(d):
        horloge["t"] += float(d)

    lignes = asyncio.run(mod._battement(_Lane(), deadline=180.0, intervalle_s=60.0,
                                        dormir=dormir, horloge=lambda: horloge["t"]))
    assert lignes == 2                       # a 60 s et 120 s ; a 180 s on est a l'echeance
    sortie = capsys.readouterr().out
    assert sortie.count("[contexte] vivant") == 2
    assert "7 carnets d'ordres" in sortie


def test_la_ligne_de_vie_ne_parle_pas_apres_l_echeance(capsys):
    import asyncio
    mod = _module()
    horloge = {"t": 0.0}

    async def dormir(d):
        horloge["t"] += float(d)

    lignes = asyncio.run(mod._battement(_Lane(), deadline=0.0, intervalle_s=60.0,
                                        dormir=dormir, horloge=lambda: horloge["t"]))
    assert lignes == 0 and "vivant" not in capsys.readouterr().out


def test_CANARI_pas_de_heartbeat_declare_DONC_une_ligne_de_vie_obligatoire():
    """INVARIANT COUPLE. L'entree de registre `contexte-leaders` ne declare PAS de fichier heartbeat
    (la lane n'en ecrit pas) : sa vie est donc jugee sur la fraicheur du log. Si quelqu'un retire la
    ligne de vie, un marche calme ferait relancer un processus VIVANT (double collecte). Ce test lie
    les deux faits pour qu'on ne puisse pas casser l'un sans voir l'autre.
    """
    sys.path.insert(0, str(RACINE / "src"))
    from hl_observer.ops import collecteur_registry as R

    entree = next(c for c in R.REGISTRE if c["nom"] == "contexte-leaders")
    src = OUTIL.read_text(encoding="utf-8")

    if not entree.get("heartbeat"):
        assert "_battement" in src, ("pas de heartbeat declare : la lane DOIT emettre une ligne de vie "
                                     "(sinon le superviseur relance un vivant)")
        assert "_battement(lane, deadline)" in src, "la ligne de vie doit etre LANCEE dans la boucle"
    assert entree["args"][:2] == ("--leaders-source", "fills"), \
        "l'entree locale doit aligner les ordres sur les fills (cause racine de R2)"
    assert entree["limite_minutes"] * 60 > entree["intervalle_s"] * 1.5, "regle anti-relance"
