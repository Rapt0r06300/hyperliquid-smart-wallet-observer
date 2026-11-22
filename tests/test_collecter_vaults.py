"""COLLECTEUR DE VAULTS HL (chantier COPY, 23/07). La dernière porte copy : répliquer une trajectoire
de vault (horizon jours) où nos 62 s sont négligeables. Ces tests prouvent qu'on capture TOUT (NAV,
positions, expo, levier, PnL latent+réalisé, drawdown, delta d'expo), qu'on exclut les vaults de MM,
et qu'on n'invente rien. Aucun réseau réel : tout bouchonné.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]


def _mod():
    spec = importlib.util.spec_from_file_location("cv", RACINE / "tools" / "collecter_vaults.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


_CH = {"marginSummary": {"accountValue": "10000.0"},
       "assetPositions": [
           {"position": {"coin": "ETH", "szi": "5.0", "entryPx": "3000", "positionValue": "15000",
                         "unrealizedPnl": "200", "leverage": {"value": 3}}},
           {"position": {"coin": "BTC", "szi": "-0.2", "entryPx": "60000", "positionValue": "12000",
                         "unrealizedPnl": "-100", "leverage": {"value": 2}}}]}
_VD = {"leader": "0xabc", "apr": 0.5, "portfolio": [
    ["day", {}], ["allTime", {"accountValueHistory": [[1, "100"], [2, "120"], [3, "90"]],
                              "pnlHistory": [[1, "0"], [3, "-10"]]}]]}


def test_clearinghouse_capture_nav_expo_levier_pnl_latent():
    m = _mod()
    r = m.parser_clearinghouse(_CH)
    assert r["nav_usd"] == 10000.0 and r["n_positions"] == 2
    assert r["expo_brute_usd"] == 27000.0 and r["expo_nette_usd"] == 3000.0   # 15000-12000
    assert r["levier"] == 2.7 and r["pnl_latent_usd"] == 100.0                # 200-100
    assert m.parser_clearinghouse("nawak") is None                           # illisible -> None


def test_vault_details_capture_hist_et_pnl_realise():
    m = _mod()
    r = m.parser_vault_details(_VD)
    assert r["nav_hist"] == [100.0, 120.0, 90.0] and r["pnl_realise_usd"] == -10.0
    assert m.parser_vault_details("nawak")["nav_hist"] == []                  # tolérant


def test_drawdown_pic_a_creux():
    m = _mod()
    assert m.drawdown_pct([100, 120, 90]) == -25.0                            # (90-120)/120
    assert m.drawdown_pct([]) == 0.0


def test_snapshot_calcule_le_DELTA_d_exposition():
    m = _mod()
    cs = m.parser_clearinghouse(_CH)
    vd = m.parser_vault_details(_VD)
    snap = m.construire_snapshot("0xv", cs, vd, now=1000.0, etat_prec={"expo_nette_usd": 2000.0})
    assert snap["delta_expo_nette_usd"] == 1000.0                             # 3000 - 2000
    assert snap["drawdown_pct"] == -25.0 and snap["real_execution"] is False


def test_les_vaults_de_MARKET_MAKING_sont_exclus(tmp_path):
    m = _mod()
    d = tmp_path / "runtime" / "data"
    d.mkdir(parents=True)
    hlp = next(iter(m.VAULTS_EXCLUS))
    (d / "vaults_suivis.json").write_text(json.dumps({"vaults": ["0xDIRECTIONNEL", hlp, "0xdirectionnel"]}),
                                          encoding="utf-8")
    assert m.charger_vaults_suivis(tmp_path) == ["0xdirectionnel"]            # HLP exclu, dédupliqué


def test_une_passe_ecrit_un_snapshot_complet(tmp_path, monkeypatch):
    m = _mod()

    def faux_post(charge, **_k):
        return _CH if charge.get("type") == "clearinghouseState" else _VD

    monkeypatch.setattr(m, "_post_info", faux_post)
    n = m.une_passe(tmp_path, ["0xv"], now=1000.0)
    assert n == 1
    snap = json.loads((tmp_path / m.SORTIE).read_text(encoding="utf-8").splitlines()[0])
    assert snap["vault"] == "0xv" and snap["nav_usd"] == 10000.0 and snap["levier"] == 2.7
    assert snap["pnl_realise_usd"] == -10.0 and snap["n_positions"] == 2


def test_reseau_coupe_ne_tue_pas_la_passe(tmp_path, monkeypatch):
    m = _mod()

    def boom(*_a, **_k):
        raise OSError("reseau")

    monkeypatch.setattr(m, "_post_info", boom)
    assert m.une_passe(tmp_path, ["0xv"], now=1000.0) == 0


def test_resume_honnete_quand_vide(tmp_path):
    m = _mod()
    assert m.resume(tmp_path)["verdict"] == "AUCUN_VAULT_SUIVI_OU_COLLECTE"


def _snaps(net, *, jours=4.0, dd=-10.0, n=15):
    pas = jours * 86_400_000.0 / n
    return [{"nav_usd": 10000.0, "expo_brute_usd": 20000.0, "expo_nette_usd": net,
             "levier": 2.0, "drawdown_pct": dd, "ts_ms": int(i * pas)} for i in range(n)]


def test_classer_retient_un_DIRECTIONNEL_sain():
    m = _mod()
    r = m.classer_vault(_snaps(15000.0))                       # net/gross = 0.75 -> directionnel
    assert r["verdict"] == "RETENU_DIRECTIONNEL" and r["directionnalite"] == 0.75


def test_classer_ECARTE_un_market_maker_net_proche_de_zero():
    m = _mod()
    assert m.classer_vault(_snaps(300.0))["verdict"] == "ECARTE_MARKET_MAKING"   # net/gross 0.015


def test_classer_ECARTE_un_vault_trop_jeune():
    m = _mod()
    assert m.classer_vault(_snaps(15000.0, jours=1.0))["verdict"] == "ECARTE_TROP_JEUNE"


def test_classer_ne_se_fie_ni_au_nom_ni_a_l_apr_et_exige_de_la_donnee():
    m = _mod()
    assert m.classer_vault(_snaps(15000.0, n=5))["verdict"] == "INSUFFISANT"      # < 10 snapshots


def test_import_assiste_fusionne_et_exclut_les_MM(tmp_path):
    m = _mod()
    hlp = next(iter(m.VAULTS_EXCLUS))
    assert m.importer_vaults(tmp_path, ["0xAAA", hlp, "0xaaa", "0xBBB"]) == 2   # dédup + HLP exclu
    assert set(m.charger_vaults_suivis(tmp_path)) == {"0xaaa", "0xbbb"}


def _vault_public(address, *, tvl=250_000, age_days=100, now_ms=2_000_000_000_000,
                  closed=False, relationship="normal", apr=0.25):
    return {
        "apr": apr,
        "summary": {
            "vaultAddress": address,
            "name": f"Vault {address[-4:]}",
            "tvl": tvl,
            "isClosed": closed,
            "relationship": {"type": relationship},
            "createTimeMillis": now_ms - age_days * 86_400_000,
        },
    }


def test_parser_univers_public_filtre_et_trie_sans_promouvoir():
    m = _mod()
    now_ms = 2_000_000_000_000
    first = "0x1111111111111111111111111111111111111111"
    second = "0x2222222222222222222222222222222222222222"
    payload = [
        _vault_public(first, tvl=300_000, now_ms=now_ms),
        _vault_public(second, tvl=900_000, now_ms=now_ms),
        _vault_public("0x3333333333333333333333333333333333333333", tvl=99_999, now_ms=now_ms),
        _vault_public("0x4444444444444444444444444444444444444444", age_days=44, now_ms=now_ms),
        _vault_public("0x5555555555555555555555555555555555555555", closed=True, now_ms=now_ms),
        _vault_public("0x6666666666666666666666666666666666666666", relationship="child", now_ms=now_ms),
        _vault_public("0xtronquee...", now_ms=now_ms),
        _vault_public(second.upper().replace("0X", "0x"), tvl=800_000, now_ms=now_ms),
    ]

    result = m.parser_univers_public(payload, now_ms=now_ms)

    assert [row["address"] for row in result] == [second, first]
    assert all(row["observation_only"] is True for row in result)
    assert result[0]["tvl_usd"] == 900_000


def test_rafraichissement_public_preserve_manuel_et_provenance(tmp_path):
    m = _mod()
    now_ms = 2_000_000_000_000
    managed = "0x1111111111111111111111111111111111111111"
    manual = "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    fresh = "0x2222222222222222222222222222222222222222"
    destination = tmp_path / m.CONFIG
    destination.parent.mkdir(parents=True)
    destination.write_text(json.dumps({
        "_provenance": {"vaults": [{"address": managed}]},
        "vaults": [managed, manual],
    }), encoding="utf-8")

    result = m.rafraichir_univers_public(
        tmp_path,
        fetcher=lambda: [_vault_public(fresh, now_ms=now_ms)],
        now_ms=now_ms,
    )

    assert result["vaults"] == [fresh, manual]
    assert result["_provenance"]["source"] == m.URL_VAULTS
    assert result["_provenance"]["manual_preserved"] == [manual]
    assert json.loads(destination.read_text(encoding="utf-8")) == result


def test_rafraichissement_vide_preserve_strictement_ancien_fichier(tmp_path):
    m = _mod()
    destination = tmp_path / m.CONFIG
    destination.parent.mkdir(parents=True)
    original = '{"vaults":["0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"]}'
    destination.write_text(original, encoding="utf-8")

    try:
        m.rafraichir_univers_public(tmp_path, fetcher=lambda: [])
    except ValueError as exc:
        assert "préservé" in str(exc)
    else:
        raise AssertionError("un univers vide doit échouer fail-closed")

    assert destination.read_text(encoding="utf-8") == original


# ---------------------------------- biais du survivant (mesure du 21/11/2026)
def _payload_mixte(maintenant: int) -> list[dict]:
    vieux = maintenant - 90 * 86_400_000
    def ligne(suffixe, *, ferme, tvl, cree, relation="normal"):
        return {"summary": {"isClosed": ferme, "vaultAddress": "0x" + suffixe * 40,
                            "name": "v" + suffixe, "tvl": str(tvl),
                            "createTimeMillis": cree,
                            "relationship": {"type": relation}}, "apr": 0.2}
    return [
        ligne("a", ferme=False, tvl=500_000, cree=vieux),
        ligne("b", ferme=True, tvl=900_000, cree=vieux),            # ferme
        ligne("c", ferme=False, tvl=10, cree=vieux),                # tvl insuffisant
        ligne("d", ferme=False, tvl=500_000, cree=maintenant - 3_600_000),  # trop jeune
        ligne("e", ferme=False, tvl=500_000, cree=vieux, relation="child"),  # relation
    ]


def test_un_vault_ferme_est_ecarte_mais_PLUS_efface():
    """Sans trace des ecartes, toute statistique sur << les vaults qu'on suit >> est
    biaisee vers le haut : un vault qui ferme apres une perte disparaissait.

    Le /goal interdit explicitement le biais du survivant. Le filtre ne change pas --
    aucun vault ferme n'entre dans l'univers d'observation -- il devient VISIBLE.
    """
    m = _mod()
    maintenant = 1_800_000_000_000
    rejets: list[dict] = []
    retenus = m.parser_univers_public(_payload_mixte(maintenant), now_ms=maintenant,
                                      rejets=rejets)
    assert [r["address"] for r in retenus] == ["0x" + "a" * 40]
    motifs = {r["address"]: r["motif"] for r in rejets}
    assert motifs["0x" + "b" * 40] == "vault_ferme"
    assert motifs["0x" + "c" * 40] == "tvl_insuffisant_ou_creation_invalide"
    assert motifs["0x" + "d" * 40] == "trop_jeune"
    assert motifs["0x" + "e" * 40] == "relation_non_normale"
    # Le vault ferme garde son drapeau : on doit pouvoir le reconnaitre plus tard.
    ferme = next(r for r in rejets if r["motif"] == "vault_ferme")
    assert ferme["is_closed"] is True


def test_l_univers_rendu_est_INCHANGE_pour_les_consommateurs():
    """Le correctif AJOUTE une trace ; il ne doit rien changer a la liste rendue."""
    m = _mod()
    maintenant = 1_800_000_000_000
    sans = m.parser_univers_public(_payload_mixte(maintenant), now_ms=maintenant)
    avec = m.parser_univers_public(_payload_mixte(maintenant), now_ms=maintenant, rejets=[])
    assert sans == avec


def test_l_horodatage_de_creation_absolu_est_conserve():
    """`age_j` depend de l'heure du collecteur : un rejeu ne peut pas le reproduire."""
    m = _mod()
    maintenant = 1_800_000_000_000
    retenus = m.parser_univers_public(_payload_mixte(maintenant), now_ms=maintenant)
    assert retenus[0]["created_at_ms"] == maintenant - 90 * 86_400_000
    # Et la valeur relative reste la, pour ne casser aucun consommateur.
    assert retenus[0]["age_j"] == 90.0


def test_la_trace_des_rejets_est_BORNEE():
    """L'univers officiel compte des milliers d'entrees : la trace ne doit pas enfler."""
    m = _mod()
    maintenant = 1_800_000_000_000
    fermes = [{"summary": {"isClosed": True, "vaultAddress": f"0x{i:040d}",
                           "name": "x", "tvl": "1", "createTimeMillis": 1,
                           "relationship": {"type": "normal"}}}
              for i in range(m.MAX_REJETS_TRACES + 50)]
    rejets: list[dict] = []
    m.parser_univers_public(fermes, now_ms=maintenant, rejets=rejets)
    assert len(rejets) == m.MAX_REJETS_TRACES


def test_une_trace_ne_fait_jamais_tomber_la_collecte():
    """Une ligne inattendue ne doit pas lever : la trace est un bonus, pas une porte."""
    m = _mod()
    rejets: list[dict] = []
    m._noter_rejet(rejets, None, None, "motif_sans_contexte")
    assert rejets[0]["address"] == "" and rejets[0]["motif"] == "motif_sans_contexte"


# ------------- refus du levier et du PnL latent (quatre cas mesures le 21/11/2026)
def _etat_compte(nav, *, pv="15000", upnl="-500"):
    return {"marginSummary": {"accountValue": nav},
            "assetPositions": [{"position": {"coin": "ETH", "szi": "5.0", "entryPx": "3000",
                                             "positionValue": pv, "unrealizedPnl": upnl,
                                             "leverage": {"value": "20"}}}]}


def test_un_nav_nul_avec_exposition_REFUSE_au_lieu_de_dire_zero():
    """Un compte a NAV nul AVEC 15 000 $ d'exposition a un levier INFINI : l'etat le plus
    dangereux qui existe. Il etait rapporte `0.0` -- << aucun levier >>.

    La version honnete existait deja dans le depot :
    `portefeuille_compte.construire_portefeuille` rend `None` dans ce cas.
    """
    m = _mod()
    for nav in ("0", "-250"):
        r = m.parser_clearinghouse(_etat_compte(nav))
        assert r["levier"] is None, nav
        assert r["levier_refus"] == "nav_non_exploitable"
        # L'exposition reste PUBLIEE : on refuse le ratio, on ne cache pas le fait.
        assert r["expo_brute_usd"] == 15000.0


def test_une_valeur_de_position_illisible_refuse_le_levier():
    """Comptee 0, elle SOUS-ESTIME l'exposition, donc le levier : un faux rassurant."""
    m = _mod()
    r = m.parser_clearinghouse(_etat_compte("10000", pv="n/a"))
    assert r["levier"] is None
    assert r["levier_refus"] == "exposition_incomplete"
    assert r["positions_valeur_illisible"] == 1
    assert r["expo_complete"] is False


def test_un_upnl_illisible_ne_devient_pas_un_resultat_neutre():
    """Somme a 0, un inconnu passait pour un PnL latent nul."""
    m = _mod()
    r = m.parser_clearinghouse(_etat_compte("10000", upnl="n/a"))
    assert r["pnl_latent_usd"] is None
    assert r["positions_upnl_illisible"] == 1
    # La somme partielle reste disponible, nommee pour ce qu'elle est.
    assert r["pnl_latent_partiel_usd"] == 0.0


def test_un_compte_sain_repond_toujours_normalement():
    """Le refus ne doit pas se declencher sur le cas courant."""
    m = _mod()
    r = m.parser_clearinghouse(_etat_compte("10000"))
    assert r["levier"] == 1.5
    assert r["levier_refus"] is None
    assert r["pnl_latent_usd"] == -500.0
    assert r["expo_complete"] is True


def test_le_snapshot_complet_SURVIT_aux_refus_du_parseur():
    """Garde contre une regression que le correctif du 21/11/2026 pouvait introduire.

    `construire_snapshot` copie `cs["levier"]` et `cs["pnl_latent_usd"]`, qui valent
    desormais `None` quand le parseur refuse. Un consommateur qui ferait
    `f"{levier:.2f}"` leverait TypeError. Verifie ici que le snapshot se construit ET se
    serialise dans les quatre cas -- mesure, pas deduction.
    """
    import json as _json
    m = _mod()
    for etat in (_etat_compte("10000"), _etat_compte("0"),
                 _etat_compte("10000", pv="n/a"), _etat_compte("10000", upnl="n/a")):
        cs = m.parser_clearinghouse(etat)
        snap = m.construire_snapshot("0xaa", cs, {"pnl_realise_usd": 12.0},
                                     now=1_700_000_000.0, etat_prec=None)
        assert _json.dumps(snap)
        assert snap["nav_usd"] == cs["nav_usd"]
        assert snap["levier"] == cs["levier"]
