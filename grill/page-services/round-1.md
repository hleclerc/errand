# Services d'une page, par machine : tour 1

> Laisse **Réponse** vide pour accepter la recommandation. `?` demande plus de détails.
> Écris autre chose (réponse, objection, commentaire) sous n'importe quelle question, puis Envoyer.

Contexte : aujourd'hui (ADR 0026, steps 1-4) le `services.json` d'un store porte une **recette complète** : la
commande (`{tool:blender} -b -P /Users/…/sdot-ffi/src/sdot/viz/services/blender.py …`), un `env`
(`PYTHONPATH` vers le checkout de l'auteur), des candidats locaux (`/Applications/Blender.app/…`), des URL et sha256.
`errand serve install DIR NAME` montre ce qu'elle déclarerait et demande un oui. Trois problèmes :

- la recette contient les **chemins de la machine qui a écrit le store** : faux sur lmo, sur n14, sur le Mac de
  quelqu'un d'autre ;
- un store malhonnête peut mettre n'importe quelle commande dans la recette : seul l'œil de la personne protège ;
- tout se passe sur **la machine qui sert la page** : pas de choix de machine, pas de diagnostic, et `errand status`
  ne liste que les services déjà lancés une fois (`spec.json`), d'où le « not installed » vu hier.

Ce tour pose ce qui ne dépend de rien d'autre.

---

## Q1 : Le verbe

Tu as écrit `errand server install`. Le verbe existant est `errand serve` (`serve NAME`, `serve list`,
`serve stop`, `serve install DIR NAME`, `serve forward`). On garde `errand serve install` / `errand serve fetch`,
ou un nouveau verbe `errand server …` pour tout ce qui est « déclarer, installer » (et `serve` resterait « lancer »)?

➡️ **Recommandé :** garder `errand serve` (`errand serve install`, `errand serve fetch`) : un seul verbe pour les
services, déjà documenté ; `server` et `serve` côte à côte se confondraient.

**Réponse :**

---

## Q2 : Qui sait *comment lancer* un service : le store, ou le paquet installé sur la machine ?

C'est la question centrale (« un store ne doit pas pouvoir faire tourner n'importe quoi »).

- **(a) le store** (aujourd'hui) : commande + outils + env dans `services.json`. Les chemins sont ceux de l'auteur ;
  un store malhonnête écrit ce qu'il veut, la personne doit lire.
- **(b) le paquet du producteur, installé sur la machine.** sdot embarque, en *données*, la description de ses
  services : un fichier `sdot/viz/services/errand-services.json` dans le paquet (lu sans importer sdot), du genre

  ```json
  { "blender": { "version": "3fa29c1e", "protocol": 1, "text": "Pictures of the current view by Cycles.",
                 "run": [ "{tool:blender}", "-b", "--factory-startup", "-P", "{file:blender.py}", "--", "--port", "{port}" ],
                 "gpus": 1, "idle": "10m",
                 "tools": { "blender": { "min": "5.0", "fetch": { "linux-x86_64": "https://…tar.xz#sha256=8409…", … },
                                         "look": [ "/Applications/Blender.app/Contents/MacOS/Blender", "blender" ] } } },
    "sdot.ao": { "version": "77c2e910", "protocol": 1, "run": [ "{python}", "-m", "sdot.viz.services.ao", "--port", "{port}" ] } }
  ```

  `{file:…}` = un fichier *de ce paquet, là où il est installé sur cette machine* ; `{python}` = le Python de l'env
  qui a ce paquet. **Le store ne porte que des noms** : `"blender#3fa29c1e"`, son protocole, son texte, et le
  paquet qui le fournit (`"from": "sdot"`, version d'écriture `2026.11.3`) comme indice pour le diagnostic.
  Une machine ne peut lancer que ce que des paquets **qu'elle a déjà** décrivent ; un store malhonnête ne peut que
  nommer un service, jamais l'inventer.
- **(c) le store porte un gabarit restreint** (seulement des `{placeholders}` résolus sur la machine) : il reste des
  mots littéraux dans le gabarit (`-c 'import os…'`), donc il faut une grammaire et une liste blanche ; fragile.

➡️ **Recommandé :** (b). Le store = des noms (`name#version`) et des liens (le paquet, sa version) ; la façon de lancer
vient du paquet installé sur la machine choisie, composée avec les chemins de cette machine. Le `services.json` du
store perd `install.command`, `tools`, `env`.

**Réponse :**

Oui pour b. Je me demande s'il ne faudrait pas copier le fichier dans le .sviz pour le rendre indépendant de l'install.

---

## Q3 : `name#version` : quelle version, et comment on la vérifie

Ta proposition : version fixée par le producteur, hash du code du service (ex. `viz/services/blender.py`) et de son
protocole, la même sur toutes les machines ; la ligne d'installation lie ce nom aux chemins de la machine.

Trois sous-points :

1. **Ce qui est haché** : le producteur choisit (sdot : le fichier du service + le numéro de protocole ; `region.py`
   importe sdot, donc sdot peut y ajouter sa version). Huit caractères hexa.
2. **Coexistence** : une machine peut déclarer `blender#3fa29c1e` *et* `blender#91c0d2aa` en même temps (deux stores
   écrits par deux sdot) ; le relais ne prend que la version exacte. Pas de « compatible » implicite.
3. **Vérification** : au démarrage, le gardien demande au service `GET /errand/identity` → `{"name": "blender",
   "version": "3fa29c1e"}` (le service le calcule lui-même, comme le producteur). Différent de ce qui a été déclaré
   → le service est arrêté, état `wrong version` dans la page et dans `errand status`. Sans ça, le `#version` n'est
   qu'une étiquette tapée par quelqu'un.

➡️ **Recommandé :** les trois tels quels. Le hash change à chaque modification du fichier du service : un store écrit
par un sdot plus vieux demandera une nouvelle installation (rapide : même outil, autre `{file:}`), c'est le prix de
l'exactitude.

**Réponse :**

---

## Q4 : Quelles machines la page propose, par service

Le service lit le store (`X-Errand-Root`) : il doit tourner là où une copie du store existe.

- **ici** (la machine qui sert la page : le Mac, sa copie ramenée) ;
- **la machine du run** (lmo : le store original, au chemin où le run l'a écrit), atteinte par `forward` (ADR 0018
  step 6, fait) ;
- **les machines qui partagent un système de fichiers avec l'une des deux** (n14 et n22 voient le même `$HOME` NFS
  que…, si errand le sait déjà par ses lieux / ses vues de caches ADR 0022) ;
- plus tard : n'importe quelle machine, en y portant le store (non).

Choix par défaut : la première où le service est **prêt**, dans l'ordre ici → machine du run → autres ; si aucune,
**ici**, avec les lignes à taper.

➡️ **Recommandé :** proposer ici + machine du run + machines qui voient le même système de fichiers que l'une d'elles ;
défaut comme ci-dessus.

**Réponse :**

Il faut proposer toutes les machines, avec ici en priorité sauf si le service exprime un besoin spécial (auquel cas, il faut faire un tri, et griser puis expliquer pour les machines qui ne fonctionnent pas)

---

## Q5 : Où le choix de machine est gardé

Le relais (`.errand/svc/<name>/…`) doit savoir où envoyer : le choix ne peut pas vivre seulement dans le navigateur.

- **(a) chez errand, par vue** : la page fait `POST .errand/services/<name> {"on": "lmo"}` ; refusé si `lmo` n'est pas
  dans la liste proposée (Q4). Gardé dans l'état de la vue sur la machine qui sert la page ; même choix dans tous les
  navigateurs, et `errand web` peut le montrer.
- **(b) dans l'URL** (`?on.blender=lmo`) : le relais lit le paramètre à chaque requête ; rien de gardé.

Changer de machine n'installe rien et ne lance rien : c'est un aiguillage parmi des services déjà déclarés.

➡️ **Recommandé :** (a), et un changement prend effet à la requête suivante (les connexions ouvertes restent où elles
sont).

**Réponse :**

---

## Q6 : Ce que l'agent a le droit de regarder (le diagnostic)

Pour chaque service et chaque machine, l'agent de cette machine répond un court diagnostic (nouvelle op en lecture,
à côté de `look.OPS`) :

- les services déclarés de ce nom et leurs versions (`blender#91c0d2aa` déclaré, pas `#3fa29c1e`) ;
- les envs errand de la machine qui ont le paquet (`lmo-jax : sdot 2026.11.3, fournit blender#3fa29c1e`) — lu dans les
  `*.dist-info` et le fichier de données du paquet, **sans importer** ;
- les outils : les candidats `look` du paquet, le `PATH`, le cache d'errand (`tools/<sha256>/`), et les chemins que
  l'utilisateur a donnés ; leur version ;
- les cartes (déjà connues de l'agent : `resources`).

Question : l'agent peut-il **exécuter** quelque chose pour lire une version (`/usr/bin/blender --version`) ? Sinon la
version vient de fichiers seulement (`Info.plist`, nom du répertoire `blender-5.2.2-linux-x64`), et un Blender d'apt
reste « version inconnue ».

➡️ **Recommandé :** lecture de fichiers d'abord ; exécution permise **seulement** pour `--version` (arguments fixés par
le paquet installé, jamais par le store), sur des programmes trouvés par errand ou donnés par l'utilisateur, avec un
délai court (5 s) ; résultat mis en cache par (chemin, taille, date) ; le bouton *Refresh* vide ce cache.

**Réponse :**

L'idéal serait de ne pas utiliser `--version`. Si vraiment ce n'est pas possible, il faudrait que l'utilisateur l'autorise explicitement avec la commande détaillée.

---

## Q7 : Les services déclarés dans `errand status` / `errand web`

Aujourd'hui `serve.listed()` ne voit que les répertoires avec `spec.json` (lancés au moins une fois). Proposition :
la liste = tout ce qui est déclaré (`services.py`, installés) ∪ ce qui a un état ; un déclaré jamais lancé est
**`ready`** ; chaque ligne montre `name#version` (sans version pour une déclaration à la main qui n'en donne pas), et
d'où vient la déclaration (`services.py` / `installed`).

➡️ **Recommandé :** oui, avec le mot `ready` (l'état `declared` de `.errand/services` devient `ready` aussi).

**Réponse :**

Je pense qu'on n'a plus besoin de `spec.json`.
Et effectivement, il faudra tout afficher.

---

## Q8 : Quand la machine n'a pas du tout le paquet

Sur une machine sans aucun env qui a sdot, (b) n'a rien à composer : le paquet manque. La page :

- **(a)** dit « aucun env de n14 n'a sdot (le store a été écrit par sdot 2026.11.3) » et montre une ligne
  `micromamba run -n <env> pip install 'sdot==2026.11.3'` à compléter (l'env est à choisir) ; errand ne la lance jamais ;
- **(b)** dit seulement qu'il manque, sans ligne.

Avec (a), le nom du paquet vient du store : un store malhonnête pourrait faire afficher `pip install paquet-piégé`.
La ligne est visible, mais c'est exactement le cas « la personne tape sans lire ».

➡️ **Recommandé :** (b) par défaut ; une ligne `pip install` seulement pour un paquet que la machine qui sert la page
**a elle-même** (même nom, même version, donc déjà de confiance ici), avec son index d'origine.

**Réponse :**

Ça doit être dans `errand-services.json` et errand doit faire des propositions pour installer les paquets.

---
