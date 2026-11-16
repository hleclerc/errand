# Refonte de la doc errand : round 2

> Laisse **Réponse** vide pour accepter la recommandation. `?` demande plus de détail.
> Écris autre chose sous n'importe quelle question, puis Envoyer.

Retenu du round 1 : tout sauf la phrase ; le fil rouge de la doc devient l'objection « je fais ça à la main, ça va très bien, je ne veux pas perdre le contrôle ».

---

## Q1 : la phrase, version « pourquoi pas à la main »

Candidates, toutes en deux temps (une accroche, puis une phrase qui dit ce qu'il fait) :

- **A.** *Stop babysitting your runs.* — errand takes your command to the laptop, the lab server, the cluster or a Windows VM, sets the place up from what you declared, brings the results back, and leaves nothing running behind you.
- **B.** *Your command, anywhere, without the ssh–sbatch–rsync dance.* — Declare a place once (a conda env, a container, a server, a Slurm allocation, any stack of them); errand gets it ready, runs what you would have typed, and brings back what it produced.
- **C.** *Run it there as if it were here.* — Same command, same output in your terminal, Ctrl-C included, whether "there" is a container, a server over ssh, a Slurm allocation or a Windows VM. errand sets the place up, syncs the files both ways, and cleans up after itself.

Le mot *own* disparaît de l'accroche ; il reste dans la page de la partie ressources, où il est expliqué.

➡️ **Recommandé :** C comme titre (c'est l'effet qu'on ressent à l'usage), avec la deuxième phrase de C ; A garde sa place comme sous-titre d'une section (« what you stop doing »).

**Réponse :**

---

## Q2 : répondre à « je ne veux pas perdre le contrôle »

Proposition, sur l'accroche et dans *What errand is* :

1. **Avant / après** : le bloc de commandes qu'on tape à la main (ssh, `module load`, `sbatch` ou `salloc`, `apptainer exec`, `rsync` retour, puis plus tard « qu'est-ce qui tourne encore sur lmo ? ») face à `errand run --env cluster python train.py` et `errand status`.
2. **Une section « You stay in control »** : ce qui tourne est la commande que tu aurais tapée ; `-v` affiche chaque commande lancée (ssh, sbatch, apptainer…) ; `errand shell --env X` te met dedans ; un environnement qui existe déjà est adopté, jamais reconstruit ; tout est en fichiers lisibles (`errand-envs.py` en Python, `errand-outputs/`) ; rien à installer sur les machines distantes ; Ctrl-C arrête vraiment, à travers toutes les couches.
3. **« What you stop doing »** : relancer à la main après un laptop fermé, chercher les processus oubliés, re-soumettre dans la file pour chaque commande, refaire l'env sur chaque machine.

➡️ **Recommandé :** les trois : 1 sur l'accueil, 2 et 3 dans *What errand is* (2 en version courte aussi sur l'accueil).

**Réponse :**

---

## Q3 : les scénarios mis en avant

Pour l'accueil et le quickstart, je propose d'en choisir 3 qui parlent au public, parmi :

- a. une commande sur le cluster, dans un conteneur, les résultats rapatriés ;
- b. le laptop fermé pendant une longue exécution, `errand attach` le lendemain ;
- c. `errand status` : ce qui tourne sur chaque machine, y compris ce qu'on a oublié ;
- d. la commande suivante sur le cluster démarre en 1 s, sans repasser par la file (allocation gardée chaude) ;
- e. construire / tester sur Windows depuis un Mac (VM gérée par errand) ;
- f. le même benchmark sur deux machines, `--grid`, résultats côte à côte ;
- g. `-x` : une mesure de temps sans rien d'autre sur la machine.

➡️ **Recommandé :** a, d, c (et b comme quatrième si la place le permet). e en carte.

**Réponse :**

a, c, b. Pour d, ça serait presque de la filouterie. Par contre, on peut mettre en avant le keep alive avec le temps de démarrage gagné sans préciser.

---

## Q4 : le nom de la partie « ressources »

« Owning what runs » écarté (le mot fait peur). Candidats : **Nothing left behind** · **Keeping track** · **What is running** · **Machines and resources**. Pages dedans : agents, status, stopping work, sharing a machine (`-x`, `--cpus`, `--gpus`), Slurm allocations, VMs, waiting (arrivals).

➡️ **Recommandé :** *Nothing left behind* (dit le bénéfice) ; la page d'entrée s'appelle *What is running* (`errand status`).

**Réponse :**

---

## Q5 : ce que tu veux rediscuter sur les runners

Tu as écrit : « La sélection des envs en fonction du retour est sans doute un peu compliqué et presque hors sujet. » Je ne suis pas sûr de ce que tu vises. Deux lectures :

- **A.** La sélection *des runners* selon le contenu du fichier (« guessing, and writing the guess down », `errand init` qui écrit la supposition) : trop de détail, à réduire à une phrase.
- **B.** La sélection *des environnements* par tags (`-t cuda`, `--fp 32,64`, « an environment that does not say fp covers both », `has_tag` dans le code) : trop compliqué pour la partie Places, à déplacer dans une page avancée.

Et pour la discussion à part sur les runners : la mener après cette refonte (je laisse la partie tests au minimum, sans réécriture de fond), ou maintenant dans ce grill ?

➡️ **Recommandé :** je pense que tu vises A et peut-être B : je réduis les deux (A à une phrase, B dans une page *Tags* en fin de partie Places, hors du quickstart), et la discussion de fond sur les runners se fait après, dans une session à part.

**Réponse :**

Je visais les 2 :)

---
