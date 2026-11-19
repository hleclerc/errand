# Les runs tirés du registre local : tour 1

> Laisse **Réponse** vide pour accepter la recommandation. `?` pour plus de détails.
> Écris autre chose ( réponse, objection, commentaire ) sous n'importe quelle question, puis Envoyer.

Ce qui est là ( mesuré sur ce Mac ) :

- `~/Projects/errand-outputs/runs/` tient **62 989 runs** avec leur `result.yaml`, dont **9 969 lancés sur lmo** :
  chaque run lancé d'ici, où qu'il ait tourné, y a son dossier ( `output.txt`, `result.yaml`, ses sorties ramenées ).
  Le `result.yaml` dit tout : `name`, `file`, `env`, `place` ( `lmo-torch@leclerc-Precision-5820-Tower` ), `host`,
  `status`, `duration_s`, `params`, `results`.
- D'autres `errand-outputs/` : `errand/`, `otrec/`, `sdot-ffi/`, `loom/`, `test_errand/`, `loombox-scratch/`.
- Parcourir les 62 989 dossiers : **0,25 s**. Lire tous les `result.yaml` : ~6 s la première fois ( 0,1 ms chacun ).
- Aujourd'hui l'arbre vient de l'historique de chaque agent ( ses liens `seen`, les 1000 derniers ), fusionné : d'où
  les comptes faux, les vieux runs qui remontent, et une suppression qui doit chercher sur chaque machine.

---

## Q1 : D'où vient la liste

- **(a) le registre local** : les dossiers de runs de ce Mac ( ceux lancés d'ici, ramenés ou pas encore ), tous, sans
  limite ; la machine où un run a tourné vient de son `result.yaml` ( `place`, `host` ), rapportée au nom de la
  machine dans le registre d'errand ( `Lmo`, `node14` ) ;
- (b) l'historique des agents, comme aujourd'hui.

Ce qui tourne ou attend vient toujours des tables des agents ( c'est vivant ), et se place dans l'arbre à son
dossier.

➡️ **Recommandé :** (a).

**Réponse :**

Oui pour le registre local. Rq: l'agent local peut avoir la charge de maintenir la lecture à jour des result.yaml pour maintenir une vue sur les runs, le cache, etc... Ça ne devrait pas prendre trop de place en RAM, non ?

---

## Q2 : Quels `errand-outputs/`

- **(a)** ceux des projets de ce Mac : chaque racine de projet qu'errand a vue ici ( les liens `seen` en gardent la
  racine : `~/Projects`, `~/Projects/errand`, `~/Projects/otrec`, … ), son `errand-outputs/runs/` ( ou ce que sa
  config nomme ) ; un dossier de projet disparu sort de la liste ;
- (b) une liste écrite à la main dans la config.

Une racine imbriquée dans une autre ( `~/Projects` et `~/Projects/otrec` ) : deux arbres de runs distincts, l'arbre
les range sous leur chemin ( `otrec/…` vient de `~/Projects`, les runs de `~/Projects/otrec/errand-outputs` sous
`otrec/` aussi : ils se fondent ).

➡️ **Recommandé :** (a).

**Réponse :**

~/A/B et ~/A/C donnent ~/A puis 2 sous listes. 1 pour B, 1 pour C

---

## Q3 : Le classement par dossier

Le chemin sous `runs/` **est** le classement : `<dossiers>/<fichier>/<entrée>/<run>`, ou `<dossiers>/<fichier>/<run>`
pour un fichier lancé en entier ( `sh x.sh` ). Le `result.yaml` dit le fichier et l'entrée : on coupe le chemin là,
sans deviner.

- Les niveaux : dossiers ( fusionnés quand ils n'ont qu'un enfant ), fichier, entrée, jeux de paramètres, runs, comme
  aujourd'hui ; **les comptes sont exacts** ( tous les runs ).
- Un run sans `result.yaml` ( interrompu, tué ) : rangé par son chemin, statut « lost ».

➡️ **Recommandé :** comme ci-dessus.

**Réponse :**

---

## Q4 : Lire 63 000 `result.yaml`

- **(a) un index** sur disque ( `~/.cache/errand/runs-index` : un enregistrement par run, avec la date de son
  `result.yaml` ), relu au démarrage ; un dossier dont la date n'a pas changé n'est pas relu ; un run qui se termine
  ou qui est ramené le met à jour tout de suite ( le pilote sonne : ADR 0024 ) ; un balayage des dates toutes les
  60 s pour le reste ( 0,25 s ) ;
- (b) tout relire au démarrage de `errand web` / `errand tui` ( ~6 s ), puis en mémoire.

Qui tient l'index : l'agent hôte de ce Mac ( il sert déjà la page, il entend la sonnette ) ; la TUI le lui demande.

➡️ **Recommandé :** (a), tenu par l'agent hôte.

**Réponse :**

---

## Q5 : Effacer

Un run : son dossier ici, et, s'il a tourné ailleurs, son dossier là-bas, par l'agent de cette machine. Là-bas, il est
retrouvé par son chemin sous `errand-outputs/runs/` ( le même des deux côtés ) parmi les runs que cet agent a notés ;
jamais rien d'autre.

- Plus de recherche sur les autres machines : ce qui est effacé est ce qui est listé ( avec les comptes exacts, la
  fenêtre dit tout de suite combien ; la place libérée arrive après ).
- Une machine injoignable : l'ici est effacé, le là-bas reste et **sera trouvé par la vérification** ( Q6 ).

➡️ **Recommandé :** comme ci-dessus.

**Réponse :**

---

## Q6 : La vérification

Une action à part ( un bouton « vérifier », `c` dans la TUI ), qui demande à chaque machine les runs qu'elle a notés
( tous ) et les compare au registre d'ici :

- **là-bas seulement** ( effacé ici mais pas là-bas, ou lancé d'ailleurs ) : listés dans l'arbre à leur place,
  marqués « sur lmo seulement », avec **rapatrier** ( le dossier ramené ici, comme `-o` ) ou **effacer** ;
- ici, mais plus là-bas : rien à faire ( la copie d'ici est le run ), pas signalé.

Ce qu'elle a trouvé reste affiché jusqu'à la vérification suivante ou jusqu'à ce que ce soit réglé.

➡️ **Recommandé :** comme ci-dessus.

**Réponse :**

---

## Q7 : Un run lancé directement sur lmo ( pas depuis ce Mac )

Il n'est pas dans le registre d'ici.

- **(a)** il n'apparaît qu'à la vérification, « sur lmo seulement », rapatriable ;
- (b) les agents continuent d'envoyer leur historique et ces runs apparaissent toujours.

➡️ **Recommandé :** (a) : la liste est celle d'ici ; la vérification montre le reste.

**Réponse :**

---

## Q8 : Les runs des tests d'errand

Sur 62 989 runs, l'essentiel est des tests d'errand ( `errand/tests/…`, faits dans des dossiers temporaires ou dans
`errand-outputs` ). Ils seront comptés et listés comme les autres.

- **(a)** comme les autres : on les efface avec `d` sur `errand/tests/` ;
- (b) cachés par défaut.

➡️ **Recommandé :** (a).

**Réponse :**

---

## Q9 : L'ADR et l'ordre

Un ADR 0025 ( « la liste des runs est celle d'ici » ), qui remplace la partie « d'où ça vient » de l'ADR 0023, puis :

1. l'index ( l'agent hôte : balayage, `result.yaml`, sonnette ) et l'arbre qui en vient, avec ce qui tourne ;
2. effacer ici et là-bas ;
3. la vérification ( là-bas seulement, rapatrier, effacer ) ;
4. la TUI.

➡️ **Recommandé :** cet ordre, l'ADR d'abord.

**Réponse :**

---
