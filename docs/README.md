# The errand website

[VitePress](https://vitepress.dev). Everything web lives under this directory, so the project root
stays a Python package root.

```bash
cd docs
npm install
npm run dev        # http://localhost:5173/errand/
npm run build      # -> .vitepress/dist
npm run preview    # serve what was built
```

From the project root, the Makefile says the same thing: `make site`, `make site-build`.

## The layout

```
index.md                 the home page: the tagline, by hand vs with errand, what you stop doing
guide/                   the documentation: Start, Places, Running, Nothing left behind,
                         Test suites and entries, Project (the sidebar in config.mts is the order)
tutorials/               three walkthroughs, in order
reference/               the command line, the Python API, tag expressions
.vitepress/config.mts    nav, sidebar, base
.vitepress/theme/        the CSS that makes it errand's, and `Term.vue` + `scenes.js`: the terminal
                         recordings (`<Term scene="tui" />`), drawn by hand, cell by cell
```

`base` is `/errand/`, for GitHub Pages under `github.com/hleclerc/errand`. Change it in
`config.mts` if the site moves.

## Keeping it true

These pages are the source of record for what errand does; the project's README is a short summary of them. When
a behaviour changes, the page that describes it is part of the change — the build fails on a dead
internal link, which catches a page that was removed but not the one that went quietly out of date.

Pages that make a claim about a flag or an argument should be checked against `errand/cli/parsing.py`
(every verb and flag), `errand/layers/`, `errand/vm/` and `errand/__init__.py`, which are where the
answers actually live. A page that moves leaves a stub at its old path (see `guide/remote.md`).

## Publishing

`.github/workflows/docs.yml` builds and deploys on every push to `main` that touches `docs/`. Pages
has to be switched to "GitHub Actions" as its source once, in the repository's settings.
