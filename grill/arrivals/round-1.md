# Arrivées (ADR 0009) : tour 1

> Laisse **Réponse** vide pour accepter la recommandation. `?` demande plus de détails.
> Écris n'importe quoi d'autre (réponse, objection, commentaire) sous n'importe quelle question, puis appuie sur Envoyer.

Contexte : le brouillon est dans `docs/adr/0009-arrivals.md`, avec le tableau de ce qui attend aujourd'hui. Une **arrivée**, c'est quelque chose de demandé qui n'a pas encore de propriétaire là où il va tourner : un job Slurm en file, une VM qui boote, un agent qui démarre.

## Q1 : périmètre

Deux options :

- **(a) Toutes les attentes** du tableau suivent le même modèle : job Slurm, allocation chaude, queue errand, VM, démarrage d'un agent, zygote. Un seul vocabulaire, une seule façon de les montrer dans `status`.
- **(b) Seulement celles qui peuvent laisser quelque chose derrière elles et consommer des ressources** : les jobs Slurm (attendus, gardés au chaud, surveillés) et la VM. Le démarrage d'un agent ou d'un zygote reste tel quel : ils expirent seuls en quelques secondes ou après leur `keep`.

Le coût de (a) : les attentes de quelques secondes (bridge 15 s, zygote 20 s) n'ont pas grand-chose à annuler, et les déclarer partout ajoute du code sans rien régler.

➡️ **Recommandé :** (a) pour le vocabulaire et l'affichage (tout ce qui attend apparaît dans `status`), mais la règle complète (annulation enregistrée, bail, départ à vide) seulement pour ce qui peut consommer des ressources de façon durable : Slurm et VM. Pour les autres, on garde leur échéance courte et c'est tout.

**Réponse :**

---

## Q2 : qui possède une arrivée pendant l'attente

Il y a deux choix possibles :

- **(a) L'agent du process qui attend**, sur la machine de ce process. Le process y dépose sa consigne d'annulation, comme `on_stop` aujourd'hui (`ERRAND_PROC_DIR`). Si le process est arrêté, ou si son agent meurt (l'agent suivant fait le ménage), l'annulation part. Pour un `srun`, c'est l'agent du nœud de login ; pour la VM, l'agent de lmo.
- **(b) Le client** (le Mac), par le registre de l'ADR 0008. Mais le client peut avoir le couvercle fermé : c'est justement ce qu'on veut éviter.

➡️ **Recommandé :** (a). Le propriétaire provisoire est l'agent sur la machine du process qui attend, et l'annulation passe par `on_stop`, qu'on renomme `cancel` dans la fiche du process (fichier `ERRAND_PROC_DIR/cancel`), avec en plus ce qui est attendu et depuis quand (Q4).

**Réponse :**

---

## Q3 : une arrivée que plus personne n'attend

Cas : le process qui attendait est parti et l'annulation a échoué ou est arrivée trop tard. Le job démarre quand même et son agent se lance. Aujourd'hui, l'agent d'une allocation chaude reste `max( 30 s, keep / 4 )` sans rien faire, puis part, et le job se termine.

Comment l'agent qui arrive sait-il que quelqu'un l'attend encore ?

- **(a) Un bail en fichier.** Le process qui attend touche un fichier `wanted` toutes les N secondes, là où l'arrivée le lira : même machine pour la VM, système de fichiers partagé entre login et nœuds pour Slurm (le cas presque partout, `$HOME`). À son démarrage, l'agent qui arrive part tout de suite si ce bail a plus de 2N secondes.
- **(b) Une question au demandeur.** L'agent qui arrive interroge le process qui attend (pid sur une autre machine) : il faut un chemin réseau du nœud vers le nœud de login, ce qui n'est pas garanti.
- **(c) Rien de plus.** On garde le délai d'inactivité actuel : au pire 30 s d'allocation perdue.

➡️ **Recommandé :** (a), avec N = 30 s. Sans bail lisible (pas de système de fichiers partagé), on retombe sur (c), le délai d'inactivité.

**Réponse :**

---

## Q4 : échéances

Faut-il une échéance par défaut pour chaque type d'attente ?

- Les **démarrages** (bridge, zygote, ping) en ont déjà une, de 15 à 30 s.
- Le **boot** de la VM a `BOOT_TIMEOUT`.
- Les **files d'attente** (Slurm, queue errand, place pour la VM) n'en ont aucune : une file de cluster peut durer des heures, et c'est normal.

➡️ **Recommandé :** pas d'échéance par défaut pour les files d'attente. Chaque arrivée enregistre quand même `since`, ce qu'elle attend et pour qui, ce qui la rend visible dans `status` (« job 1234 en file depuis 2 h, pour sdot »). Une option pour en fixer une (`Slurm( wait = "6h" )`) n'est ajoutée que si le besoin se présente.

**Réponse :**

---
