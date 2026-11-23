from datetime import date

import stockage
import suivi


def _entree(id_, **champs):
    return {"id": id_, "date": "2026-11-02T10:00:00", "entreprise": f"E{id_}", **champs}


def test_changer_statut_date_automatiquement(projet_temporaire):
    stockage.ajouter_historique(_entree("a"))
    suivi.changer_statut("a", "envoyee", le=date(2026, 11, 3))
    entree = stockage.charger_historique()[0]
    assert entree["statut"] == "envoyee" and entree["date_envoi"] == "2026-11-03"
    suivi.changer_statut("a", "relancee", le=date(2026, 11, 20))
    entree = stockage.charger_historique()[0]
    assert entree["date_envoi"] == "2026-11-03" and entree["date_relance"] == "2026-11-20"


def test_relances_et_statistiques():
    historique = [
        _entree("a", statut="envoyee", date_envoi="2026-11-01"),  # 22 jours : à relancer
        _entree("b", statut="envoyee", date_envoi="2026-11-20"),  # trop récent
        _entree("c", statut="relancee", date_envoi="2026-10-01", date_relance="2026-11-01"),  # 2e relance
        _entree("d", statut="entretien", date_envoi="2026-10-01"),
        _entree("e"),  # jamais suivie : ignorée partout, sans erreur
        {"date": "date invalide", "entreprise": "Ancienne", "statut": "statut inconnu"},
    ]
    relances = suivi.candidatures_a_relancer(historique, aujourd_hui=date(2026, 11, 23))
    assert [r.entree["id"] for r in relances] == ["a", "c"]
    assert relances[1].deuxieme

    stats = suivi.statistiques(historique, aujourd_hui=date(2026, 11, 23))
    assert (stats.total, stats.envoyees, stats.reponses, stats.entretiens) == (6, 4, 1, 1)
    assert stats.taux_reponse == 0.25
    assert stats.par_semaine["2026-11-02"] == 5  # semaine du lundi 2 novembre
    assert suivi.statut(historique[-1]) == ""


def test_badges():
    assert suivi.badge("envoyee") == ":blue-badge[:material/send: Envoyée]"
    assert suivi.libelle("inconnu") == "Générée"


def test_export_csv_pour_tableur():
    historique = [
        {"date": "2026-11-20T10:00:00", "entreprise": "=HYPERLINK(\"http://pirate.example\")", "poste": "Data; BI",
         "statut": "envoyee", "date_envoi": "2026-11-21", "score": 80, "notes": "Ligne 1\nLigne 2"},
        {"date": "2026-11-19T09:00:00", "entreprise": "Exemple", "poste": "-Analyste"},
    ]
    contenu = suivi.exporter_csv(historique)
    assert contenu.startswith("\ufeff".encode())  # Excel reconnaît l'UTF-8 (accents corrects)
    import csv
    import io

    lignes = list(csv.reader(io.StringIO(contenu.decode("utf-8-sig")), delimiter=";"))
    assert lignes[0][:4] == ["Date", "Entreprise", "Poste", "Statut"]
    assert lignes[1][1].startswith("'=")  # formule neutralisée
    assert lignes[1][2] == "Data; BI" and lignes[1][3] == "Envoyée" and lignes[1][6] == "80"
    assert lignes[1][10] == "Ligne 1\nLigne 2"
    assert lignes[2][2] == "'-Analyste" and lignes[2][3] == "Générée"


def test_date_de_reponse_et_source(projet_temporaire):
    stockage.ajouter_historique({"id": "r1", "date": "2026-11-02T10:00:00", "url_offre": "https://fr.indeed.com/x"})
    suivi.changer_statut("r1", "envoyee", le=date(2026, 11, 3))
    suivi.changer_statut("r1", "entretien", le=date(2026, 11, 10))
    suivi.changer_statut("r1", "acceptee", le=date(2026, 11, 20))  # la 1re réponse compte
    entree = stockage.charger_historique()[0]
    assert entree["date_reponse"] == "2026-11-10" and suivi.delai_reponse(entree) == 7
    assert suivi.source_offre(entree) == "Indeed"
    assert suivi.source_offre({"url_offre": "https://careers.exemple-energie.fr/offre/12"}) == "exemple-energie.fr"
    assert suivi.source_offre({"url_offre": "www.welcometothejungle.com/fr/jobs/x"}) == "Welcome to the Jungle"
    assert suivi.source_offre({}) == "Non renseignée"
