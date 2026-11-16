# errand tui, refonte : tour 2

> Laisse **Réponse** vide pour accepter la recommandation. `?` demande plus de détails.

Réglé au tour 1 :
- écran A, une liste par machine plus un panneau de détail ;
- tous les projets, avec `p` pour s'en tenir au projet courant ;
- les actions : arrêter, sortie dans `$PAGER`, shell, arrêter une VM ;
- l'ancienne TUI et `session.py` sont supprimés ;
- on garde curses ;
- les lettres servent de verbes, `/` filtre ;
- les `waiting` suffisent.

Ce tour traite de **trois points ouverts** (passer par les agents, les fichiers d'un run en cours, l'historique des sorties) et de tes deux remarques en passant.

Faits relevés dans le code :
- `run_case` (`cli/here.py`) crée la feuille du run, `errand-outputs/runs/<fichier>/<nom>/<quand>-<où>[-params]/`, **sur la machine qui exécute**. `output.txt` y est écrit au fil de l'eau, et `result.yaml` à la fin. Le tout est rapatrié par rsync vers le client.
- Une session (`agents.ops session`) peut enchaîner plusieurs cas, donc plusieurs feuilles. Pour l'instant, rien ne dit à son propriétaire laquelle est en cours.
- Le dossier `proc/<id>/` d'un processus est effacé dès que sa fin a été livrée. Il n'en reste donc rien pour l'historique. Ce qui reste, ce sont les feuilles.

---

## Q1 : passer par les agents, concrètement

Il faut un nouvel op dans `agent.py`, `table`, qui renvoie `table.scan()`. La TUI ouvre l'agent de chaque machine du ledger avec `agents.open(target)`, qui passe par le hub, et lui pose la question toutes les ~3 s, par un flux déjà ouvert, sans nouveau ssh à chaque fois. Les mêmes canaux servent à trois autres ops :
- `kill` : arrêter par id, ou par pgid pour un orphelin ou un unowned. La ligne `cancel` d'abord, puis INT/TERM/KILL ;
- `tail` : lire un fichier à partir d'un offset, que ce soit la sortie d'un processus ou un fichier de sa feuille ;
- `ls` : la liste d'un dossier de feuille.

**Conséquence :** ouvrir la TUI **démarre l'agent** des machines du ledger qui n'en ont plus, donc un ssh et un boot de quelques secondes la première fois. C'est cohérent avec l'ADR 0009 (il n'y a plus de mode sans agent). Une machine qui ne répond pas est affichée en erreur, avec sa dernière table grisée. Il n'y a pas de repli sur le ssh de `remote_table` (qui reste, pour `errand status`).

➡️ **Recommandé :** oui, comme ci-dessus.

**Réponse :**

---

## Q2 : les fichiers d'un run en cours

`run_case` écrit le chemin de sa feuille dans `$ERRAND_PROC_DIR/leaf` quand il commence un cas, comme `waiting` (ADR 0009), et `table` le rapporte. Le panneau de détail montre alors, sous la méta :
- les fichiers de la feuille (nom, taille, modifié il y a…), du plus récent au plus ancien ;
- la fin de `output.txt`, ou de la sortie du processus si la feuille n'en a pas.

`tab` passe dans la liste des fichiers. `enter` (ou `o`) sur un fichier ouvre `$PAGER`, avec le fichier rapatrié par l'op `tail` s'il est distant.

➡️ **Recommandé :** oui.

**Réponse :**

---

## Q3 : l'historique, des liens vers les feuilles

Chaque machine garde **un petit fichier par run**, `~/.cache/errand/seen/<id>.json`, qui contient `{ leaf, project, what, env, started }`. Il est écrit par `run_case` sur la machine qui exécute, ce qui couvre aussi les runs locaux. Rien d'autre n'est gardé : le statut, la durée, les paramètres et la sortie se lisent dans la feuille (`result.yaml`, `output.txt`) au moment où on les affiche. L'agent, en répondant à l'op `seen`, **efface les liens dont la feuille a disparu**. Il n'y a donc rien à purger à part : la place prise suit celle des dossiers de runs que tu gardes.

Dans la TUI, chaque machine a un nœud `history` replié par défaut, au même niveau que ses processus. Il liste les runs du plus récent au plus ancien (les 50 derniers, `→` pour en voir plus), un par ligne : `il y a 2 h  ok  sdot-ffi  python -m loom.release make_wheels  4 min 12`. Le filtre `/` s'y applique, et le détail est le même que pour un run en cours (fichiers de la feuille et sortie).

Les runs **lancés ailleurs mais exécutés sur cette machine** y figurent, puisque c'est la machine qui exécute qui écrit le lien. Leur copie rapatriée sur le client n'y est pas : elle est déjà dans `errand-outputs`.

➡️ **Recommandé :** oui, comme ci-dessus.

**Réponse :**

---

## Q4 : ta remarque sur les étapes envoyées par les processus

C'est le même mécanisme que `waiting` : un fichier `$ERRAND_PROC_DIR/step`, une ligne de texte avec une date, écrit par un petit `errand.step("itération 41, résidu 3e-07")` côté Python (et une fonction shell). La table le rapporte et la TUI l'affiche en direct sur la ligne du processus. C'est peu de code, mais c'est une **API publique pour le code des utilisateurs** : son nom, ce qu'elle accepte (texte seul ? une fraction pour une barre de progression ? des valeurs nommées ?), ce que `errand run` en fait.

➡️ **Recommandé :** pas dans ce chantier. On en fait une proposition de session à part (un petit ADR, puis l'implémentation), une fois la TUI en place pour l'afficher. La TUI prévoit juste une colonne `step` vide pour l'instant.

**Réponse :**

---

## Q5 : ta remarque sur les petits serveurs http dans les agents

Cela voudrait dire un port par agent, un tunnel ssh pour y accéder depuis le Mac, et la question de l'authentification (un port ouvert sur lmo est visible des autres utilisateurs).

➡️ **Recommandé :** hors de ce chantier, et proposé comme session à part. La TUI et les ops `table`/`tail`/`ls`/`seen` en seront la base : un serveur http n'aura qu'à appeler les mêmes ops.

**Réponse :**

Oui on peut faire ça dans une session à part. Par contre, je parle uniquement de produire du html pour les humains. L'idée de base est de produire la même chose que `errand tui` mais en html.

---
