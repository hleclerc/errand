# Microserveurs et organisation des sources : tour 1

> Laisse **Réponse** vide pour accepter la recommandation. `?` demande plus de détails.
> Écris autre chose (réponse, objection, commentaire) sous n'importe quelle question, puis Envoyer.

Les faits mesurés aujourd'hui (Mac → lmo) :

| étape | coût |
|---|---|
| une connexion `ssh lmo true` | ~600 ms (1,1 s à froid), **ControlMaster désactivé** |
| `$SHELL -ic` en plus | ~+150 ms |
| `micromamba -n base run true` | ~+1,4 s |
| un rsync (même vide) | ~700 ms |

Un `errand run --env lmo-jax x.py` fait aujourd'hui : mkdir + rsync du projet, mkdir + rsync des sources d'errand (nouveau), le run (ssh -ic + micromamba run + import d'errand), puis un rsync par répertoire rapporté. Soit **6 à 8 connexions, 5 à 7 s de frais fixes** avant que le travail ne commence vraiment. En deux phases (préparation puis run), errand démarre deux fois de l'autre côté.

---

## Q1 : Par quoi commencer ?

La disposition des fichiers dépend du modèle d'exécution : avec des agents, il y a des modules « transport » et « agent » qui n'existent pas aujourd'hui, et la hiérarchie des couches change (une couche ne se contente plus de réécrire une commande, elle sait aussi *ouvrir un canal*).

- **A.** Décider d'abord le modèle d'exécution (une ADR 0005), puis réorganiser les sources *autour* de ce modèle, en une seule passe.
- **B.** Réorganiser d'abord à comportement constant, puis introduire les agents dans une structure propre.
- **C.** Mener les deux en parallèle.

➡️ **Recommandé :** A pour `layers.py` / `batch.py` / la partie « aller là-bas » de `cli.py`, qui seront refaits de toute façon. Mais B tout de suite pour ce qui n'en dépend pas : `tui.py` (1386 lignes), `vm.py` (1292), le reste de `cli.py` (verbes, aide, parsing), `runner.py`. On ne déplace pas deux fois le même code.

**Réponse :**

---

## Q2 : Quel problème les agents doivent-ils résoudre ?

Il y a deux gains possibles, de natures différentes :

1. **la latence** : les connexions et les démarrages répétés (ssh, `$SHELL -ic`, micromamba run, apptainer exec, import d'errand) ;
2. **l'état** : un processus qui reste vivant là-bas garde ce qu'il sait, par exemple les entrées collectées, le plan, un binaire déjà construit, des imports lourds comme jax ou torch, un GPU déjà initialisé. Il peut aussi pousser des événements (sortie en direct, progression) au lieu d'être interrogé.

Le premier gain s'obtient en grande partie sans agent : un `ControlMaster auto` + `ControlPersist` qu'errand ajouterait lui-même à ses options ssh fait passer chaque connexion de ~600 ms à ~30 ms, sans rien changer à l'architecture. Le second gain exige un agent.

➡️ **Recommandé :** activer le multiplexage ssh tout de suite. C'est un petit changement isolé dans `Ssh` qui divise les frais fixes par ~3. Il ne justifie pas les agents à lui seul, mais il recentre leur intérêt sur l'**état** et l'**interactivité** : le TUI, `watch`, les séries de runs courts, l'itération rapide « je modifie, je relance » sur lmo. C'est sur ces usages qu'on mesurera si l'agent vaut sa complexité.

**Réponse :**

On veut 1 et 2. Ssh n'est qu'un exemple parmi d'autre de layer qui prendre du temps au démarrage. Je préfère qu'on se concentre directement sur les agents.

---

## Q3 : Comment parle-t-on à un agent ?

- **A. Canal stdio.** Le errand local lance `ssh lmo $SHELL -ic 'micromamba -n x run python <boot> agent'` une fois, puis échange des messages (JSON par ligne) sur stdin/stdout. Pas de port, pas de socket, pas d'authentification à inventer : le tuyau ssh *est* l'authentification. L'agent meurt quand le errand local se termine ou ferme le tuyau.
- **B. Démon persistant.** L'agent écoute sur un socket unix (`~/.cache/errand/agents/<clé>.sock`). Il survit au errand local, et on s'y reconnecte (`ssh lmo python <boot> connect <clé>`, ou un `-L` de ssh). Cela exige de gérer la durée de vie, les versions (un démon lancé avec une vieille copie d'errand) et le nettoyage.
- **C.** Des ports TCP : non, à cause des pare-feu des clusters et des comptes partagés.

➡️ **Recommandé :** **A**, avec une durée de vie égale à celle du processus local : une commande `errand run` (qui réutilise l'agent pour la préparation, le run et les fetchs), une session TUI, un `watch`. La version B s'ajoute plus tard si on veut que l'agent survive entre deux commandes. Le protocole sera le même, seul l'établissement du canal change.

**Réponse :**

Je ne sais pas la solution, mais il faut qu'on puisse faire fonctionner les programmes interactifs, et que ça fonctionne aussi sous Windows.

---

## Q4 : Où vit l'agent dans la chaîne ?

« En bout de chaîne » veut dire, pour `Ssh → Module → Micromamba → Apptainer`, dans le conteneur, avec l'interpréteur de l'environnement. On y gagne le plus (micromamba et apptainer ne démarrent qu'une fois, les imports restent chauds), et c'est là que tournent les entrées Python.

Mais certaines opérations n'ont rien à faire dans le conteneur : rsync et les fichiers du projet, `setup` qui *construit* le conteneur (et qui doit donc tourner avant qu'il existe), et la soumission à un scheduler.

- **A.** Deux niveaux. Un **agent d'hôte**, juste après `Ssh`, avec le Python trouvé ou créé par `bootstrap` : fichiers, setup, soumissions, état des jobs. Puis un **agent d'environnement** au bout de la chaîne, démarré *par* l'agent d'hôte (sans nouvelle connexion ssh) : collecte, préparation, runs.
- **B.** Un seul agent, en bout de chaîne. Setup et rsync restent comme aujourd'hui.
- **C.** Un seul agent, d'hôte. Chaque run refait `micromamba run …` depuis lui, ce qui économise ssh mais ni micromamba ni l'état.

➡️ **Recommandé :** **A**. L'agent d'hôte remplace naturellement `Over.shell` : chaque `host.shell( line )` du code actuel (setup, probes, vm) devient un appel sur un canal déjà ouvert, ce qui unifie déjà beaucoup. Un agent d'environnement est un enfant de l'agent d'hôte, un par pile de couches, et on peut en avoir plusieurs en même temps (`--env a,b` sur la même machine).

**Réponse :**

---

## Q5 : Et les schedulers (Slurm, OAR…) ?

Un agent au bout d'une chaîne qui passe par Slurm vit *dans une allocation* : il occupe des nœuds tant qu'il vit, il est soumis à la limite de temps, et il dépend de la file d'attente pour démarrer.

- **A.** **La chaîne d'agents s'arrête au scheduler.** L'agent d'hôte (sur le nœud de login) soumet, surveille et rapatrie. Le job lui-même tourne en one-shot comme aujourd'hui, `python <boot> run --from-plan …`, avec sa sortie dans un fichier que l'agent d'hôte lit en continu (ce qui remplace le polling `tail` par ssh). `--batch` ne change pas : rien ne doit rester connecté.
- **B.** Un agent d'environnement dans l'allocation, si on le demande explicitement : un `salloc` interactif, ou `errand tui --env cluster` qui réserve un nœud et y garde un agent pour itérer. C'est un *mode*, pas le défaut.
- **C.** Toujours un agent dans l'allocation.

➡️ **Recommandé :** **A** par défaut, et **B** comme extension ultérieure explicite (« réserve-moi un nœud et garde-le chaud »). Ce cas est vraiment utile sur un cluster pour itérer, mais il a son propre cycle de vie : temps d'allocation, libération, reprise.

**Réponse :**

Je ne sais pas encore, mais en tous cas, slurm peut nous donner plusieurs machines et il faut gérer le cas.
J'imagine aussi le cas un peu tordu où slurm nous donnerait accès à certains répertoires inaccessibles autrement et où errand voudrait installer des trucs.

---

## Q6 : Que sait faire un agent ?

- **A. Minimal et générique.** Lancer un processus (argv, env, cwd), diffuser sa sortie, lui envoyer un signal, attendre son code de retour, lire et écrire un fichier, et `stat`. La logique d'errand reste dans errand : l'agent d'environnement lance `errand run …` comme un processus enfant. On économise ssh et micromamba, mais pas l'import d'errand ni celui des modules de l'utilisateur.
- **B. Errand en processus.** L'agent d'environnement *est* un errand : il exécute `run`, `list` et `prepare` dans son propre processus, garde les modules importés, le plan et les entrées collectées. C'est le plus rapide, mais il faut alors gérer l'isolation entre runs (un module modifié doit être réimporté, l'état global d'un run ne doit pas fuir dans le suivant) et un plantage dans une entrée tue l'agent.
- **C.** A pour l'agent d'hôte, et pour l'agent d'environnement A d'abord, puis B quand on en mesure le besoin.

➡️ **Recommandé :** **C**. On fait A partout pour commencer : c'est sans risque, et cela suffit à supprimer ssh + micromamba + apptainer de chaque run. B se fait ensuite, en mesurant l'import de jax/torch, qui est probablement la vraie motivation, avec des règles d'isolation à décider à ce moment-là (un sous-processus *forké* depuis un agent qui a déjà importé, par exemple).

**Réponse :**

Ok pour C.
D'ailleurs, si on veut faire du "alive" (pouvoir relancer un calcul sans ré-importer et refaire les couches), il faudra une indirection supplémentaire: un petit serveur local qui s'éteint tout seul et qui éteint les couches si pas d'activité au bout de x minutes.

---

## Q7 : Hiérarchie des couches

Aujourd'hui, le comportement d'une couche est reconnu par `isinstance` et `hasattr( inner[ 0 ], "run" )`, et les familles sont des listes de types : `interpreters_of`, `chooses_python`, `batch_of`, `ssh_of`, `vm_of`. Je propose des classes de base explicites, chacune avec ses méthodes à fournir :

```
Layer                       when=, describe(), declares() -> ce dont dépend le setup
├── Wrapper                 wrap( cmd, ctx ) -> cmd         (Vars, Module, Nix, Guix, Mpi)
│   └── Interpreter         + choisit `python`              (Venv, Micromamba/Conda, Uv)
│       └── Container       + image à construire, montages  (Apptainer, Docker/Podman)
├── Built (mixin)           probe, build, stamp, record     (Venv, Micromamba, Uv, conteneurs)
├── Scheduler               submit / watch / cancel / size  (Slurm, Oar, Pbs, Sge, Lsf)
└── Place                   ouvre un canal vers ailleurs    (Ssh, Windows VM)
```

`Place` est le point d'accroche des agents : `open( ctx ) -> Channel`. `Here` (la machine locale), `Over` (via ssh) et un VM deviennent des implémentations de `Channel`.

➡️ **Recommandé :** oui, ces classes, avec des ABC (`abc.ABC`, `@abstractmethod`) plutôt que des Protocols, pour qu'une couche incomplète échoue *à la déclaration* et pas au premier run. Les dataclasses restent pour les paramètres. L'API publique (`errand.Venv( … )`, `errand.Ssh( … )`) ne bouge pas.

**Réponse :**

Ça m'a laire bien. J'ai juste du mal avec Wrapper et Built qui sont des mots trop génériques.

---

## Q8 : Découpage en fichiers

La cible est une soixantaine de fichiers de 50 à 300 lignes, chacun avec une docstring de tête qui dit sa responsabilité, groupés en sous-packages :

```
errand/
  __init__.py  __main__.py       surface publique, inchangée
  cli/        main.py (parsing, dispatch)  verbs/run.py list.py setup.py status.py …  help.py
  layers/     base.py  vars.py  venv.py  micromamba.py  uv.py  apptainer.py  docker.py
              module.py  nix.py  mpi.py  ssh.py  compose.py (fold, under, stack_for)
  schedulers/ base.py  slurm.py  oar.py …  watch.py
  places/     channel.py ( Here, Over )  bootstrap.py  push.py ( rsync )  vm/ ( windows … )
  agent/      protocol.py  host.py  env.py            (après l'ADR)
  work/       entries.py  discovery.py  targets.py  plan.py  results.py  runners/…
  machine/    queue.py  mpi.py  local.py
  tui/        app.py  panes.py  input.py  draw.py …
  util/       yamlish.py  expr.py  fuzzy.py  trace.py
```

On procède par étapes, chacune étant un déplacement à comportement constant, avec la suite complète au vert, en 3.8 et en 3.13, et un commit par étape.

➡️ **Recommandé :** ce schéma, en commençant par `tui/` et `cli/verbs/`, qui ne dépendent pas des agents. Les fichiers de l'ancien chemin (`errand/layers.py`…) disparaissent : ce sont des modules internes, et la frontière publique reste `errand/__init__.py`.

**Réponse :**

work et machine sont des noms trop générique, mais sinon ça a l'air bien

---
