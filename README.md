# Générateur de candidatures — alternance

[![Tests](https://github.com/Levraiowen/Recherche-alternance/actions/workflows/tests.yml/badge.svg)](https://github.com/Levraiowen/Recherche-alternance/actions/workflows/tests.yml)

App locale (Streamlit) pour préparer en une minute une candidature
personnalisée à partir d'une offre d'alternance :

1. Tu importes ton CV Word une fois (il reste enregistré en local) — ou
   plusieurs, par exemple un CV « Data » et un CV « Marketing ».
2. Tu colles le **lien** de l'offre (l'app récupère le texte, l'entreprise,
   le poste et l'adresse) ou directement son texte.
3. L'app génère, en **PDF prêt à envoyer, chacun sur une seule page** (le
   .docx est aussi gardé) :
   - une **lettre de motivation** au format A4, nommée
     `Lettre_Motivation_Prénom_Nom_(Entreprise).pdf` ;
   - une **version adaptée de ton CV**, nommée `CV_Prénom_Nom_(Entreprise).pdf`,
     avec quelques formulations ajustées pour coller à l'offre — même mise
     en page, même fichier d'origine, mise en forme conservée (libellés en
     gras, dates en italique...) ;
   - un **e-mail d'accompagnement** prêt à copier ou à ouvrir dans ta
     messagerie, et une **analyse de l'offre** (correspondance estimée, tes
     atouts, ce que l'offre demande et que ton CV ne montre pas).

   Une offre rédigée en anglais donne automatiquement une **lettre et un
   e-mail en anglais** (`Cover_Letter_Prénom_Nom_(Entreprise).pdf`, codes
   anglais : « Dear Hiring Manager », date à l'anglaise, numéro au format
   international) ; la langue peut aussi être choisie à la main.
4. Tu relis (aperçu intégré), tu retouches si besoin directement dans l'app
   (un paragraphe peut être reformulé par l'IA d'un clic), tu télécharges,
   tu envoies.
5. **Trois recherches séparées** : alternance, stage et job étudiant. Chacune
   a sa description de ce que tu cherches, son CV de départ, son style de
   lettre (plus courte et centrée sur tes disponibilités pour un job
   étudiant) et sa propre liste de candidatures. On passe de l'une à l'autre
   en haut à droite de chaque page.
6. **Facultatif** : tu notes ce que tu as envoyé, et l'app te rappelle quand
   relancer (et rédige la relance), suit tes réponses, prépare tes entretiens
   et produit un **rapport PDF** de ta recherche (candidatures, réponses,
   sites d'emploi les plus efficaces). Rien de tout ça n'est obligatoire.

![Aperçu de l'application](docs/apercu.png)

## Ce que ce projet met en pratique

- **Intégration d'une API IA** (Google Gemini, sortie JSON structurée par
  schéma) avec bascule automatique entre plusieurs modèles quand l'un
  atteint son quota, est surchargé ou est retiré, et fournisseur alternatif
  (Claude) interchangeable sans toucher au reste du code. Le texte de
  l'annonce est traité comme une donnée : les consignes qu'il pourrait
  contenir sont ignorées (protection contre l'injection de prompt).
- **Mise en page garantie sur une page** : le PDF réellement produit est
  analysé (nombre de pages, hauteur du contenu qui déborde) et le document
  est resserré juste ce qu'il faut — espacements, interligne, marges, puis
  seulement en dernier recours la taille de police — en visant le bon
  niveau dès le premier essai d'après la mesure du débordement.
- **Manipulation fine de documents Word** (python-docx, lxml, docxtpl) :
  édition ciblée d'un paragraphe en conservant la mise en forme de chaque
  segment, respect de l'ordre des balises imposé par le format OOXML,
  gabarit de lettre généré par code.
- **Pipeline de conversion PDF à plusieurs niveaux de repli** (Microsoft
  Word via COM → LibreOffice en ligne de commande → service cloud), avec
  détection des pannes plutôt que des blocages silencieux (délai borné,
  nettoyage de l'arbre de processus, diagnostic clair).
- **Import d'une offre depuis son lien**, sécurisé : lecture des données
  structurées `JobPosting` (schema.org) publiées par les sites d'emploi,
  repli sur le texte principal de la page, et protections contre les
  requêtes vers le réseau local (adresses privées refusées, redirections
  vérifiées une à une, taille et durée bornées).
- **Robustesse et données** : écritures JSON atomiques, récupération après
  corruption, dossiers de sortie isolés par génération, sauvegarde
  automatique quotidienne et restauration contrôlée (seuls les fichiers de
  l'app sont acceptés), historique avec détection des candidatures en double
  et suivi facultatif (statuts, relances, statistiques).
- **Interface soignée** : app multipage (navigation en haut), thème clair et
  sombre sur mesure, polices fournies avec l'app (Spectral et Instrument
  Sans, licence OFL, rien n'est chargé depuis Internet), aperçu des documents
  présentés comme des feuilles, liste des candidatures et fiche détaillée
  côte à côte ; rapport PDF mis en page avec reportlab.
- **Qualité logicielle** : 99 tests automatisés (pytest, dont des
  tests de l'interface Streamlit de bout en bout et un test d'intégration
  avec un vrai moteur de rendu), analyse statique (ruff), intégration
  continue GitHub Actions.
- **Déploiement pour un utilisateur non technique** : lanceur Windows qui
  crée l'environnement et installe/met à jour les dépendances tout seul,
  raccourci avec icône épinglable à la barre des tâches, fermeture propre
  depuis l'interface.

## Installation

Prérequis : **Python 3.10 ou plus récent** (sous Windows, cocher « Add
python.exe to PATH » pendant l'installation).

**Sous Windows, rien à taper** : double-clique sur `Lancer.bat`. Au premier
lancement, il crée l'environnement Python (`.venv`) et installe les
dépendances ; ensuite, il ne les réinstalle que si `requirements.txt` a
changé (après une mise à jour du projet, par exemple).

Installation manuelle (toutes plateformes) :

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows (PowerShell : .venv\Scripts\Activate.ps1)
source .venv/bin/activate       # Mac / Linux
pip install -r requirements.txt
```

## Configuration de la clé API (gratuit par défaut)

Par défaut, l'app utilise l'**API Gemini** (Google) pour rédiger la lettre et
adapter le CV — gratuit, sans carte bancaire, indépendant d'un éventuel
abonnement Gemini payant.

1. Crée une clé gratuite sur
   [aistudio.google.com/apikey](https://aistudio.google.com/apikey) (connexion
   avec un compte Google, aucun paiement demandé).
2. Copie `.env.example` en `.env` dans le dossier du projet.
3. Colle ta clé dans `.env` :
   ```
   FOURNISSEUR_IA=gemini
   GEMINI_API_KEY=...
   ```

Le fichier `.env` n'est jamais partagé ni commité (il est listé dans
`.gitignore`).

**Modèle et quotas :** l'app utilise `gemini-3.5-flash-lite` (quota gratuit
généreux) et bascule automatiquement sur `gemini-3.1-flash-lite`, puis
`gemini-3.8-flash` et `gemini-3.6-flash` si le quota du jour est atteint ou
si Google retire un modèle. Tes limites exactes sont visibles sur
[aistudio.google.com](https://aistudio.google.com) ; le détail des modèles
sur [ai.google.dev/gemini-api/docs/models](https://ai.google.dev/gemini-api/docs/models).
Pour forcer un autre modèle : `GEMINI_MODEL=...` dans `.env`.

**Alternative payante (Claude/Anthropic) :** passe `FOURNISSEUR_IA=anthropic`
dans `.env` et ajoute `ANTHROPIC_API_KEY=sk-ant-...` (clé à créer sur
[console.anthropic.com](https://console.anthropic.com), facturée à l'usage :
environ 3 centimes par candidature avec Claude Sonnet 5.5, le modèle par
défaut, et environ 0,2 centime avec `ANTHROPIC_MODEL=claude-haiku-5-5`).

## Lancer l'app

**Option simple (recommandée) : un raccourci à double-cliquer**

1. Double-clique une seule fois sur `Creer_raccourci.vbs` (script Windows
   natif, rien à installer). Il crée un raccourci **« Candidatures
   Alternance »** sur le Bureau, avec sa propre icône.
2. Ensuite, pour lancer l'app : double-clique sur ce raccourci.
3. Pour l'avoir dans la barre des tâches : clic droit sur le raccourci du
   Bureau → « Épingler à la barre des tâches ».

Une petite fenêtre noire reste ouverte pendant que l'app tourne : elle
affiche les éventuelles erreurs. Pour arrêter l'app, utilise le bouton
**Fermer l'app** en bas de chaque page (ou ferme la fenêtre noire).
L'app suit le thème clair ou sombre de ton ordinateur ; pour le changer :
menu **⋮** en haut à droite → *Settings*.

**Option manuelle (ligne de commande)**

```bash
streamlit run app.py
```

Dans les deux cas, un onglet s'ouvre dans ton navigateur (par défaut
http://127.0.0.1:8501). L'app n'est accessible **que depuis ton PC** : même
sur un Wi-Fi partagé (école, café...), personne d'autre ne peut l'ouvrir
(réglage `server.address` dans `.streamlit/config.toml`).

## Utilisation

L'app a quatre pages, accessibles depuis la barre du haut. En haut à droite
de chaque page, choisis la recherche en cours : **Alternance**, **Stage** ou
**Job étudiant** (le choix est retenu pour la prochaine fois).

- **Nouvelle candidature** : à gauche l'offre, à droite les documents. Colle
  le lien de l'offre puis clique sur « Importer » (ou colle directement le
  texte de l'annonce), vérifie l'entreprise et le poste, choisis le CV de
  départ si tu en as plusieurs et la **langue de la lettre** (« Automatique »
  suit la langue de l'annonce), puis clique **une seule fois** sur « Générer
  la candidature ». Le bloc « Options » permet d'indiquer l'adresse de
  l'entreprise, l'e-mail du recruteur, le ton (sobre, dynamique, très
  formel), une lettre plus courte et des remarques libres pour l'IA. L'app
  affiche ensuite :
  - un **aperçu** de la lettre et du CV, avec leur statut (1 page, et le cas
    échéant le léger resserrement appliqué), les boutons de téléchargement
    PDF et Word, et un bouton pour ouvrir le dossier ;
  - **Analyse** : correspondance estimée, tes atouts pour ce poste, et ce
    que l'offre demande sans que ton CV le montre (à ajouter seulement si
    c'est vrai, sinon à préparer pour l'entretien) ;
  - **E-mail et texte** : l'e-mail d'accompagnement (objet et message avec
    bouton de copie, ou ouverture directe dans ta messagerie) et le **texte
    brut de la lettre**, pour les sites qui demandent de la coller dans un
    champ plutôt que de joindre le PDF ;
  - **Retouches** : objet, paragraphes, formule de politesse et chaque
    modification du CV (activable/désactivable) sont modifiables ;
    « Reformuler » fait réécrire un seul paragraphe par l'IA (avec une
    consigne facultative : « plus court », « insiste sur Power BI »...), puis
    « Mettre à jour les fichiers » régénère Word et PDF sans rappeler l'IA.

  Chaque génération a son propre sous-dossier horodaté dans
  `outputs/<Entreprise>/` : rien n'est jamais écrasé. Si tu as déjà généré
  une candidature pour la même entreprise, l'app te le signale. Pour passer
  à l'offre suivante, « Nouvelle offre » vide le formulaire ; et si tu
  colles directement une autre annonce, l'adresse, l'e-mail du recruteur ou
  le lien restés de l'offre précédente sont retirés automatiquement (l'app te
  le signale). Tu peux aller voir une autre page à tout moment : l'annonce et
  tes retouches en cours sont retrouvées telles quelles en revenant.
- **Mes candidatures** : un résumé en une phrase (candidatures préparées,
  envoyées, réponses, entretiens), la liste de tes candidatures à gauche
  (recherche, filtres par statut, tri) et, à droite, une vue d'ensemble ou la
  **fiche** de la candidature choisie : aperçu et retéléchargement des
  fichiers, dossier, lien de l'offre, e-mail, notes et préparation
  d'entretien. « Retirer » enlève une entrée de la liste sans toucher aux
  fichiers. **Suivi facultatif** (l'app fonctionne très bien sans) :
  - un statut par candidature (envoyée, relancée, entretien, acceptée,
    refusée...), modifiable dans la fiche ; la date de la première réponse
    est notée toute seule ;
  - **À relancer** : les candidatures envoyées restées sans réponse depuis
    10 jours (14 après une première relance), avec une relance rédigée par
    l'IA à partir de la lettre envoyée (en anglais si la lettre l'était) ;
  - **Préparer l'entretien** : une fiche (pitch de 30 secondes, questions
    probables avec pistes de réponse tirées de ton vrai CV, questions à
    poser), aussi enregistrée en Word imprimable dans le dossier ;
  - des notes, l'e-mail du recruteur, la date d'envoi et le lien de l'offre ;
  - une vue d'ensemble : répartition des statuts, activité par semaine,
    délai moyen de réponse, site d'emploi le plus efficace ;
  - **Rapport PDF** : le bilan de ta recherche sur la période de ton choix
    (depuis le début, 30 derniers jours, ce mois-ci, mois dernier ou dates
    précises) : chiffres clés, entonnoir envoi-réponse-entretien, activité,
    résultats par site d'emploi, relances à faire et détail de chaque
    candidature ;
  - un **export de la liste pour Excel** (fichier .csv, avec la recherche et
    les filtres en cours).
- **Mes CV** : importe ton CV au format **.docx**. Il devient la référence
  permanente : chaque candidature part d'une copie, il n'est jamais modifié.
  Tu peux ajouter des CV supplémentaires (choisis au moment de générer),
  voir le texte détecté (les blocs verrouillés ne sont jamais modifiés par
  l'IA : coordonnées, liens, titres de section) et **vérifier qu'un CV tient
  sur une page**.
- **Profil** : tes coordonnées (en-tête de chaque lettre, avec un aperçu,
  communes aux trois recherches), puis pour la recherche en cours : ce que
  tu cherches (utilisé par l'IA pour situer ta candidature) et le CV de
  départ proposé, la **sauvegarde** de tes données (téléchargement d'une
  archive, restauration) et le service d'IA utilisé.

## Une page garantie : comment ça marche

Un CV qui tient sur une page dans un logiciel peut déborder dans un autre :
chaque moteur de rendu (Word, LibreOffice...) calcule la hauteur des lignes
un peu différemment. L'app ne devine donc pas : elle **mesure le PDF
réellement produit**.

1. Le document est converti tel quel ; si le PDF fait une page, rien n'est
   touché.
2. Sinon, l'app mesure la hauteur du contenu passé en page 2 et choisit le
   plus petit niveau de resserrement qui devrait suffire, puis vérifie.
3. Les niveaux vont du moins visible au plus visible : espacements entre
   paragraphes et interligne (−2 % à −12 %), puis marges, et seulement
   ensuite la taille de police, par demi-point. **Le texte n'est jamais
   coupé.**
4. Pour le CV, le niveau qui a suffi est mémorisé : les candidatures
   suivantes partent directement du bon réglage (une seule conversion).

En amont, l'IA a pour consigne de ne jamais allonger un bloc du CV au-delà
de sa longueur d'origine (une adaptation nettement plus longue est
ignorée et signalée), et de viser 1 300 à 1 900 caractères pour le corps de
la lettre.

## Export PDF

L'app essaie automatiquement, dans l'ordre, la première méthode disponible :

1. **Microsoft Word** (version bureau installée) — 100 % local, le plus fidèle.
2. **LibreOffice** — 100 % local aussi, gratuit et illimité :
   [fr.libreoffice.org/telecharger](https://fr.libreoffice.org/telecharger/).
3. **iLovePDF** (service en ligne), si tu n'as ni l'un ni l'autre — configure
   `ILOVEPDF_PUBLIC_KEY`/`ILOVEPDF_SECRET_KEY` dans `.env` avec une clé
   gratuite créée sur [developer.ilovepdf.com](https://developer.ilovepdf.com)
   (2 500 crédits par mois, soit environ 250 conversions : une candidature en
   consomme 2, parfois 3 ou 4 si la mise en page doit être resserrée).
   **Ton CV et ta lettre sont alors envoyés aux serveurs d'iLovePDF le temps
   de la conversion.**

La méthode qui fonctionne est mémorisée pendant que l'app tourne. Si aucune
n'est disponible, les fichiers **.docx** restent téléchargeables.

## Où sont stockées les données

Tout reste **en local**, dans le dossier du projet :

- `data/cv_original.docx` — ton CV principal ; `data/cvs/` — tes CV
  supplémentaires
- `data/profil.json` — tes coordonnées
- `data/historique.json` — l'historique des candidatures (et leur suivi)
- `data/mise_en_page.json` — le réglage de mise en page mémorisé par CV
- `outputs/<Entreprise>/<poste_date>/` — les fichiers générés (PDF + Word,
  et la fiche de préparation d'entretien si tu la demandes)
- `sauvegardes/` — une sauvegarde automatique par jour de tout le dossier
  `data/` (les 15 plus récentes sont gardées)

Au moment de générer une candidature (ou une relance, une fiche
d'entretien, une reformulation), le contenu de ton CV et de l'annonce est
envoyé au fournisseur IA actif (Gemini par défaut, ou Anthropic), et à
iLovePDF seulement si c'est lui qui fait la conversion PDF. L'import par
lien lit simplement la page de l'offre sur le site concerné, comme le
ferait ton navigateur. Bon à savoir
pour Gemini : sur le palier gratuit, Google peut utiliser les contenus
envoyés pour améliorer ses produits, **sauf pour les utilisateurs situés
dans l'Espace économique européen (donc en France), au Royaume-Uni et en
Suisse**, à qui s'appliquent les mêmes règles que pour le palier payant
(voir les [conditions de l'API Gemini](https://ai.google.dev/gemini-api/terms)).

## Limites connues

- **Formats acceptés pour le CV : .docx uniquement** (pas de PDF : un PDF ne
  peut pas être réédité en préservant sa mise en page).
- **Import par lien** : certains sites (LinkedIn connecté, Indeed...)
  bloquent la lecture automatique ou affichent l'offre seulement après
  connexion ; l'app le dit clairement et il suffit alors de coller le texte
  de l'annonce.
- L'**analyse de l'offre** est une estimation de l'IA, à prendre comme un
  indicateur et non comme une note.
- Le texte contenu dans des **zones de texte, images ou SmartArt** n'est pas
  détecté — seuls les paragraphes et tableaux Word « standards » sont lus
  et modifiables (vérifie la liste dans la page « Mes CV »).
- La mise en forme d'un paragraphe modifié est conservée segment par segment
  (libellé, texte, date...) ; une mise en forme ponctuelle au milieu d'une
  phrase réécrite (un mot en gras isolé) peut toutefois être perdue.
- L'IA a pour consigne stricte de ne jamais inventer une expérience, un
  diplôme ou une compétence absente du CV — elle reformule et réorganise
  l'emphase. **Relis toujours** le résultat avant de l'envoyer : c'est toi
  qui restes responsable du contenu envoyé.

## Modifier la mise en page de la lettre

Ne modifie jamais `templates/lettre_template.docx` directement dans Word :
les balises qu'il contient (`{{ ... }}`) seraient probablement cassées.
Modifie plutôt `scripts/generer_gabarit_lettre.py` puis relance-le :

```bash
python scripts/generer_gabarit_lettre.py
```

## Tests

```bash
pip install -r requirements-dev.txt
ruff check .
pytest
```

Les tests utilisent un CV fictif généré à la volée et un dossier temporaire :
ils ne lisent ni ne modifient jamais tes vraies données. Le test
d'intégration de la mise en page utilise LibreOffice s'il est installé (il
est ignoré sinon) ; la CI GitHub Actions l'installe pour le lancer à chaque
push.

## Structure du projet

```
app.py                          cadre commun : thème, logo, navigation entre les pages, pied de page
vues/
  nouvelle_candidature.py       page « Nouvelle candidature » (offre, génération, retouches)
  candidatures.py               page « Mes candidatures » (liste, fiche, relances, rapport)
  cv.py                         page « Mes CV »
  profil.py                     page « Profil » (coordonnées, sauvegardes)
Lancer.bat                      double-clic pour démarrer (installe les dépendances si besoin)
Creer_raccourci.vbs             à exécuter une fois pour créer le raccourci Bureau
icon.ico                        icône utilisée par le raccourci
.streamlit/config.toml          réglages Streamlit (accès local uniquement, thèmes clair et sombre, polices)
static/                         logo, icône et polices de l'interface (Spectral, Instrument Sans : licence OFL)
src/
  candidature.py                assemble lettre + CV adapté + PDF d'une page
  mise_en_page.py               mesure des PDF et resserrement progressif (1 page garantie)
  cv_editor.py                  extraction/édition du CV Word en conservant la mise en forme
  lettre_generator.py           rendu du gabarit de lettre (docxtpl), typographie française ou anglaise
  pdf_export.py                 conversion .docx -> .pdf (Word, LibreOffice, iLovePDF)
  import_offre.py               import d'une offre depuis son lien (JSON-LD JobPosting, sécurisé)
  ai_client.py                  bascule vers le fournisseur IA actif (FOURNISSEUR_IA)
  ia_commun.py                  schéma, prompt et parsing partagés entre fournisseurs
  ia_gemini.py                  fournisseur Gemini (gratuit, par défaut)
  ia_anthropic.py               fournisseur Anthropic/Claude (payant, alternatif)
  assistant.py                  relances, fiches d'entretien, reformulation d'un paragraphe
  interface.py                  éléments d'interface partagés par les pages (style, aperçus, e-mails)
  rapport.py                    chiffres du suivi et rapport PDF (reportlab)
  recherches.py                 profils de recherche : alternance, stage, job étudiant
  suivi.py                      statuts, relances à faire, statistiques (suivi facultatif)
  stockage.py                   profil, CV, historique, sauvegardes (fichiers locaux)
  version.py                    numéro de version affiché dans l'app
scripts/
  generer_gabarit_lettre.py     génère templates/lettre_template.docx
templates/
  lettre_template.docx          gabarit Word de la lettre (généré, format A4)
tests/                          tests automatisés (pytest)
docs/apercu.png                 capture d'écran pour ce README
data/                           CV, profil, historique (non versionné)
outputs/                        fichiers générés (non versionné)
sauvegardes/                    sauvegardes automatiques de data/ (non versionné)
```

## Licence

[MIT](LICENSE)
