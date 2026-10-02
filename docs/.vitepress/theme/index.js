import DefaultTheme from 'vitepress/theme'
import Term from './Term.vue'
import './custom.css'

export default {
  extends: DefaultTheme,
  enhanceApp( { app } ) {
    app.component( 'Term', Term )
  },
}
