# Les runs tirés du registre local : décisions

- **D'où vient la liste**: le registre local, tous les runs lancés d'ici ( leurs dossiers, leur `result.yaml` ), sans
  limite ; la machine d'un run vient de son `result.yaml`. Ce qui tourne ou attend vient des tables des agents. L'agent
  local tient la lecture à jour. RAM mesurée : ~1 kB par run en dictionnaires ( 62 MB pour 63 000 ), visé ~20-25 MB en
  enregistrements compacts.
- **Quels `errand-outputs/`**: ceux des racines de projets vues ici. `~/A/B` et `~/A/C` donnent `~/A` puis deux sous-listes,
  une pour B, une pour C ( pas de fusion des racines imbriquées ).
- **Classement**: le chemin sous `runs/` ; dossiers, fichier, entrée, jeux, runs ; comptes exacts ; sans `result.yaml` :
  « lost ».
- **Lecture**: un index sur disque, relu au démarrage, mis à jour par date de `result.yaml`, sur la sonnette et par un
  balayage de 60 s ; tenu par l'agent hôte.
- **Effacer**: ici, et là-bas par l'agent de la machine où il a tourné, retrouvé par son chemin sous `runs/` parmi ce qu'il
  a noté ; pas de recherche ailleurs ; une machine injoignable : la vérification le retrouvera.
- **Vérification**: action à part ; « là-bas seulement » listés à leur place, marqués, rapatrier ou effacer ; ici mais plus
  là-bas : rien.
- **Run lancé directement sur une autre machine**: seulement par la vérification.
- **Tests d'errand**: comptés et listés comme les autres.
- **Ordre**: ADR 0025, puis index + arbre, effacer, vérification, TUI.
