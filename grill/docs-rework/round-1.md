# Refonte de la doc errand : round 1

> Laisse **Réponse** vide pour accepter la recommandation. `?` demande plus de détail.
> Écris autre chose (réponse, objection, commentaire) sous n'importe quelle question, puis Envoyer.

Contexte : la doc actuelle (≈ 60 pages) suit déjà l'ADR 0003 (l'accroche est « tes environnements »), mais les tests restent partout : onglets pytest / Catch2 / cargo sur la page d'accueil, une section « A suite, test by test » dans Getting started, 2 tutoriels sur 4 (*Adopt a suite*, *errand's own entries*), et un bloc « Runners » dans le guide. Ce qu'apportent les ADR 0005, 0008 et 0009 (agents sur chaque nœud, propriétaire par machine, `errand status` partout, VM keeper, allocations Slurm partagées, arrivées) tient aujourd'hui dans une seule page, *Fast, and nothing lost*.

---

## Q1 : la phrase de positionnement

Aujourd'hui : *« errand runs your work in any environment — a conda or uv env, a container, another machine over ssh, a Slurm allocation, any stack of them — building and updating it from what it declares, and syncing your files there and back. »*

Proposition : garder l'idée des environnements et ajouter la propriété comme seconde jambe :

> **errand runs your commands wherever you can reach — your laptop, a server over ssh, a Slurm cluster, a Windows VM, a container, any stack of them. It gets each place ready from what you declare, and owns everything it starts there until it ends.**

Avec, juste en dessous, la ligne sur l'étymologie (*« An errand is a trip made on someone's behalf… »*).

➡️ **Recommandé :** cette phrase (ou ta reformulation) : lancer partout + préparer + posséder.

**Réponse :**

"posséder" peut faire peur. Mais c'est peut être parce que je suis de culture française. 
La formulation proposée ne donne pas spécialement envie. Il faudrait que les gens comprennent l'intérêt d'utiliser errand plutôt que tout faire à la main comme on fait d'habitude.

---

## Q2 : pour qui

Proposition : quelqu'un qui écrit du code de calcul (recherche, HPC, ML) et qui le fait tourner sur un portable, un ou deux serveurs du labo, un compte sur un cluster national (Jean Zay), parfois une machine Windows pour les wheels. Qui en a assez des scripts ssh + sbatch + apptainer + rsync, et des processus oubliés sur les machines. Pas : un ingénieur DevOps qui cherche un orchestrateur de prod (Kubernetes, Ansible), ni un utilisateur qui veut un nouveau lanceur de tests.

➡️ **Recommandé :** ce public-là, écrit en clair dans *What errand is* (« who it is for / what it is not »).

**Réponse :**

Oui c'est ça

---

## Q3 : ce que montre la page d'accueil

Options :

- **A.** La pile de couches + une commande (comme aujourd'hui), la gestion des ressources en simple carte.
- **B.** La gestion des ressources en premier : `errand status` qui liste tout ce qui tourne sur chaque machine, allocations, VM.
- **C.** Les deux, dans cet ordre : (1) déclarer un endroit et y lancer une commande ; (2) « everything it starts is owned » : agents, `errand status` sur toutes les machines, Ctrl-C qui arrête à travers toutes les couches, allocations partagées, VM qui s'arrêtent seules ; (3) ce qu'on a en plus (`--batch`, `-o`, file d'attente par machine, grilles).

Les 6 cartes « features » seraient refaites dans l'esprit de C, sans carte « tests ».

➡️ **Recommandé :** C.

**Réponse :**

---

## Q4 : la place des tests

Ce qui existe encore : `x::y` qui passe par un runner (pytest, Catch2, cargo, entrées d'errand), tags d'entrée (`-e '!slow'`), `default_run`, `errand-project.py` avec `errand.runners`, les entrées propres d'errand (`test`, `bench`, `track`, `Param`, en cours de refonte en protocole selon l'ADR 0003).

Options :

- **A.** Une section du guide « Test suites and entries » (runners, entrées, tags d'entrée), placée après les ressources. Absente de la page d'accueil et du quickstart, sauf une ligne « errand also runs pytest / Catch2 / cargo suites test by test → ».
- **B.** Garder un onglet sur la page d'accueil et une section dans le quickstart, comme aujourd'hui.
- **C.** Réduire à une seule page, dans une rubrique « More ».

➡️ **Recommandé :** A.

**Réponse :**

Oui, plutôt A. Je pense qu'il faut qu'on discute à part des "runners". La sélection des envs en fonction du retour est sans doute un peu compliqué et presque hors sujet.

---

## Q5 : les entrées propres d'errand (`test` / `bench` / `track`, `Param`)

Elles sont annoncées « en cours de refonte » depuis l'ADR 0003. Options : (a) les garder documentées dans la section tests, avec un encadré « being reworked » ; (b) n'en garder qu'une page courte et retirer le tutoriel 4 ; (c) les retirer de la doc tant que le protocole n'est pas fait.

➡️ **Recommandé :** (b) : une page *Writing entries* courte avec l'encadré, le tutoriel 4 retiré (ou fondu dans la page).

**Réponse :**

---

## Q6 : grandes parties du guide

Proposition de découpage (le sommaire détaillé page par page viendra après ce round) :

1. **Start** : What errand is · Installing · Quickstart
2. **Places** : environments, layers (Ssh, Slurm, Windows, WindowsBox, containers, envs…), keeping them current, tags
3. **Running** : `errand run`, files there and back (`--pull`, `-o`, `also`), `--batch` / attach, grids, MPI, `errand shell`
4. **Owning what runs** : agents (hub / direct), ownership and the ledger, `errand status`, Ctrl-C and stops, the per-machine queue (`-x`, `--cpus`, `--gpus`), Slurm allocations and leases, VMs and their keeper, arrivals, `errand agents`
5. **Test suites and entries** : runners, entries, entry tags
6. **Project** : configuration files, where errand writes
7. **Reference** : CLI, Python API, expressions

➡️ **Recommandé :** ce découpage, en particulier une partie 4 à part entière (aujourd'hui une seule page).

**Réponse :**

---

## Q7 : les tutoriels

Aujourd'hui : 1 Four environments · 2 Adopt an existing suite · 3 Numbers over two machines · 4 errand's own entries (liés à `examples/`).

Proposition : garder 1 et 3 (les reprendre au ton nouveau), déplacer 2 dans la partie tests comme page « Adopting a suite », fondre 4 dans *Writing entries* (Q5), et **ajouter** un tutoriel « A cluster, a Windows VM, and what is running » : une allocation Slurm gardée chaude, une VM Windows, `errand status`, laptop fermé, `errand attach`, Ctrl-C.

➡️ **Recommandé :** cela. Je n'écris le nouveau tutoriel qu'avec des commandes vérifiées dans le code (sans le lancer sur Jean Zay ni lmo).

**Réponse :**

---

## Q8 : le ton

La doc actuelle a une voix assez littéraire (« A timing taken while something else was running is not a timing », titres comme *Fast, and nothing lost*, *A heartbeat, not a promise*). Options : (a) garder cette voix ; (b) plus sobre : phrases courtes, titres descriptifs (*Agents*, *Status*, *Stopping work*), exemples d'abord, la voix gardée seulement dans *What errand is*.

➡️ **Recommandé :** (b).

**Réponse :**

Oui, plus sobre et plus percutant. Il faut qu'on comprenne l'intérêt d'utiliser errand. Les personnes à qui j'en ai parlé disent à chaque fois "je fais ça à la main, ça va très bien, je n'ai pas envie de perdre le contrôle" et c'est après du temps qu'ils comprennent et ne souhaitent pas revenir en arrière.

---

## Q9 : le README

Aujourd'hui ≈ 170 lignes qui doublent la page d'accueil (couches, runners, configuration). Options : (a) le garder long et aligné sur la nouvelle accroche ; (b) le raccourcir : phrase, install, un exemple `errand-envs.py` + 5 commandes dont `errand status`, une liste de ce qu'il gère, lien vers le site.

➡️ **Recommandé :** (b), ≈ 60 lignes.

**Réponse :**

---
