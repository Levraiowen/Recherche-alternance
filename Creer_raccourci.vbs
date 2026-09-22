' Cree un raccourci "Candidatures Alternance" sur le Bureau, avec l'icone du
' projet, qui pointe vers Lancer.bat. A executer UNE SEULE FOIS en double-
' cliquant sur ce fichier (rien a installer, c'est un script Windows natif).
'
' Ensuite, sur le raccourci cree sur le Bureau : clic droit -> "Epingler a
' la barre des taches" si tu veux l'avoir en permanence en bas de l'ecran.
'
' Remarque technique : le raccourci ne pointe pas directement sur Lancer.bat
' mais sur cmd.exe (qui execute Lancer.bat en argument). Windows 10/11
' n'affiche "Epingler a la barre des taches" que pour des raccourcis dont la
' cible est un vrai .exe ; un raccourci pointant directement sur un .bat
' n'a pas cette option dans le menu clic droit. Passer par cmd.exe est le
' contournement standard, sans rien changer au resultat pour toi.

Set oFSO = CreateObject("Scripting.FileSystemObject")
Set oWS = CreateObject("WScript.Shell")

dossierProjet = oFSO.GetParentFolderName(WScript.ScriptFullName)
cibleBat = dossierProjet & "\Lancer.bat"
cibleIcone = dossierProjet & "\icon.ico"
cmdExe = oWS.ExpandEnvironmentStrings("%WINDIR%") & "\System32\cmd.exe"

If Not oFSO.FileExists(cibleBat) Then
    MsgBox "Introuvable : " & cibleBat & vbCrLf & _
           "Verifie que Creer_raccourci.vbs est bien reste dans le meme dossier que Lancer.bat.", _
           vbCritical, "Creation du raccourci impossible"
    WScript.Quit 1
End If

sLinkFile = oWS.SpecialFolders("Desktop") & "\Candidatures Alternance.lnk"
Set oLink = oWS.CreateShortcut(sLinkFile)
oLink.TargetPath = cmdExe
oLink.Arguments = "/c """ & cibleBat & """"
oLink.WorkingDirectory = dossierProjet
oLink.Description = "Lance l'app de generation de candidatures (lettre + CV)"
oLink.WindowStyle = 1
If oFSO.FileExists(cibleIcone) Then
    oLink.IconLocation = cibleIcone
End If
oLink.Save

MsgBox "Raccourci cree/mis a jour sur le Bureau : Candidatures Alternance." & vbCrLf & vbCrLf & _
       "Double-clique dessus pour lancer l'app." & vbCrLf & _
       "Pour l'avoir dans la barre des taches : clic droit sur ce raccourci -> " & _
       Chr(34) & "Epingler a la barre des taches" & Chr(34) & ".", _
       vbInformation, "C'est fait"
