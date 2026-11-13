import { defineConfig } from 'vitepress'

export default defineConfig( {
  title: "errand",
  description: "Run a piece of work — here, in that environment, in that container, on that machine — and bring back everything it produced.",
  lang: 'en-US',

  // GitHub Pages under github.com/hleclerc/errand
  base: '/errand/',

  // Decision records are for whoever works on errand, not for the site.
  srcExclude: [ 'adr/**' ],

  cleanUrls: true,
  lastUpdated: true,

  head: [
    [ 'meta', { name: 'theme-color', content: '#c2410c' } ],
  ],

  themeConfig: {
    nav: [
      { text: 'Guide',     link: '/guide/what-is-errand' },
      { text: 'Tutorials', link: '/tutorials/' },
      { text: 'Reference', link: '/reference/cli' },
      { text: 'PyPI',      link: 'https://pypi.org/project/errand-run/' },
    ],

    // One sidebar for the whole site, every group folded but the first: the guide, the tutorials and
    // the reference are one book, and the menu is its table of contents.
    sidebar: [
      {
        text: 'Start', collapsed: false,
        items: [
          { text: 'What errand is',    link: '/guide/what-is-errand' },
          { text: 'Installing',        link: '/guide/installing' },
          { text: 'Getting started',   link: '/guide/start' },
          { text: 'Tutorials', link: '/tutorials/', collapsed: true, items: [
            { text: '1 · Four environments',         link: '/tutorials/environments' },
            { text: '2 · Adopt an existing suite',   link: '/tutorials/adopt-a-suite' },
            { text: '3 · Numbers over two machines', link: '/tutorials/two-machines' },
            { text: '4 · errand\'s own entries',     link: '/tutorials/first-entry' },
          ] },
        ]
      },
      {
        text: 'Environments', collapsed: true,
        items: [
          { text: 'Environments',         link: '/guide/environments' },
          { text: 'Keeping them current', link: '/guide/upkeep' },
          { text: 'Tags',                 link: '/guide/tags' },
          { text: 'Layers', link: '/guide/layers/', collapsed: true, items: [
            { text: 'Ssh',                         link: '/guide/layers/ssh' },
            { text: 'Slurm',                       link: '/guide/layers/slurm' },
            { text: 'Windows',                     link: '/guide/layers/windows' },
            { text: 'Apptainer, Docker, Podman',   link: '/guide/layers/containers' },
            { text: 'Micromamba, Conda',           link: '/guide/layers/micromamba' },
            { text: 'Venv, Uv',                    link: '/guide/layers/venv' },
            { text: 'Nix, Guix',                   link: '/guide/layers/nix-guix' },
            { text: 'Module',                      link: '/guide/layers/module' },
            { text: 'Mpi',                         link: '/guide/layers/mpi' },
            { text: 'Preload',                     link: '/guide/layers/preload' },
            { text: 'Vars',                        link: '/guide/layers/vars' },
          ] },
        ]
      },
      {
        text: 'Running', collapsed: true,
        items: [
          { text: 'Running it',            link: '/guide/running' },
          { text: 'Fast, and nothing lost', link: '/guide/agents' },
          { text: 'Runners', link: '/guide/runners/', collapsed: true, items: [
            { text: 'Pytest',                  link: '/guide/runners/pytest' },
            { text: 'Catch2',                  link: '/guide/runners/catch2' },
            { text: 'Cargo',                   link: '/guide/runners/cargo' },
            { text: 'Scripts and executables', link: '/guide/runners/scripts' },
            { text: 'Writing a runner',        link: '/guide/runners/writing' },
          ] },
          { text: 'Parameters & matrices',   link: '/guide/matrices' },
          { text: 'Several processes (MPI)', link: '/guide/mpi' },
          { text: 'Sharing the machine',     link: '/guide/machine' },
          { text: 'Detached runs',           link: '/guide/detached' },
        ]
      },
      {
        text: 'Results', collapsed: true,
        items: [
          { text: 'Where the output goes', link: '/guide/output' },
          { text: 'The screen',            link: '/guide/tui' },
        ]
      },
      {
        text: 'Project', collapsed: true,
        items: [
          { text: 'Configuration',   link: '/guide/configuration' },
          { text: 'Writing entries', link: '/guide/declaring-work' },
          { text: 'Where errand writes', link: '/guide/storage' },
        ]
      },
      {
        text: 'Reference', collapsed: true,
        items: [
          { text: 'Command line',    link: '/reference/cli' },
          { text: 'Python API',      link: '/reference/python-api' },
          { text: 'Tag expressions', link: '/reference/expressions' },
        ]
      },
    ],

    socialLinks: [
      { icon: 'github', link: 'https://github.com/hleclerc/errand' }
    ],

    search: { provider: 'local' },

    outline: { level: [ 2, 3 ] },

    editLink: {
      pattern: 'https://github.com/hleclerc/errand/edit/main/docs/:path',
      text: 'Edit this page on GitHub'
    },

    footer: {
      message: 'MIT licensed. Status: everything documented here works; the API may still move.',
      copyright: 'errand — H. Leclerc'
    }
  }
} )
