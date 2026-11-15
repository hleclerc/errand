# errand sous Windows et ssh vers un Windows natif : tour 1

> Laisser **Réponse** vide pour accepter la recommandation. `?` pour plus de détails.
> Écrire autre chose (réponse, objection, commentaire) sous n'importe quelle question, puis Envoyer.

Ce que j'ai trouvé avant de poser les questions :

- La VM `Windows` a déjà tout ce qu'il faut pour travailler sur un Windows **par ssh** : `sshd` dans l'invité, des lignes `cmd.exe` (`Windows.line` : `cd /d`, vcvars, `set "K=v"`), le projet copié par le rsync de MSYS2 épinglé (`vm/transfer.py`, installé dans `C:\errand\msys`), les sources d'errand envoyées dans `C:/errand/src/<clé>`, un agent dans l'invité (ADR 0005, étape 5, ConPTY), et le rapatriement des sorties par `tar` + `scp`.
- Ce qui manque pour un Windows natif, c'est seulement la façon d'**y arriver** : aujourd'hui c'est `ssh -p <port> Administrator@127.0.0.1`, lancé depuis la machine qui fait tourner QEMU, après le démarrage de la VM.
- Côté errand lancé **sous** Windows, les obstacles sont les suivants :
  - `Here.shell` lance `sh -c` ;
  - `Over.shell` lance `$SHELL -ic` (ça marche : c'est l'hôte distant qui est POSIX) ;
  - le `push` vers un `Ssh` utilise `rsync` en local ;
  - les hubs utilisent une socket unix (l'ADR 0005 prévoit déjà TCP + jeton sous Windows ; `agents/endpoint.py` a une branche `WINDOWS`).
- L'ADR 0006 (les fichiers passent par les agents, plus de rsync) est **proposé, pas commencé**.

---

## Q1 : Comment déclarer un Windows natif joint par ssh

Trois formes possibles :

**(a) Une couche à part, typée :**
```python
WindowsHost( host = "winbox", user = None, options = [], python = None, msvc = False,
             provision = [], fetch = [], also = [], root = None )
```
C'est une passerelle, toujours en premier. Elle reprend les champs « invité » de `Windows` (python, msvc, provision, fetch, also, root), sans les champs de VM (iso, key, cpus, ram, disk, keep, data). Le code commun (lignes `cmd.exe`, copie, agent, fetch) est mis en commun avec la VM : une `Machine` « déjà allumée » dont l'accès est `ssh winbox` au lieu de `ssh -p <port> Administrator@127.0.0.1`.

**(b) `Windows( host = "winbox" )`** : même classe que la VM, mais `cpus`, `ram`, `iso`… n'ont alors plus de sens et l'autocomplétion les propose quand même.

**(c) `Ssh( host = "winbox" )` qui détecte Windows au premier contact** : magique, mais `Ssh` porte `python`, `errand_outputs_directory`… pensés pour POSIX, et la suite de la pile (Micromamba, Apptainer) n'a pas de sens derrière.

➡️ **Recommandé :** (a), `WindowsHost`. Tu aimes l'autocomplétion, et des champs qui ne veulent rien dire seraient un piège. On pourra la placer après un `Ssh` (un Windows joignable seulement depuis un rebond) plus tard, si le besoin vient.

**Réponse :**

Ok pour WindowsBox. Mais alors est-ce que le layer `Ssh` ne dit pas tout vu qu'il ne fonctionne pas pour windows ?

---

## Q2 : Ce qu'errand installe sur un Windows natif

Sur la VM, tout est installé dans l'image : python.org, rsync MSYS2, provision. Sur la machine de quelqu'un, il faut choisir ce qu'errand s'autorise. Proposition :

- **rsync MSYS2 et sources d'errand** : dans `C:\errand\` (ou `%LOCALAPPDATA%\errand`), comme `~/.cache/errand` sous POSIX. Rien dans le PATH, rien dans le registre. Les supprimer défait tout.
- **Python** : `python = None` cherche `py -3`, puis `python`. `python = "3.13.16"` le fait installer par un `uv` téléchargé dans le même répertoire, comme `bootstrap` le fait déjà sous POSIX (« made for errand alone »). Jamais d'installeur python.org système.
- **`provision`** (des scripts PowerShell, par exemple le `windows-tools.ps1` de loom qui pose llvm-mingw dans `C:\tools`) : lancé par `errand setup <env>` et seulement par lui, avec un enregistrement sur la machine (ADR 0004 : empreinte + tampon dans `C:\errand\records`). `errand run` refuse tant que ce n'est pas fait ou que c'est périmé, en le disant, comme pour une image pas construite.
- **`msvc`** : `False` par défaut ici (on ne suppose pas les Build Tools). `True` vérifie vcvars et le dit s'il manque.

➡️ **Recommandé :** oui, tel quel. Le fait que `provision` passe uniquement par `errand setup`, explicitement, est ce qui rend acceptable de modifier la machine de quelqu'un.

**Réponse :**

---

## Q3 : Copie des fichiers : rsync MSYS2 maintenant, ou l'ADR 0006 d'abord

- **(a) rsync MSYS2 maintenant** : il marche déjà vers l'invité. Pour un Windows natif, il suffit de l'installer dans `C:\errand\msys` au premier contact : téléchargé **ici** et poussé par `scp`, la machine Windows n'ayant peut-être pas d'accès réseau. Pour errand lancé **sous** Windows, le même rsync MSYS2 sert aussi en local. L'ADR 0006 le remplacera plus tard partout d'un coup (c'est déjà son étape 5).
- **(b) L'ADR 0006 d'abord** (manifestes, synchro par l'agent, plus de rsync nulle part) : plus propre, mais c'est un gros chantier transverse (pushes vers lmo, jz…) qui retarde ce qui est demandé ici et touche tout ce qui marche aujourd'hui.

➡️ **Recommandé :** (a). Le code est déjà là et testé dans l'invité, et l'ADR 0006 reste le chemin pour l'enlever.

**Réponse :**

---

## Q4 : errand lancé sous Windows : jusqu'où

Ce qui doit marcher pour loom, c'est `Here()` sur un Windows (build natif local) et un `Ssh` vers lmo depuis un Windows. Proposition de périmètre :

- **Supporté** :
  - lancer en local, sans environnement ou avec les couches `Vars`, `Venv`, `Uv` ;
  - `Ssh` vers une machine POSIX, et tout ce qui suit l'`Ssh` (y compris la VM `Windows` sur lmo) ;
  - `WindowsHost` ;
  - les hubs et agents, par TCP + jeton (déjà prévu par l'ADR 0005).
- **Refusé clairement** : une couche qui exige un hôte POSIX ici (`Micromamba`, `Apptainer`, `Docker`, `Slurm`…), avec le message « … needs a POSIX machine: put an `Ssh` before it ». Cela passe par le `requires()` qu'on vient d'ajouter, ou par `check_stack`.
- **`Here.shell`** sous Windows : les lignes locales d'errand sont du `sh`. Deux voies :
  - **(i)** un `sh` épinglé (busybox-w32, un seul `.exe` d'environ 600 Ko, téléchargé dans le cache d'errand comme rsync) qui exécute les lignes telles quelles ;
  - **(ii)** réécrire en Python chaque ligne locale qui sert sur ces chemins.

➡️ **Recommandé :** ce périmètre, avec (ii) pour `Here.shell`. Les lignes locales sur ces chemins sont peu nombreuses (`mkdir`, probes, `tar`), et elles s'écrivent en Python sans ajouter un binaire de plus. Sous Windows, `Here.shell` appelé avec du `sh` lève une erreur qui nomme la ligne : on trouve celles qui restent en les testant. Si ça déborde, on passe à (i).

**Réponse :**

---

## Q5 : Côté loom

- **`windows_x86_64 = Here()` sous Windows** : l'env loom = `[ Vars( PATH llvm-mingw, LOOM_* ) ]`. Le `requires` vérifie clang et dit de lancer `windows-tools.ps1` une fois s'il manque. On n'installe pas silencieusement sur la machine de l'utilisateur, puisqu'il n'y a pas de `errand setup` pour un `Here()`.
- **`windows_x86_64 = [ WindowsHost( host = "winbox" ) ]`** : loom le complète comme la VM. Il fournit `python = WINDOWS_PYTHON` (via uv dans le cache d'errand, voir Q2), et `provision = [ ligne pip, windows-tools.ps1, setup du projet ]`, lancé par `errand setup`. Les `PATH` des outils sont ceux de `C:\tools`, et `LOOM_CACHE_DIR` passe dans le cache d'errand de cette machine (pas `E:`).
- Le template de `loom-builders.py` propose en commentaire `[ WindowsHost( host = "" ) ]` comme alternative à la VM.
- Les `Missing` actuels (« errand cannot yet… ») disparaissent.

➡️ **Recommandé :** oui.

**Réponse :**

---

## Q6 : Comment tester, sans machine Windows à part

Ce dont je dispose : la VM Windows sur lmo. Proposition :

- **Tests unitaires** (Mac, rapides), sur ce qui peut tourner ici :
  - les lignes `cmd.exe` ;
  - la composition de la pile ;
  - les refus ;
  - le code Python qui remplace les lignes `sh` locales, testé avec un faux `Here` Windows.
- **Test réel de `WindowsHost`** : la VM de lmo **sert de Windows natif**. `WindowsHost( host = "127.0.0.1", options = [ "-p", "<port>", "-J", "lmo" ] )` pendant qu'une commande la tient allumée. C'est un vrai sshd Windows, avec uniquement ce que `WindowsHost` installe (rsync dans `C:\errand`, python via uv).
- **Test réel d'errand sous Windows** : lancer `errand run` **dans** l'invité (qui a Python), vers un `Ssh` lmo et en local avec `Vars`.
- **Prérequis** : pouvoir démarrer la VM sur lmo pendant ces tests (8 cœurs / 16 Go, quelques dizaines de minutes au total), en vérifiant avant que rien d'autre ne tourne (ni dispatch, ni `make wheels`).

➡️ **Recommandé :** oui, avec ton accord pour démarrer la VM sur lmo quand c'est libre.

**Réponse :**

---
