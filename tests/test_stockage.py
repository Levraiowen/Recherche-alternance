import stockage


def test_profil_aller_retour(projet_temporaire):
    profil = stockage.charger_profil()
    assert profil["nom"] == "" and stockage.profil_incomplet(profil)
    stockage.enregistrer_profil({**profil, "nom": "Camille Martin", "ville": "Lyon"})
    assert stockage.charger_profil()["nom"] == "Camille Martin"


def test_json_corrompu_mis_de_cote(projet_temporaire):
    stockage.FICHIER_HISTORIQUE.parent.mkdir(parents=True, exist_ok=True)
    stockage.FICHIER_HISTORIQUE.write_text("{ pas du json", encoding="utf-8")
    assert stockage.charger_historique() == []
    sauvegardes = list(stockage.DOSSIER_DATA.glob("historique.corrompu-*.json"))
    assert len(sauvegardes) == 1


def test_historique_ordre_mise_a_jour_suppression(projet_temporaire):
    stockage.ajouter_historique({"id": "a", "date": "2026-01-01T10:00:00", "entreprise": "L'Oréal"})
    stockage.ajouter_historique({"id": "b", "date": "2026-01-02T10:00:00", "entreprise": "Exemple"})
    assert [e["id"] for e in stockage.charger_historique()] == ["b", "a"]
    assert stockage.mettre_a_jour_historique("a", {"poste": "Data Analyst"})
    assert stockage.charger_historique()[1]["poste"] == "Data Analyst"
    stockage.supprimer_historique("b")
    assert [e["id"] for e in stockage.charger_historique()] == ["a"]
    # Ancienne entrée sans identifiant : identifiant dérivé, suppression possible
    stockage.ajouter_historique({"date": "2025-12-01T09:00:00", "entreprise": "Ancienne"})
    ancien = stockage.identifiant_entree(stockage.charger_historique()[0])
    stockage.supprimer_historique(ancien)
    assert [e.get("id") for e in stockage.charger_historique()] == ["a"]


def test_candidatures_precedentes_insensibles_aux_accents(projet_temporaire):
    stockage.ajouter_historique({"id": "a", "date": "2026-01-01T10:00:00", "entreprise": "L'Oréal"})
    assert len(stockage.candidatures_precedentes("l’oreal")) == 1
    assert stockage.candidatures_precedentes("l'oréal", sauf="a") == []


def test_chemins_relatifs(projet_temporaire):
    fichier = stockage.DOSSIER_OUTPUTS / "Exemple" / "x.pdf"
    relatif = stockage.chemin_relatif(fichier)
    assert relatif == "outputs/Exemple/x.pdf"
    assert stockage.resoudre_chemin(relatif) == projet_temporaire / "outputs" / "Exemple" / "x.pdf"
    # Ancien chemin absolu d'un projet déplacé : retrouvé dans le dossier actuel
    ancien = "/home/quelquun/ancien projet/outputs/Exemple/x.pdf"
    attendu = projet_temporaire / "outputs" / "Exemple" / "x.pdf"
    assert stockage.resoudre_chemin(ancien) == attendu


def test_slug_et_dossier(projet_temporaire):
    assert stockage.slugifier_nom_fichier('Data <Analyst> : "IA"?') == "Data Analyst IA"
    assert len(stockage.slugifier_nom_fichier("x" * 300)) == stockage.LONGUEUR_MAX_SLUG
    d1 = stockage.dossier_candidature("Exemple", sous_dossier="Poste_1")
    d2 = stockage.dossier_candidature("Exemple", sous_dossier="Poste_2")
    assert d1 != d2 and d1.exists() and d2.exists()


def test_niveau_cv_memorise(projet_temporaire):
    assert stockage.niveau_cv_memorise("abc") == 0
    stockage.memoriser_niveau_cv("abc", 2)
    assert stockage.niveau_cv_memorise("abc") == 2
    stockage.memoriser_niveau_cv("def", 1)  # nouveau CV : l'ancien réglage est oublié
    assert stockage.niveau_cv_memorise("abc") == 0
