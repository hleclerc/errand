# Microserveurs et organisation des sources : tour 3

> Laisse **Réponse** vide pour accepter la recommandation. `?` demande plus de détails.
> Écris autre chose sous n'importe quelle question, puis Envoyer.

Décisions jusqu'ici : [decisions.md](decisions.md).

Supprimer l'errand distant est la décision qui a le plus de conséquences. Voici ce que fait aujourd'hui l'errand qu'on relance de l'autre côté, et pourquoi il y est (ADR 0002) :

| tâche | pourquoi là-bas |
|---|---|
| résoudre les cibles, **collecter les entrées** | il faut *importer* les fichiers, ce qui demande torch, jax… : seul l'environnement le peut |
| construire (Catch2, cargo), lister les cas d'un binaire | le binaire n'existe que là-bas |
| développer la grille, écrire le **plan** | ça dépend des entrées collectées |
| **exécuter les entrées**, en processus | le corps d'une entrée Python tourne dans l'interpréteur de l'environnement |
| prendre un **claim** dans la file de la machine | la file est celle de *cette* machine |
| écrire les enregistrements (`.errand/runs/…`), puis rapatriés | |

Sans errand distant, ces tâches se répartissent entre le côté local (le hub et la commande) et des *opérations* que les agents savent faire.

---

## Q1 : Qui fait quoi, sans errand distant ?

- **Local (hub + commande)** : choisir les environnements, développer la grille, construire le plan, tenir la file d'attente des runs, écrire les enregistrements à partir de ce qui revient, afficher, rapatrier les sorties.
- **Agent d'environnement** : des *opérations* errand, petites et sans orchestration :
  - `collect( fichiers, motifs )` → les entrées et leurs paramètres déclarés ;
  - `run( entrée, paramètres, out_dir )` → la sortie diffusée, puis le résultat (le dict `results`, le statut, la durée) ;
  - `build( runner )` et `list( runner )` pour pytest, Catch2, cargo, qui sont en fait des processus lancés et dont on lit la sortie.
- **Agent d'hôte** : les fichiers, le setup, la file d'attente de la machine (Q3), les soumissions.

Les deux agents sont du code errand, mais ils ne prennent aucune décision : ils exécutent et rapportent. C'est un peu la différence entre un *worker* et un *orchestrateur*.

➡️ **Recommandé :** cette répartition. Le module des opérations (`agents/ops.py`) devient la seule partie d'errand qui tourne dans l'interpréteur de l'environnement. Il ne dépend que de `targets/`, l'import des entrées, et de la stdlib. La CLI, le TUI, les couches et la file n'y vont jamais.

**Réponse :**

---

## Q2 : Et `--batch`, où rien ne reste connecté ?

Un job soumis doit s'exécuter seul, des heures, sans hub ni canal. Quelque chose doit donc, là-bas, enchaîner les `run` du plan et écrire les résultats.

➡️ **Recommandé :** le même agent d'environnement, mais **piloté par un fichier** plutôt que par un canal. C'est `python <boot> worker plan.json` : il lit le plan, appelle `ops.run` pour chaque cas, et écrit chaque résultat dans un fichier au fur et à mesure (`results/<cas>.json`, plus la sortie dans un log). Il n'orchestre rien : l'ordre, les paramètres et les répertoires viennent du plan, fait localement. `errand status` / `watch` lisent ces fichiers via l'agent d'hôte, et le hub écrit les enregistrements locaux en les rapatriant. La préparation (collect + build), qui sert à dimensionner l'allocation, se fait **avant** la soumission. En mode alive, elle se fait par l'agent de nœud. Sans allocation chaude, elle se fait par une petite allocation de préparation dont l'agent est relié au hub le temps de collecter.

**Réponse :**

---

## Q3 : La file d'attente des machines distantes

Aujourd'hui l'errand distant prend un claim (cpus, ram, gpus, exclusif) dans la file de lmo, pour ne pas se marcher dessus avec les autres runs, y compris ceux d'autres hubs ou d'autres personnes sur lmo.

➡️ **Recommandé :** c'est l'**agent d'hôte** qui tient les claims de sa machine, avec le module `queue/` actuel (des verrous de fichiers, partagés avec tout ce qui tourne sur cette machine). Le hub demande un claim avant chaque `run`, l'agent d'hôte le garde pendant l'exécution et le rend ensuite. Sous un scheduler, c'est le scheduler qui fait ce travail : pas de claim, comme aujourd'hui.

**Réponse :**

---

## Q4 : Que devient l'ADR 0002 (deux phases) ?

La règle de fond reste vraie : *les cibles se résolvent dans l'environnement*. Ce qui change, c'est qui pilote. Les deux phases deviennent deux suites d'appels d'opérations par le hub : préparation = `collect` + `build` ; run = `run`. Quand rien ne sépare les deux, par exemple sans scheduler entre eux, c'est le même agent, sans deuxième démarrage. Le « plan » devient un objet du hub. Il n'est écrit dans un fichier que pour `--batch` (Q2) et pour `status`.

➡️ **Recommandé :** une ADR 0005 « Agents : le côté local orchestre, les agents exécutent » qui *remplace* la partie « qui pilote » de l'ADR 0002 et garde sa règle de fond. Les conditions `when = "phase == …"` sur les couches restent valables.

**Réponse :**

---

## Q5 : Nom des couches qui modifient l'entourage

`Environment` est déjà pris : `errand.Env( [ couches… ] )` est *l'environnement* tout entier, la pile. Appeler `Environment` une de ses couches prêterait à confusion. Par ailleurs, `Mpi` n'est pas vraiment de la même famille : il ne modifie pas l'entourage, il *lance N copies*.

| couches | proposition | autres |
|---|---|---|
| Vars, Module, Nix, Guix | **`Overlay`** (se pose par-dessus l'entourage) | `Surround`, `Context`, `Modifier` |
| Mpi | **`Launcher`** (lance la commande, en N exemplaires) | rester dans la famille précédente |

➡️ **Recommandé :** `Overlay` et `Launcher`.

**Réponse :**

---

## Q6 : Extinction de chaque couche

Chaque agent a son propre délai d'inactivité, comme pour le hub. Un agent d'environnement inactif depuis son `keep_alive` s'éteint, ce qui libère par exemple la mémoire du GPU ou une instance d'apptainer. Un agent d'hôte s'éteint quand il n'a plus d'agent d'environnement et qu'il est inactif. Une allocation chaude est rendue quand son agent de nœud s'éteint. Le hub s'éteint en dernier.

➡️ **Recommandé :** un `keep_alive =` sur chaque couche qui mène à un agent (`Gateway`, `Scheduler`, `Interpreter`/`Container`), avec un défaut hérité de l'`Env`, puis de `errand.configure`. `errand agents stop <nom>` arrête un agent précis et tout ce qui est en dessous.

**Réponse :**

---

## Q7 : Plan de migration

1. Réorganisation sans risque : `tui/`, `cli/verbs/`, `runners/`, `vm/`, sans changer de comportement.
2. Protocole, canal et hub, avec `Here` et l'agent d'hôte via `Ssh`. Les `host.shell( … )` (setup, probes) passent par l'agent d'hôte.
3. Agents d'environnement et opérations `collect` / `run`. L'errand distant disparaît, la file passe à l'agent d'hôte.
4. `--batch` avec le worker piloté par fichier.
5. La VM Windows comme `Gateway` (absorbe son keeper) ; pty et ConPTY.
6. Slurm alive multi-nœuds, et la construction dans l'allocation.
7. Mode « errand en processus » dans l'agent d'environnement (imports gardés chauds).

Pendant les étapes 2 à 4, l'ancien chemin (`ssh … python -m errand`) reste disponible, puis il est supprimé à la fin de l'étape 4. Chaque étape garde la suite au vert en 3.8 et en 3.13, avec des tests réels sur lmo.

➡️ **Recommandé :** cet ordre. On écrit l'ADR 0005 avant l'étape 2. L'étape 1 peut commencer dès que tu valides.

**Réponse :**

---
