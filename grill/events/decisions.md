# Des événements plutôt que de l'interrogation : décisions

## Tour 1 ( 2026-11-19 )

- **But**: rien ne tourne quand rien ne se passe ; un changement vu dès qu'il a lieu ( agent, errand web, page, TUI ).
- **Ce que l'agent annonce**: ce qui a changé ( process lancé / fini, run noté / fini / effacé, étape, vue, lignes de sortie à la demande, ressources ) ; un état complet à l'abonnement et après reconnexion, pas de rejeu.
- **Ce qu'il ne voit pas passer**: un balayage lent, table et historique toutes les 60 s et à chaque abonnement ; un écart trouvé annoncé comme événement. Pas de notifications du système de fichiers.
- **Ressources**: mesurées seulement quand un veilleur les demande ( toutes les 5 s alors, envoyées si elles bougent ).
- **Page**: un flux SSE `/events` d'avis courts ( « la liste a changé », « le détail de X a changé » ) ; la page relit `/state` / `/detail` sur avis ; plus d'interrogation toutes les 2 s.
- **Console**: en flux, errand web s'abonne à la sortie d'un run en cours auprès de l'agent ( comme `errand attach` ) et la pousse.
- **TUI**: redessine sur événement ou touche ; seules les durées qui défilent avancent à la seconde.
- **Anciens agents**: pas de compatibilité ; on peut les arrêter ( Hugo : « On peut virer les anciens agents. Je relancerai les calculs » ).
- **Travail**: ADR 0024 d'abord ; puis agent ( événements, balayage, ressources à la demande ), errand web ( `/events` ), console en flux, TUI.
