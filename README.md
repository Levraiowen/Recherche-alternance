# Générateur de candidatures — alternance

App locale (Streamlit) pour préparer rapidement une candidature personnalisée
à partir d'une offre d'alternance :

1. Tu importes ton CV Word une fois (il reste enregistré en local).
2. Tu colles le texte d'une offre.
3. L'app génère, en **PDF prêt à envoyer** (le .docx est aussi gardé) :
   - une **lettre de motivation**, nommée
     `Lettre_Motivation_Owen_Charpentier_(Entreprise).pdf` ;
   - une **version adaptée de ton CV**, nommée
     `CV_Owen_Charpentier_(Entreprise).pdf`, avec quelques formulations
     ajustées pour coller à l'offre (même mise en page, même fichier
     d'origine — seul le texte de certains blocs change).
4. Tu relis, tu télécharges, tu envoies.

L'export PDF se fait automatiquement via Microsoft Word s'il est installé,
sinon via LibreOffice s'il est installé (voir « Export PDF » plus bas). Le
nom de fichier est strictement identique entre le .docx et le .pdf généré,
seule l'extension change.

## Ce que ce projet met en pratique

- **Intégration d'une API IA** (Google Gemini, sortie structurée via JSON
  Schema) avec bascule automatique entre plusieurs modèles quand l'un
  atteint son quota ou n'est plus disponible, sans jamais bloquer
  l'utilisateur.
- **Pipeline de conversion de documents à plusieurs niveaux de repli**
  (Microsoft Word via COM → LibreOffice en ligne de commande → service
  cloud), avec détection proactive des pannes plutôt que des blocages
  silencieux (timeout borné, nettoyage de processus, diagnostic clair).
- **Manipulation de documents Word par programmation** (python-docx /
  docxtpl) : extraction de texte structuré, édition ciblée en conservant la
  mise en forme, génération de gabarits.
- **Persistance de données robuste** : écritures JSON atomiques, récupération
  gracieuse après corruption, dossiers de sortie isolés par génération pour
  ne jamais écraser silencieusement un résultat précédent.
- **Interface Streamlit complète** : formulaires, état de session, aperçu
  avant envoi, téléchargements, historique consultable.
- **Déploiement soigné pour un utilisateur non technique** : raccourci
  Windows avec icône dédiée, épinglable à la barre des tâches, fermeture
  propre de l'application sans repasser par la ligne de commande.

## Installation

Prérequis : Python 3.10 ou plus récent.

```bash
python -m venv .venv
.venv\Scripts\activate          # sous Windows (PowerShell : .venv\Scripts\Activate.ps1)
pip install -r requirements.txt
```

## Configuration de la clé API (gratuit par défaut)

Par défaut, l'app utilise l'**API Gemini** (Google) pour rédiger la lettre et
adapter le CV — gratuit, sans carte bancaire, indépendant d'un éventuel
abonnement Gemini Advanced payant (c'est un palier gratuit à part, ouvert à
tout le monde).

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

**Limite du palier gratuit :** un quota de requêtes par jour (largement
suffisant pour quelques candidatures par jour ; les détails exacts et à jour
sont sur [ai.google.dev/gemini-api/docs/pricing](https://ai.google.dev/gemini-api/docs/pricing)).
Si tu dépasses le quota un jour donné, l'app affiche clairement l'erreur —
il suffit de réessayer plus tard.

**Alternative payante (Claude/Anthropic) :** si tu préfères, passe
`FOURNISSEUR_IA=anthropic` dans `.env` et ajoute `ANTHROPIC_API_KEY=sk-ant-...`
(clé à créer sur [console.anthropic.com](https://console.anthropic.com),
facturée à l'usage — quelques centimes par candidature, non couvert par un
abonnement claude.ai classique).

## Lancer l'app

**Option simple (recommandée) : un raccourci à double-cliquer**

1. Double-clique une seule fois sur `Creer_raccourci.vbs` (script Windows
   natif, rien à installer). Il crée un raccourci **« Candidatures
   Alternance »** sur le Bureau, avec sa propre icône.
2. Ensuite, pour lancer l'app : double-clique sur ce raccourci, comme
   n'importe quelle application.
3. Pour l'avoir dans la barre des tâches : clic droit sur le raccourci du
   Bureau → « Épingler à la barre des tâches ».

Une petite fenêtre noire (l'invite de commande) s'ouvre et reste affichée
pendant que l'app tourne — c'est normal, elle sert à afficher les erreurs
éventuelles et permet d'arrêter l'app (Ctrl+C ou fermer la fenêtre). Elle se
lance automatiquement, il n'y a plus besoin d'y taper quoi que ce soit.

**Option manuelle (ligne de commande)**

```bash
streamlit run app.py
```

Dans les deux cas, un onglet s'ouvre dans ton navigateur (par défaut
http://localhost:8501).

## Utilisation

- **👤 Mon profil** : tes coordonnées (nom, adresse, téléphone, email...) et
  ton contexte académique. Utilisé pour l'en-tête de chaque lettre et pour
  situer ta candidature auprès de l'IA. À remplir/mettre à jour une fois.
- **📎 Mon CV** : importe ton CV au format **.docx** (Word). Il devient la
  référence permanente : chaque candidature part toujours d'une copie de ce
  fichier, jamais modifié directement. Un aperçu du texte détecté est
  disponible pour vérifier que tout est bien lu.
- **✉️ Nouvelle candidature** : colle l'annonce, précise si besoin
  l'entreprise/le poste, puis clique **une seule fois** sur « Générer la
  candidature (PDF direct) ». L'app appelle l'IA, crée les fichiers Word et
  les convertit en PDF en une seule opération, et affiche tout de suite les
  boutons de téléchargement dans `outputs/<Entreprise>/`. Le contenu généré
  (lettre + modifications du CV) reste affiché juste en dessous pour que tu
  puisses le relire avant d'envoyer ta candidature — mais rien ne bloque
  plus le téléchargement en attendant cette relecture. Chaque génération crée
  son propre sous-dossier horodaté dans `outputs/<Entreprise>/` : rien n'est
  jamais écrasé, même en relançant une génération pour la même entreprise
  (ex. après avoir changé les « Remarques pour l'IA », ou pour un autre poste).
- **🕓 Historique** : retrouve les candidatures déjà générées avec l'app et
  retélécharge leurs fichiers. Le bouton 🗑️ retire une entrée de la liste
  sans toucher aux fichiers PDF/Word correspondants, qui restent dans
  `outputs/`.

## Où sont stockées les données

Tout reste **en local**, dans le dossier du projet :

- `data/cv_original.docx` — ton CV de référence
- `data/profil.json` — tes coordonnées
- `data/historique.json` — l'historique des candidatures générées
- `outputs/<Entreprise>/` — les fichiers générés (PDF + Word)

Rien n'est envoyé ailleurs que vers l'API du fournisseur IA actif (**Gemini**
par défaut, ou Anthropic si tu as choisi cette option — voir plus haut) au
moment de générer une candidature : le contenu du CV et de l'annonce collée
y sont transmis pour la génération, rien de plus. Exception : si tu utilises
iLovePDF pour l'export PDF faute de Word/LibreOffice (voir « Export PDF »
ci-dessous), le CV et la lettre lui sont aussi transmis le temps de la
conversion.

## Export PDF

Au moment de valider une candidature, l'app essaie automatiquement, dans
l'ordre, la première méthode disponible :

1. **Microsoft Word** (si installé) — 100% local, le plus fidèle.
2. **LibreOffice** (si installé) — 100% local aussi, gratuit sur
   [fr.libreoffice.org/telecharger](https://fr.libreoffice.org/telecharger/)
   (~5 min d'installation, aucun compte requis).
3. **iLovePDF** (service en ligne), si tu n'as ni l'un ni l'autre — configure
   `ILOVEPDF_PUBLIC_KEY`/`ILOVEPDF_SECRET_KEY` dans `.env` avec une clé
   gratuite créée sur [developer.ilovepdf.com](https://developer.ilovepdf.com)
   (250 conversions gratuites par mois, aucune carte bancaire).
   **Différence importante avec les deux méthodes précédentes : ton CV et ta
   lettre sont alors envoyés aux serveurs d'iLovePDF le temps de la
   conversion.** Si tu préfères garder ça 100% local, installe LibreOffice
   à la place (option 2) — c'est gratuit et ça ne prend que quelques
   minutes.

Si aucune des trois n'est disponible/configurée, l'app te le signale
clairement et garde de toute façon les fichiers **.docx** disponibles au
téléchargement — tu peux toujours les ouvrir dans Word/LibreOffice/Google
Docs et exporter en PDF manuellement (Fichier → Enregistrer sous / Exporter
au format PDF).

## Limites connues

- **Formats acceptés pour le CV : .docx uniquement** (pas de PDF). Un CV PDF
  ne peut pas être réédité en préservant sa mise en page.
- Le texte contenu dans des **zones de texte, images ou SmartArt** n'est pas
  détecté par l'outil utilisé (python-docx) — seuls les paragraphes et
  tableaux Word « standards » sont lus et modifiables. Si ton CV utilise ce
  genre de mise en page (fréquent avec des modèles Canva convertis en Word),
  vérifie dans l'onglet « Mon CV » que le texte important apparaît bien dans
  la liste détectée.
- Quand un bloc de CV est modifié, seule la mise en forme du tout premier
  mot du paragraphe est conservée pour l'ensemble du nouveau texte (perte
  possible d'une mise en forme mixte dans un même paragraphe, ex. un mot en
  gras au milieu d'une phrase).
- L'IA a pour consigne stricte de ne jamais inventer une expérience, un
  diplôme ou une compétence absente du CV fourni — elle ne fait que
  reformuler/réorganiser l'emphase. **Relis toujours** le résultat avant de
  l'envoyer : c'est toi qui restes responsable du contenu envoyé.

## Modifier la mise en page de la lettre

Ne modifie jamais `templates/lettre_template.docx` directement dans Word :
les balises qu'il contient (`{{ ... }}`) seraient probablement cassées.
Modifie plutôt `scripts/generer_gabarit_lettre.py` puis relance-le :

```bash
python scripts/generer_gabarit_lettre.py
```

## Structure du projet

```
app.py                          interface Streamlit (4 onglets)
Lancer.bat                      double-clic pour démarrer l'app (voir "Lancer l'app")
Creer_raccourci.vbs             à exécuter une fois pour créer le raccourci Bureau
icon.ico                        icône utilisée par le raccourci
src/
  stockage.py                   lecture/écriture profil, historique, CV
  cv_editor.py                  extraction/édition du CV Word en place
  ai_client.py                  bascule vers le fournisseur IA actif (FOURNISSEUR_IA)
  ia_commun.py                  schéma, prompt et parsing partagés entre fournisseurs
  ia_gemini.py                  fournisseur Gemini (gratuit, par défaut)
  ia_anthropic.py               fournisseur Anthropic/Claude (payant, alternatif)
  lettre_generator.py           rendu du gabarit de lettre (docxtpl)
  pdf_export.py                 conversion .docx -> .pdf (Word puis LibreOffice)
scripts/
  generer_gabarit_lettre.py     génère templates/lettre_template.docx
templates/
  lettre_template.docx          gabarit Word de la lettre (généré)
data/                           CV, profil, historique (non versionné)
outputs/                        fichiers Word générés (non versionné)
```
