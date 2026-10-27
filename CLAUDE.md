# Downscaler PSX

Outil Windows (Python + Tkinter + Pillow) qui réduit des textures carrées aux résolutions PSX (512, 256, 128, 64) en interpolation **nearest neighbor**, pour garder l'aspect pixelisé.

## Fichiers

- `downscaler_gui.py` : l'application (interface et traitement).
- `context_menu.py` : ajoute ou retire l'entrée « Downscaler PSX » du menu clic droit de l'explorateur Windows.
- `requirements.txt` : dépendances (`Pillow>=10.0`).

## Lancer le programme

```bash
pip install -r requirements.txt
python downscaler_gui.py
python downscaler_gui.py image1.png dossier/
```

Les chemins passés en argument (fichiers ou dossiers) sont préremplis dans « Source(s) ».

## Comportement du traitement

- Formats acceptés : `.png .jpg .jpeg .bmp .tif .tiff .webp`. Les dossiers sont parcourus récursivement.
- Seules les images **carrées** sont traitées, les autres sont ignorées avec une erreur dans le log.
- Pour chaque résolution cochée : déjà à la bonne taille → skip ; plus petite que la cible → skip (jamais d'agrandissement).
- Sortie : sous-dossier `_downscaled/` créé à côté de la source, en miroir de l'arborescence, avec le suffixe `_<taille>` (ex. `brique_128.png`).
- Lors du parcours d'un dossier, les sous-dossiers `_downscaled/` sont ignorés pour ne pas retraiter les sorties. Un fichier choisi explicitement est toujours traité, même s'il s'appelle déjà `xxx_128.png`.
- Les JPEG sont enregistrés en qualité 95 ; la transparence (RGBA/P) est convertie en RGB.
- Le traitement tourne dans un thread séparé ; il communique avec l'interface via des `queue.Queue` lues par `_poll_queues` toutes les 80 ms.

## Instance unique

Le menu clic droit lance un processus par fichier sélectionné. Pour tout regrouper dans une seule fenêtre :

- le premier processus ouvre un serveur sur `127.0.0.1:47821` (`IPC_PORT`) et devient l'instance principale ;
- les suivants s'y connectent, vérifient la bannière `IPC_BANNER`, envoient leurs chemins (un par ligne, UTF-8) puis se ferment ;
- la fenêtre principale ajoute les chemins reçus (sans doublons) et passe au premier plan.

Si le port est occupé par un autre programme (bannière différente), le processus ouvre simplement sa propre fenêtre.

## Menu clic droit de l'explorateur

`context_menu.py` écrit dans `HKEY_CURRENT_USER\Software\Classes\SystemFileAssociations\<ext>\shell\DownscalerPSX` pour `.png`, `.jpg` et `.jpeg`. Pas besoin de droits administrateur. La commande enregistrée utilise le chemin absolu de `pythonw.exe` (pas de console) et de `downscaler_gui.py`.

Sous Windows 11, l'entrée se trouve dans **« Afficher plus d'options »** (ou Maj + clic droit).

Installer, ou réinstaller après avoir déplacé le dossier ou changé de version de Python (les chemins enregistrés deviennent sinon invalides) :

```bash
python context_menu.py
```

Retirer l'entrée du menu :

```bash
python context_menu.py --uninstall
```

## Conventions

- Interface, messages et commits en français.
- Pas de tests automatisés : vérifier à la main avec quelques images carrées.
