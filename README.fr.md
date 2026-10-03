# Escape the Backrooms Trainer

[简体中文](README.md) | [English](README.en.md) | [日本語](README.ja.md) | [한국어](README.ko.md) | [Deutsch](README.de.md) | **Français** | [Español](README.es.md) | [Русский](README.ru.md) | [Português](README.pt-BR.md)

Un overlay d’informations avec des fonctions amusantes pour *Escape the Backrooms* (Steam 1943950, UE 4.27). Écrit en Python pur, bibliothèque standard uniquement. L’outil lit et écrit la mémoire du jeu depuis l’extérieur et installe un petit hook sur `UObject::ProcessEvent` pour appeler les UFunctions du jeu dans le thread du jeu.

> Réservé au mode solo ou à votre propre partie (avec des amis au courant), pour s’amuser et apprendre la rétro-ingénierie d’UE.
> Ce projet n’a aucun lien avec Fancy Games ni Steam. Utilisation à vos risques ; les offsets et signatures peuvent ne plus fonctionner après une mise à jour du jeu.
>
> Remarque : le panneau à l’écran et les messages sont pour l’instant uniquement en chinois simplifié.

## Fonctionnalités

**Overlay** (lecture seule, ne modifie pas le jeu)
- Affiche à l’écran les monstres, objets, sorties, zones de chute et coéquipiers avec leur distance ; les cibles hors écran ont une flèche au bord de l’écran
- Panneau en haut à gauche : niveau, coordonnées, endurance, distance du monstre le plus proche (rouge à moins de 15 m), liste des sorties et des objets
- Radar en haut à droite (orienté selon la caméra, portée 40 m, monstres lointains épinglés au bord) ; liste des coéquipiers : nom, vivant/mort, distance et santé mentale
- Se masque quand le jeu n’est pas au premier plan ; se ferme quand le jeu se ferme

**Raccourcis** (votre rôle est détecté automatiquement : solo / hôte / client)

| Touche | Hôte / solo | Client |
|---|---|---|
| F5 | Posséder le monstre le plus proche (ZQSD/WASD pour bouger, souris pour tourner, Espace pour sauter, Maj pour courir) ; appuyer à nouveau pour revenir dans votre corps | Passer à la vue du monstre le plus proche (observation seulement) |
| F6 | Geler / dégeler tous les monstres | Indisponible |
| F7 | Vol + traverser les murs (Espace pour monter, Ctrl pour descendre) | Indisponible |
| F2 | Bonus de vitesse + endurance infinie | Bonus de vitesse (via RPC serveur) |
| F3 | Vue à la troisième personne | Identique |
| F4 / Maj+F4 | Changer d’apparence : costumes du jeu (visibles par les autres) ou modèles des monstres/personnages du niveau (visibles par vous seul) | Identique |
| Inser | Se téléporter à la sortie la plus proche | Indisponible |
| Suppr | Vous ressusciter à l’endroit de votre mort | Envoie une demande de réapparition à l’hôte (généralement ignorée) |
| F11 | Invincibilité : ni les monstres, ni les chutes, ni la noyade ne peuvent vous tuer (vous seul, pas vos coéquipiers) | Indisponible |
| F1 | Vision nocturne : exposition plus forte, sans vignette, grain ni aberration chromatique | Identique |
| Alt+1 | Caméra libre : détacher la caméra du corps et la faire voler (ZQSD/WASD, Espace/Ctrl monter/descendre, Maj plus vite) | Identique |
| Alt+2 | Santé mentale bloquée au maximum | Identique |
| Alt+3 | Déclencher le bonus de vitesse + endurance du jeu | Identique |
| Alt+4 | Super saut | Identique |
| Alt+5 | Traverser les murs : demander au serveur de désactiver votre collision | Expérimental : demande à l’hôte de désactiver votre collision |
| Alt+6 | Ramasser à distance l’objet au sol le plus proche | Identique (dépend du contrôle de distance par l’hôte) |
| Alt+7 | Interagir à distance avec l’élément visé par le réticule | Identique (dépend du contrôle de distance par l’hôte) |
| Alt+8 | Écrire l’objet choisi avec Page↑/Page↓ dans un emplacement libre de l’inventaire | Identique |
| Page↑ / Page↓ + Origine | Choisir un objet et le faire apparaître dans vos mains | Identique |
| F8 / F9 / F10 | Masquer l’overlay / afficher les objets / afficher les éléments interactifs | Identique |
| Fin | Annuler toutes les modifications, retirer le hook et quitter | Identique |

## Utilisation

1. Mettez le jeu en mode **fenêtré** ou **fenêtré sans bordure** (le plein écran exclusif cache l’overlay) et entrez dans un niveau.
2. Au choix :
   - téléchargez `ETB-Trainer.exe` dans les Releases et double-cliquez dessus (pas besoin de Python), ou
   - installez Python 3.10+, téléchargez le code source et double-cliquez sur `启动覆盖层.bat` (« lancer l’overlay »), ou lancez `python etb_overlay.py`.
3. Appuyez sur **Fin** pour quitter : la possession, le gel, le vol, les apparences, etc. sont d’abord annulés, puis le hook est retiré.

L’exe en fichier unique est créé avec PyInstaller et peut être signalé à tort par un antivirus. Si cela vous gêne, lancez l’outil depuis le code source.

## Fichiers

| Fichier | Description |
|---|---|
| `etb_overlay.py` | Point d’entrée : fenêtre d’overlay, lecture mémoire, classification des acteurs, projection monde → écran |
| `etb_trainer.py` | Fonctions des raccourcis, exécutées dans un thread d’arrière-plan du processus de l’overlay |
| `etb_call.py` | Hook de ProcessEvent + appelant d’UFunctions qui construit les paramètres par réflexion (appels groupés pris en charge) |
| `etb_ue.lua` | Script Cheat Engine : trouve GNames / GObjects / GWorld par AOB, avec des fonctions d’aide pour les noms, la réflexion et le parcours des acteurs |
| `NOTES.md` | Notes de rétro-ingénierie (en chinois) : globales, chaînes de pointeurs, offsets, fonctionnement du hook |
| `FUNCTIONS.md` | Liste des fonctions appelables (descriptions en chinois ; sélection + signatures complètes de 1729 fonctions dans 212 classes du jeu) |

## Fonctionnement

- Au démarrage, les sections exécutables du module principal sont analysées par signatures AOB pour trouver `GNames` (FNamePool), `GUObjectArray` et `GWorld`. Tout le reste est lu d’après la structure d’UE 4.27 et la réflexion à l’exécution.
- Les 19 premiers octets de `ProcessEvent` sont remplacés par un `jmp` vers une code cave. Celle-ci vérifie que le thread courant est le thread du jeu, réserve le drapeau d’appel avec `lock cmpxchg`, exécute la file d’appels écrite depuis l’extérieur, puis exécute le prologue d’origine et revient. Tous les appels de fonctions du jeu ont donc lieu dans le thread principal du jeu.
- Détection du rôle : si `Actor::Role` du personnage local vaut Authority, `World::NetDriver` distingue le solo de l’hôte ; AutonomousProxy signifie client.

Détails dans [NOTES.md](NOTES.md) (en chinois).

## Compatibilité

Écrit et testé sur le build Steam 24997718. Si après une mise à jour l’outil affiche « AOB 没找到 » (AOB introuvable) ou « ProcessEvent 开头字节和预期不同 » (prologue de ProcessEvent inattendu), il faut relocaliser les adresses.

## Licence

[MIT](LICENSE)
