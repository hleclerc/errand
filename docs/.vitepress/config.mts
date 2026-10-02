import { defineConfig } from 'vitepress'

export default defineConfig( {
  title: "errand",
  description: "Run a piece of work — here, in that environment, in that container, on that machine — and bring back everything it produced.",
  lang: 'en-US',

  // GitHub Pages under github.com/hleclerc/errand
  base: '/errand/',

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

    sidebar: {
      '/guide/': [
        {
          text: 'Getting started',
          items: [
            { text: 'What errand is',    link: '/guide/what-is-errand' },
            { text: 'Installing',        link: '/guide/installing' },
            { text: 'Start from what you have', link: '/guide/start' },
          ]
        },
        {
          text: 'Where and how it runs',
          items: [
            { text: 'Environments (layers)', link: '/guide/environments' },
            { text: 'Keeping them current', link: '/guide/upkeep' },
            { text: 'Tags',              link: '/guide/tags' },
            { text: 'Running elsewhere', link: '/guide/remote' },
            { text: 'Detached runs',     link: '/guide/detached' },
          ]
        },
        {
          text: 'Running work',
          items: [
            { text: 'Running it',        link: '/guide/running' },
            { text: 'Parameters & matrices', link: '/guide/matrices' },
            { text: 'Other languages',   link: '/guide/providers' },
            { text: 'Writing entries',   link: '/guide/declaring-work' },
          ]
        },
        {
          text: 'Sharing and results',
          items: [
            { text: 'Sharing the machine', link: '/guide/machine' },
            { text: 'Where the output goes', link: '/guide/output' },
            { text: 'The screen',        link: '/guide/tui' },
          ]
        },
        {
          text: 'Projects',
          items: [
            { text: 'Configuration',     link: '/guide/configuration' },
          ]
        },
      ],

      '/tutorials/': [
        {
          text: 'Tutorials',
          items: [
            { text: 'All of them',               link: '/tutorials/' },
            { text: '1 · errand\'s own entries',  link: '/tutorials/first-entry' },
            { text: '2 · Four environments',     link: '/tutorials/environments' },
            { text: '3 · Adopt an existing suite', link: '/tutorials/adopt-a-suite' },
            { text: '4 · Numbers over two machines', link: '/tutorials/two-machines' },
          ]
        }
      ],

      '/reference/': [
        {
          text: 'Reference',
          items: [
            { text: 'Command line',    link: '/reference/cli' },
            { text: 'Python API',      link: '/reference/python-api' },
            { text: 'Layers',          link: '/reference/layers' },
            { text: 'Providers',       link: '/reference/providers' },
            { text: 'Tag expressions', link: '/reference/expressions' },
            { text: 'Output files',    link: '/reference/output-files' },
          ]
        }
      ],
    },

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
