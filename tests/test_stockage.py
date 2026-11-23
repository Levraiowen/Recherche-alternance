import pytest

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


def test_cache_historique_copies_et_modification_externe(projet_temporaire):
    stockage.ajouter_historique({"id": "a", "entreprise": "Alpha"})
    premiere = stockage.charger_historique()
    premiere[0]["entreprise"] = "modifiée en mémoire"
    premiere.append({"id": "intrus"})
    assert stockage.charger_historique() == [{"id": "a", "entreprise": "Alpha"}]  # le cache n'est pas touché
    # Fichier modifié par un autre programme (ou une autre fenêtre de l'app) : relu
    stockage.FICHIER_HISTORIQUE.write_text('[{"id": "b", "entreprise": "Beta"}]', encoding="utf-8")
    assert [e["id"] for e in stockage.charger_historique()] == ["b"]
    stockage.FICHIER_HISTORIQUE.unlink()
    assert stockage.charger_historique() == []


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
    assert stockage.niveau_cv_memorise("abc:LibreOffice") == 0
    stockage.memoriser_niveau_cv("abc:LibreOffice", 2)
    stockage.memoriser_niveau_cv("def:LibreOffice", 1)  # deuxième CV : le premier n'est pas oublié
    assert stockage.niveau_cv_memorise("abc:LibreOffice") == 2
    assert stockage.niveau_cv_memorise("abc") == 2  # convertisseur pas encore connu
    for i in range(stockage.ENTREES_MISE_EN_PAGE_MAX + 2):
        stockage.memoriser_niveau_cv(f"cv{i}:Word", 3)
    assert stockage.niveau_cv_memorise("abc:LibreOffice") == 0  # les plus anciens sont élagués


def test_plusieurs_cv(projet_temporaire, cv_exemple):
    stockage.enregistrer_cv(cv_exemple.read_bytes(), "Mon_CV.docx")
    stockage.ajouter_cv(cv_exemple.read_bytes(), "CV Marketing.docx")
    stockage.ajouter_cv(cv_exemple.read_bytes(), "../../piège")
    noms = [cv.nom for cv in stockage.lister_cvs()]
    assert noms[0] == "Mon_CV (principal)" and "CV Marketing" in noms
    assert all(cv.chemin.resolve().is_relative_to(stockage.DOSSIER_DATA.resolve()) for cv in stockage.lister_cvs())
    stockage.supprimer_cv("CV Marketing")
    assert "CV Marketing" not in [cv.nom for cv in stockage.lister_cvs()]
    assert stockage.FICHIER_CV.exists()  # le CV principal n'est jamais supprimé ainsi


def test_sauvegarde_et_restauration(projet_temporaire, cv_exemple):
    import io
    import zipfile

    stockage.enregistrer_cv(cv_exemple.read_bytes(), "cv.docx")
    stockage.ajouter_historique({"id": "a", "date": "2026-01-01T10:00:00", "entreprise": "Exemple"})
    assert stockage.sauvegarde_automatique() is not None
    assert stockage.sauvegarde_automatique() is None  # une seule par jour
    export = stockage.exporter_donnees()

    stockage.supprimer_historique("a")
    assert stockage.charger_historique() == []
    restaures = stockage.restaurer_sauvegarde(export)
    assert "historique.json" in restaures and stockage.charger_historique()[0]["id"] == "a"

    # Archive piégée : chemins hors du dossier et fichiers inconnus ignorés
    tampon = io.BytesIO()
    with zipfile.ZipFile(tampon, "w") as archive:
        archive.writestr("../../evil.txt", "x")
        archive.writestr("cvs/../../evil.docx", "x")
        archive.writestr("profil.json", '{"nom": "Restauré"}')
    assert stockage.restaurer_sauvegarde(tampon.getvalue()) == ["profil.json"]
    assert not (projet_temporaire.parent / "evil.txt").exists()
    assert stockage.charger_profil()["nom"] == "Restauré"


def _verrouiller(monkeypatch, nom_fichier: str, echecs: int, methode: str = "read_bytes"):
    """Simule un fichier verrouillé (antivirus, OneDrive...) pendant `echecs` accès."""
    from pathlib import Path

    originale = getattr(Path, methode)
    etat = {"restants": echecs}

    def verrouillee(self, *args, **kwargs):
        if self.name == nom_fichier and etat["restants"] > 0:
            etat["restants"] -= 1
            raise PermissionError(13, "fichier utilisé par un autre processus (simulé)")
        return originale(self, *args, **kwargs)

    monkeypatch.setattr(Path, methode, verrouillee)
    return etat


def test_verrou_passager_sans_perte(projet_temporaire, monkeypatch):
    monkeypatch.setattr(stockage, "DELAIS_REESSAI", (0, 0))
    for i in range(5):
        stockage.ajouter_historique({"id": f"e{i}"})
    _verrouiller(monkeypatch, "historique.json", echecs=2)  # réussit à la 3e tentative
    stockage.ajouter_historique({"id": "nouvelle"})
    assert [e["id"] for e in stockage.charger_historique()] == ["nouvelle", "e4", "e3", "e2", "e1", "e0"]


def test_verrou_persistant_rien_n_est_efface(projet_temporaire, monkeypatch):
    monkeypatch.setattr(stockage, "DELAIS_REESSAI", (0, 0))
    for i in range(5):
        stockage.ajouter_historique({"id": f"e{i}"})
    stockage.FICHIER_HISTORIQUE.write_text(stockage.FICHIER_HISTORIQUE.read_text(encoding="utf-8"),
                                           encoding="utf-8")  # cache invalidé
    etat = _verrouiller(monkeypatch, "historique.json", echecs=100)
    with pytest.raises(stockage.ErreurStockage):
        stockage.charger_historique()
    with pytest.raises(OSError):
        stockage.ajouter_historique({"id": "nouvelle"})  # rien n'est écrit par-dessus
    etat["restants"] = 0  # le verrou disparaît
    assert len(stockage.charger_historique()) == 5  # aucune perte, aucun cache vide
    assert not list(stockage.DOSSIER_DATA.glob("*corrompu*"))


def test_fichier_corrompu_impossible_a_mettre_de_cote(projet_temporaire, monkeypatch):
    monkeypatch.setattr(stockage, "DELAIS_REESSAI", (0, 0))
    stockage.DOSSIER_DATA.mkdir(parents=True, exist_ok=True)
    stockage.FICHIER_HISTORIQUE.write_text("[{cassé", encoding="utf-8")
    _verrouiller(monkeypatch, "historique.json", echecs=100, methode="replace")
    with pytest.raises(stockage.ErreurStockage):
        stockage.ajouter_historique({"id": "nouvelle"})
    assert stockage.FICHIER_HISTORIQUE.read_text(encoding="utf-8") == "[{cassé"  # jamais écrasé


def test_restauration_d_archives_abimees(projet_temporaire):
    import io
    import zipfile

    def archive(fichiers: dict[str, bytes], compression=zipfile.ZIP_STORED) -> bytes:
        tampon = io.BytesIO()
        with zipfile.ZipFile(tampon, "w", compression) as z:
            for nom, donnees in fichiers.items():
                z.writestr(nom, donnees)
        return tampon.getvalue()

    abimee = bytearray(archive({"profil.json": b'{"nom": "Camille Martin, une valeur assez longue"}'}))
    abimee[abimee.find(b"Camille")] = ord("K")  # un octet altéré (copie ou téléchargement abîmé)
    cas = {
        "CRC invalide": bytes(abimee),
        "CV qui n'est pas un docx": archive({"cvs/CV Marketing.docx": archive({"x.txt": b"pas un CV"})}),
        "trop de fichiers": archive({f"autre_{i}.txt": b"" for i in range(stockage.ENTREES_MAX_SAUVEGARDE + 1)}),
        "pas un zip": b"ceci n'est pas une archive",
    }
    for nom, contenu in cas.items():
        with pytest.raises(ValueError):
            stockage.restaurer_sauvegarde(contenu)
        assert not stockage.FICHIER_PROFIL.exists(), nom  # rien n'a été écrit
