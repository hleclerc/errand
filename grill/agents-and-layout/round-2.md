# Microserveurs et organisation des sources : tour 2

> Laisse **Réponse** vide pour accepter la recommandation. `?` demande plus de détails.
> Écris autre chose sous n'importe quelle question, puis Envoyer.

Décisions du tour 1 : [decisions.md](decisions.md). L'idée « alive » change la forme d'ensemble. Je la reformule pour vérifier qu'on parle de la même chose :

```
 errand run …  ─┐                       ┌─ agent d'hôte (lmo) ─┬─ agent d'env (lmo-jax) ─ processus
 errand tui    ─┼─ serveur local ───────┤                      └─ agent d'env (lmo-torch)
 errand shell  ─┘  (le « hub »)         └─ agent d'hôte (VM Windows) ─ agent d'env (msvc)
                   s'éteint seul après x min sans activité, et éteint ses chaînes avec lui
```

Les commandes `errand` deviennent des clients légers du hub. Le hub démarre à la première commande qui en a besoin, et c'est lui qui possède les canaux.

---

## Q1 : Le hub, c'est bien ça ?

Un processus local par utilisateur (et non par projet), lancé à la demande, qui garde ouvertes les chaînes d'agents, et dont les commandes `errand` sont des clients. Il s'éteint après `keep_alive` minutes sans activité. Une activité, c'est une commande en cours, un TUI ouvert ou un processus distant encore vivant. Quand il s'éteint, il éteint les agents qu'il a lancés.

Le keeper actuel des VMs (`python -m errand.vm keep`, qui garde la VM Windows chaude entre deux commandes, et `errand vm stop`) fait déjà exactement ce travail pour un seul type de couche. Il disparaîtrait au profit du hub, et `errand vm stop` deviendrait `errand agents` (liste) / `errand agents stop [nom]`.

➡️ **Recommandé :** oui. Par utilisateur, avec `keep_alive = 15` min par défaut, réglable dans `errand.configure( keep_alive = … )` et par environnement (`Env( …, keep_alive = 60 )` pour une allocation Slurm qu'on veut garder). Le keeper des VMs est absorbé.

**Réponse :**

Oui, parfait. Il faudra aussi que les couches puissent s'éteindre individuellement avant que le hub ne s'éteignent.

---

## Q2 : Que se passe-t-il quand le hub n'est pas là ou pas souhaité ?

Par exemple : errand lancé depuis un job cron, depuis une CI, à l'intérieur d'une allocation, ou par l'errand distant lui-même (il ne doit pas monter un hub sur lmo).

➡️ **Recommandé :** le mode actuel (chaîne one-shot) reste le *repli* et passe derrière la même interface `Channel`. Un canal one-shot, c'est un agent qu'on démarre pour une seule commande puis qu'on ferme. On utilise le hub quand on est sur un terminal interactif et que ce n'est pas désactivé (`--no-agent`, ou `ERRAND_AGENT=0`). Sans terminal, pas de hub par défaut. Un seul chemin de code, deux durées de vie.

**Réponse :**

En fait, je n'aime pas trop le principe du errand distant. Ce côté "méta" pourrait peut être disparaître si on est capable de bien faire les agents.

On pourra toujours lancer un hub (le même, mais pas en daemon) pour le processus qui met --no-agent.

---

## Q3 : Programmes interactifs et Windows, côté processus

Pour qu'un programme interactif marche (`errand shell`, un `python` interactif, `htop`, un debugger, la couleur, ctrl-C, le redimensionnement), il lui faut un **pseudo-terminal** là où il tourne. Il y a deux options :

- **A. L'agent fournit le pty.** POSIX : `pty.openpty()` de la stdlib. Windows : **ConPTY** (`CreatePseudoConsole`, Windows 10 1809+), appelé en `ctypes`. Ce sont environ 200 lignes, sans dépendance, ce qui respecte la règle « errand n'a aucune dépendance ». Le flux du terminal (octets, taille, signaux) passe dans le protocole comme un canal de plus.
- **B. Contournement.** Un programme interactif ne passe pas par les agents : il prend le chemin one-shot avec `ssh -t` comme aujourd'hui. C'est simple, mais il refait les couches à chaque fois, et ça ne marche pas pour la VM Windows, où l'on passe déjà par ssh.

➡️ **Recommandé :** **A**. Un processus lancé par un agent a un pty quand le client en a un (stdin est un terminal), et des tuyaux sinon. ConPTY en ctypes sur Windows, avec repli sur des tuyaux simples (pas de couleur, pas de taille) si la fonction n'existe pas.

**Réponse :**

---

## Q4 : Programmes interactifs et Windows, côté canal

Entre deux agents, et entre le hub et le premier agent, le transport est un **flux d'octets** déjà donné par la couche : la stdio de `ssh`, la stdio de `micromamba run python agent`, celle de `apptainer exec`, de `srun`, celle de ssh vers la VM. Sur ce flux, on **multiplexe** des trames : `[ id de canal, type, longueur, données ]`. Le canal 0 sert au contrôle (lancer, signaler, attendre, fichiers), les autres aux flux (stdin/stdout/stderr ou pty de chaque processus). Le flux lui-même n'est jamais un tty, donc les octets passent tels quels.

Entre les commandes `errand` et le hub (local) : un socket unix sur macOS et Linux. Sous Windows, `AF_UNIX` existe depuis Windows 10 1803, mais Python ne l'expose qu'imparfaitement. Repli : TCP sur `127.0.0.1` avec un jeton aléatoire lu dans un fichier que seul l'utilisateur peut lire.

➡️ **Recommandé :** ce schéma : trames binaires sur un flux, socket unix (ou TCP + jeton sous Windows) vers le hub. Le protocole est le même à chaque saut, et un agent d'hôte relaie les trames de ses agents d'environnement sans les comprendre (il réécrit seulement les ids).

**Réponse :**

---

## Q5 : Quand un agent devient-il périmé ?

Un agent qui reste vivant peut ne plus correspondre à ce qu'on lui demande :

1. **errand a changé** (on l'édite) : l'agent tourne avec l'ancienne copie ;
2. **l'environnement a été reconstruit** (setup, `requirements.txt` modifié) : l'agent d'environnement tourne dans l'ancien ;
3. **la déclaration de l'env a changé** (une `Vars` en plus, un autre module) ;
4. (plus tard, en mode « errand en processus ») **les sources du projet ont changé**, avec des modules importés devenus faux.

➡️ **Recommandé :** chaque agent porte une **clé** : le hash du contenu des sources d'errand, l'empreinte de la pile de couches (celle de l'ADR 0004, qui sert déjà à décider d'un rebuild) et le stamp de ce qui a été construit. Le hub compare les clés avant chaque usage, et un agent dont la clé ne correspond plus est arrêté puis relancé, en le disant (`-v` dit pourquoi). Le cas 4 sera traité avec le mode « en processus ».

**Réponse :**

---

## Q6 : Slurm et plusieurs machines

En mode `--batch`, rien ne change : le job tourne seul, et l'agent d'hôte du nœud de login soumet, surveille et rapatrie.

En mode **alive**, avec une allocation gardée chaude : Slurm donne N nœuds. Je propose que l'agent d'hôte sur le login fasse `salloc` (ou `sbatch` d'un job « réservoir »), puis `srun --ntasks-per-node=1 python <boot> agent` : **un agent de nœud par nœud**, dont chacun parle par la stdio de srun, relayée par l'agent d'hôte. Les agents d'environnement se lancent ensuite sur chaque nœud. Un run MPI à N rangs devient « un processus par rang, lancé par l'agent de son nœud » au lieu d'un `mpiexec`, ou bien `mpiexec` lancé par l'agent du premier nœud.

```
hub ─ agent d'hôte (login) ─ salloc/srun ─┬─ agent de nœud 1 ─ agent d'env ─ rangs 0..k
                                          └─ agent de nœud 2 ─ agent d'env ─ rangs k+1..
```

➡️ **Recommandé :** oui pour la forme. Pour MPI, on garde `mpiexec`/`srun` lancé par l'agent du nœud 0, parce que c'est la seule manière dont MPI sait câbler les rangs entre eux. Les agents des autres nœuds servent à l'observation, aux fichiers locaux des nœuds et aux entrées non-MPI réparties. Cette partie vient **après** l'hôte unique : c'est une étape du plan, pas du premier jet.

**Réponse :**

---

## Q7 : Ce qui ne s'atteint que dans l'allocation

Ton cas : un répertoire (un `/scratch` local au nœud, un système de fichiers monté seulement sur les nœuds de calcul, un module disponible seulement là) où errand doit installer quelque chose : un venv, une image, son propre Python. Aujourd'hui, `setup` construit tout depuis l'hôte que `Ssh` atteint, c'est-à-dire le nœud de login.

➡️ **Recommandé :** chaque couche *construite* s'installe **là où elle va servir**. Une couche placée après un scheduler est construite par l'agent de nœud, dans l'allocation (celle de préparation en `--batch`, l'allocation chaude en mode alive). Une couche placée avant est construite depuis l'agent d'hôte, comme aujourd'hui. Le bootstrap de Python suit la même règle. Ça découle de la forme « agent par niveau » et ça généralise ce qu'on vient de faire avec la recherche en ligne de Python.

**Réponse :**

---

## Q8 : Les noms

**Couches.** Ce que j'appelais `Wrapper` regroupe les couches qui modifient l'*entourage* de la commande sans choisir l'interpréteur (Vars, Module, Nix, Guix, Mpi). Ce que j'appelais `Built` regroupe les couches qui possèdent un *artefact* : une chose construite, avec son enregistrement (ADR 0004).

| rôle | proposition | autres |
|---|---|---|
| modifie l'entourage | **`Setting`** | `Surround`, `Prefix` |
| choisit l'interpréteur | `Interpreter` | |
| conteneur | `Container` | |
| possède une chose construite | **`Artefact`** ( mixin ) | `Provisioned`, `Buildable` |
| scheduler | `Scheduler` | |
| mène ailleurs | `Place` | `Gateway` |

**Packages.** `work/` contenait les entrées, la découverte, les cibles et le plan, c'est-à-dire *ce qu'on demande*, et les résultats, c'est-à-dire *ce qui en sort*. `machine/` contenait la file d'attente et les claims.

| contenu | proposition |
|---|---|
| entries, discovery, targets, plan | **`targets/`** |
| results, history, sorties | **`records/`** |
| runners (pytest, catch2, cargo…) | `runners/` |
| file d'attente, claims, ressources de la machine | **`queue/`** |
| hub, agents, protocole, canaux | **`agents/`** |

➡️ **Recommandé :** les noms en gras.

**Réponse :**

Setting -> Environment ?
Je préfère Gateway à Place

---
