"""Rapport de candidatures : calculs et PDF (données fictives)."""

from datetime import date, timedelta

import pypdfium2 as pdfium

import rapport

AUJOURD_HUI = date(2026, 11, 23)


def _historique() -> list[dict]:
    lignes = [
        ("Nova Énergie", "https://www.welcometothejungle.com/fr/x", "acceptee", 82, 1, 8),
        ("Exemple & Fils", "https://www.linkedin.com/jobs/view/1", "relancee", 74, 1, None),
        ("Atelier Lumière", "https://fr.indeed.com/x", "refusee", 61, 1, 10),
        ("Mutuelle Horizon", "https://www.linkedin.com/jobs/view/2", "envoyee", 70, 1, None),
        ("Clinique Exemple", "", "", None, None, None),
    ]
    historique = []
    for rang, (entreprise, url, statut, score, envoi, reponse) in enumerate(lignes):
        jour = AUJOURD_HUI - timedelta(days=5 * rang + 2)
        entree = {"id": f"e{rang}", "date": f"{jour.isoformat()}T09:00:00", "entreprise": entreprise,
                  "poste": "Data Analyst", "url_offre": url, "statut": statut}
        if score is not None:
            entree["score"] = score
        if envoi is not None:
            entree["date_envoi"] = (jour + timedelta(days=envoi)).isoformat()
        if reponse is not None:
            entree["date_reponse"] = (jour + timedelta(days=envoi + reponse)).isoformat()
        historique.append(entree)
    historique.append({"id": "ancienne", "date": "2025-01-10T10:00:00", "entreprise": "Hors période"})
    return historique


def test_periodes():
    assert rapport.periode("30 derniers jours", AUJOURD_HUI) == rapport.Periode(date(2026, 10, 25), AUJOURD_HUI)
    assert rapport.periode("Ce mois-ci", AUJOURD_HUI).debut == date(2026, 11, 1)
    assert rapport.periode("Mois dernier", AUJOURD_HUI) == rapport.Periode(date(2026, 10, 1), date(2026, 10, 31))
    assert rapport.periode("Personnalisée", AUJOURD_HUI, date(2026, 11, 10), date(2026, 11, 1)) == \
        rapport.Periode(date(2026, 11, 1), date(2026, 11, 10))
    assert rapport.periode("Depuis le début", AUJOURD_HUI).debut is None


def test_calculs():
    donnees = rapport.calculer(_historique(), rapport.periode("30 derniers jours", AUJOURD_HUI), AUJOURD_HUI)
    assert donnees.total == 5  # l'entrée de 2025 est hors période
    assert (donnees.envoyees, donnees.reponses, donnees.entretiens, donnees.acceptees) == (4, 2, 1, 1)
    assert donnees.taux_reponse == 0.5 and donnees.delai_moyen == 9
    assert donnees.score_moyen == (82 + 74 + 61 + 70) / 4
    # Tri par nombre de candidatures, « Non renseignée » toujours en dernier
    assert [s.nom for s in donnees.sources] == ["LinkedIn", "Indeed", "Welcome to the Jungle", "Non renseignée"]
    assert donnees.activite_par == "semaine" and sum(n for _, n in donnees.activite) == 5
    assert rapport.phrase_resume(donnees) == "5 candidatures préparées, 4 envoyées, 2 réponses (50 %) et 1 entretien."
    assert any("Délai moyen" in c for c in rapport.constats(donnees))
    assert donnees.libelle_periode == "Du 25 octobre au 23 novembre 2026"


def test_sans_suivi_ni_candidature():
    sans_suivi = [{"id": "a", "date": "2026-11-20T10:00:00", "entreprise": "A"}]
    donnees = rapport.calculer(sans_suivi, rapport.periode("Ce mois-ci", AUJOURD_HUI), AUJOURD_HUI)
    assert rapport.phrase_resume(donnees) == "1 candidature préparée."  # rien sur le suivi s'il n'est pas utilisé
    vide = rapport.calculer([], rapport.periode("Ce mois-ci", AUJOURD_HUI), AUJOURD_HUI)
    assert rapport.phrase_resume(vide) == "Aucune candidature sur cette période."
    assert rapport.generer_pdf(vide, nom="Camille Martin").startswith(b"%PDF")


def test_pdf_complet():
    donnees = rapport.calculer(_historique(), rapport.periode("Depuis le début", AUJOURD_HUI), AUJOURD_HUI)
    pdf = rapport.generer_pdf(donnees, nom="Camille Martin", ville="Lyon")
    document = pdfium.PdfDocument(pdf)
    try:
        pages = len(document)
        texte = "".join(document[i].get_textpage().get_text_range() for i in range(pages))
    finally:
        document.close()
    assert "Recherche d’alternance" in texte and "Lyon, le 23 novembre 2026" in texte
    assert "Exemple & Fils" in texte  # caractères spéciaux échappés, pas perdus
    assert "Détail des candidatures" in texte and "Hors période" in texte
    assert f"1 / {pages}" in texte  # numérotation des pages


def test_polices_de_secours(monkeypatch):
    import reportlab.pdfbase.pdfmetrics as metriques
    import reportlab.pdfbase.ttfonts as ttfonts

    monkeypatch.setattr(metriques, "getRegisteredFontNames", lambda: [])

    def police_absente(*args, **kwargs):
        raise OSError("police introuvable")

    monkeypatch.setattr(ttfonts, "TTFont", police_absente)
    assert rapport._polices()[0] == "Helvetica"
