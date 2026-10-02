// The recordings on the site: scenes of a terminal, drawn cell by cell.
//
// They are drawn BY HAND from the screens the guide describes -- not captured -- so that they
// can show what a capture on one laptop never would: three machines and four layers at once.
// A scene is { cols, rows, frames: [ { ms, html } ] }; `html` is built here, from text written
// here, which is why it is safe to hand to v-html.

const ESC = { '&': '&amp;', '<': '&lt;', '>': '&gt;' }
const esc = ( s ) => s.replace( /[&<>]/g, ( c ) => ESC[ c ] )

class Grid {
  constructor( rows, cols ) {
    this.rows = rows
    this.cols = cols
    this.cells = Array.from( { length: rows }, () => Array.from( { length: cols }, () => [ ' ', '' ] ) )
  }
  put( r, c, text, cls = '' ) {
    if ( r < 0 || r >= this.rows ) return this
    let i = 0
    for ( const ch of text ) {
      if ( c + i >= 0 && c + i < this.cols ) this.cells[ r ][ c + i ] = [ ch, cls ]
      i++
    }
    return this
  }
  fill( r, c, h, w ) {
    for ( let y = r; y < r + h; y++ ) this.put( y, c, ' '.repeat( w ) )
    return this
  }
  box( r, c, h, w, title = '', cls = 'dim', titleCls = '' ) {
    this.fill( r, c, h, w )
    this.put( r, c, '╭' + '─'.repeat( w - 2 ) + '╮', cls )
    this.put( r + h - 1, c, '╰' + '─'.repeat( w - 2 ) + '╯', cls )
    for ( let y = r + 1; y < r + h - 1; y++ ) {
      this.put( y, c, '│', cls )
      this.put( y, c + w - 1, '│', cls )
    }
    if ( title ) this.put( r, c + 2, ' ' + title + ' ', titleCls || cls )
    return this
  }
  html() {
    return this.cells.map( ( row ) => {
      let out = '', cur = null, buf = ''
      const flush = () => { if ( buf ) out += cur ? `<span class="t-${ cur }">${ esc( buf ) }</span>` : esc( buf ); buf = '' }
      for ( const [ ch, cls ] of row ) {
        if ( cls !== cur ) { flush(); cur = cls }
        buf += ch
      }
      flush()
      return out.replace( /\s+$/, '' )
    } ).join( '\n' )
  }
}

// ── one command, four contexts ───────────────────────────────────────────────

function stack() {
  const cols = 66, rows = 20
  const nest = [
    { r: 2, c: 1, h: 9, w: 62, title: 'your laptop' },
    { r: 3, c: 3, h: 7, w: 58, title: 'ssh · gpu-box' },
    { r: 4, c: 5, h: 5, w: 54, title: 'slurm · partition gpu · node042' },
    { r: 5, c: 7, h: 3, w: 50, title: 'apptainer · cuda.sif' },
  ]
  const log = [
    [ 'push', 'rsync the project to gpu-box' ],
    [ 'wait', 'sbatch --partition gpu     job 48213' ],
    [ 'run',  'apptainer exec cuda.sif   (rebuilt only if the .def changed)' ],
  ]
  const frames = []
  const draw = ( { typed = 0, depth = 0, logged = 0, running = false, dots = 0, back = 0, done = false } ) => {
    const g = new Grid( rows, cols )
    const cmd = '$ errand train --env cluster'
    g.put( 0, 1, '$ ', 'dim' ).put( 0, 3, cmd.slice( 2, 2 + typed ), 'b' )
    for ( let i = 0; i < depth; i++ ) {
      const n = nest[ i ]
      const active = running ? true : i === depth - 1
      g.box( n.r, n.c, n.h, n.w, n.title, active ? 'run' : 'dim', active ? 'run' : 'dim' )
    }
    if ( depth === nest.length ) g.put( 6, 9, 'train', running ? 'b' : '' ).put( 6, 25, running ? '.'.repeat( dots ) : '', 'run' )
    for ( let i = 0; i < logged; i++ ) {
      g.put( 12 + i, 2, '→', 'run' ).put( 12 + i, 4, log[ i ][ 1 ], 'dim' )
    }
    if ( back >= 1 ) g.put( 15, 2, '←', 'ok' ).put( 15, 4, 'rsync runs/train/…/ back to your laptop', 'dim' )
    if ( done ) g.put( 17, 2, 'PASS', 'ok' ).put( 17, 7, 'train   cluster@gpu-box   42.1s   runs/train/latest/', '' )
    return g.html()
  }
  const cmdLen = 'errand train --env cluster'.length
  for ( let t = 0; t <= cmdLen; t += 3 ) frames.push( { ms: 45, html: draw( { typed: Math.min( t, cmdLen ) } ) } )
  frames.push( { ms: 500, html: draw( { typed: cmdLen } ) } )
  for ( let d = 1; d <= nest.length; d++ ) {
    frames.push( { ms: 650, html: draw( { typed: cmdLen, depth: d, logged: Math.min( d - 1, log.length ) } ) } )
  }
  frames.push( { ms: 500, html: draw( { typed: cmdLen, depth: 4, logged: 3 } ) } )
  for ( let k = 0; k < 6; k++ ) frames.push( { ms: 300, html: draw( { typed: cmdLen, depth: 4, logged: 3, running: true, dots: 1 + ( k % 3 ) } ) } )
  frames.push( { ms: 700, html: draw( { typed: cmdLen, depth: 4, logged: 3, back: 1 } ) } )
  frames.push( { ms: 3200, html: draw( { typed: cmdLen, depth: 4, logged: 3, back: 1, done: true } ) } )
  return { cols, rows, title: 'errand', frames }
}

// ── errand --tui, over three machines ────────────────────────────────────────

function tui() {
  const cols = 82, rows = 24
  const frames = []

  const CASES = [
    [ 'solve',          'bench/shapes.py:42' ],
    [ 'solve_coarse',   'bench/shapes.py:61' ],
    [ 'shape_gradient', 'tests/geometry.py:9' ],
  ]
  const header = ( g, page, state ) => {
    g.put( 0, 1, page === 'cases' ? '[cases]' : ' cases ', page === 'cases' ? 'hl' : 'dim' )
    g.put( 0, 9, page === 'runs' ? '[runs]' : ' runs ', page === 'runs' ? 'hl' : 'dim' )
    g.put( 0, cols - 36, `errand · myproject · ${ state }`, state === 'running' ? 'run' : 'dim' )
  }
  const footer = ( g, text ) => g.put( rows - 1, 1, text, 'dim' )

  // cases page ---------------------------------------------------------------
  const casesPage = ( find, selected, { dim = false } = {} ) => {
    const g = new Grid( rows, cols )
    header( g, 'cases', 'idle' )
    g.put( 1, 1, 'find: ', 'dim' ).put( 1, 7, find, 'b' ).put( 1, 7 + find.length, '▏', 'run' )
    const shown = find ? CASES.filter( ( c ) => c[ 0 ].startsWith( find ) || ( find === 'sol' && c[ 0 ].startsWith( 'sol' ) ) ) : CASES
    const list = find ? shown : CASES
    g.box( 2, 1, 10, 38, `cases  ${ list.length } found`, 'dim' )
    list.forEach( ( c, i ) => {
      const sel = i === selected
      g.put( 3 + i, 3, ( sel ? '› ' : '  ' ) , sel ? 'run' : '' )
      g.put( 3 + i, 5, c[ 0 ].slice( 0, find.length ), 'b' ).put( 3 + i, 5 + find.length, c[ 0 ].slice( find.length ), sel ? 'hl' : '' )
      g.put( 3 + i, 20, c[ 1 ], 'dim' )
    } )
    g.box( 2, 40, 17, 41, 'solve', 'dim' )
    const r = [ 'bench/shapes.py:42', 'kind: bench', 'tags: gpu', 'needs: gpus=1', '', '--n   default 1000', '  how many points', '', 'last run', '  PASS   local   local@laptop', '  seconds = 12.406' ]
    r.forEach( ( t, i ) => g.put( 3 + i, 42, t, i === 8 ? 'b' : i > 8 ? 'ok' : i === 5 || i === 6 ? '' : 'dim' ) )
    footer( g, 'type to search · enter runs it · space ticks · tab next box · F3 runs · F1 keys' )
    return g
  }

  // the dialog ---------------------------------------------------------------
  const dialog = ( ticked, row, command ) => {
    const g = casesPage( 'sol', 0 )
    g.box( 5, 2, 14, 78, 'run: solve', 'run', 'run' )
    const chip = ( on, name ) => ( on ? '[x] ' : '[ ] ' ) + name
    g.put( 7, 4, '› --env', 'run' )
    let c = 17
    for ( const [ name, on ] of [ [ 'local', ticked[ 0 ] ], [ 'gpu', ticked[ 1 ] ], [ 'cluster', ticked[ 2 ] ] ] ) {
      g.put( 7, c, chip( on, name ), on ? 'b' : 'dim' ); c += chip( on, name ).length + 3
    }
    g.put( 7, 58, `${ ticked.filter( Boolean ).length > 1 ? 'two or more ticks' : 'one tick' } = ${ ticked.filter( Boolean ).length || 1 } run${ ticked.filter( Boolean ).length > 1 ? 's' : '' }`.slice( 0, 20 ), 'dim' )
    g.put( 8, 4, '  --n', '' ).put( 8, 17, '1000', 'dim' ).put( 8, 58, 'how many points', 'dim' )
    g.put( 9, 4, '  -j', '' ).put( 9, 17, '1', 'dim' ).put( 9, 58, 'how many at once', 'dim' )
    g.put( 10, 4, '  --batch', '' ).put( 10, 17, '[ ] detach', 'dim' ).put( 10, 58, 'outlives this window', 'dim' )
    g.put( 11, 4, '─'.repeat( 74 ), 'dim' )
    g.put( 12, 4, command, 'ok' )
    g.put( 14, 4, 'space ticks · ←→ picks · type into a field · enter runs · esc gives up', 'dim' )
    return g
  }

  // runs page ----------------------------------------------------------------
  const ENVS = [
    { name: 'local',   chain: 'micromamba:demo' },
    { name: 'gpu',     chain: 'apptainer:cuda.sif' },
    { name: 'cluster', chain: 'ssh:gpu-box -> slurm:gpu -> apptainer:cuda.sif' },
  ]
  const CLUSTER_LOG = [
    '-> cluster',
    '   ssh:gpu-box -> slurm:gpu',
    '   -> apptainer:cuda.sif',
    'rsync  project -> gpu-box',
    'sbatch job 48213 .. pending',
    'job 48213 running on node042',
    'iteration 41   residual 3.1e-07',
    'iteration 42   residual 1.9e-07',
    'rsync  results <- gpu-box',
  ]
  const runsPage = ( status, sel, cl ) => {
    // status: [local, gpu, cluster] each '..' or 'ok' ; cl: how many lines of the cluster log
    const g = new Grid( rows, cols )
    const done = status.filter( ( s ) => s === 'ok' ).length
    header( g, 'runs', done === 3 ? 'idle' : 'running' )
    g.put( 1, 1, 'find: ', 'dim' ).put( 1, 7, '▏', 'run' )
    g.box( 2, 1, 12, 46, 'runs', 'dim' )
    g.put( 3, 3, '▾ errand solve --env local,gpu,cluster', 'b' ).put( 3, 43, `${ done }/3`, done === 3 ? 'ok' : 'run' )
    ENVS.forEach( ( e, i ) => {
      const sel_ = i === sel
      g.put( 4 + i, 3, sel_ ? '›' : ' ', 'run' )
      g.put( 4 + i, 5, status[ i ] === 'ok' ? 'ok' : '..', status[ i ] === 'ok' ? 'ok' : 'run' )
      g.put( 4 + i, 10, `solve  n=1000  [${ e.name }]`, sel_ ? 'hl' : '' )
    } )
    g.put( 8, 3, '▸ errand tests --n 10', 'dim' ).put( 8, 40, '1 ok', 'dim' )
    g.put( 9, 3, '▸ errand -k bench --fp 32', 'dim' ).put( 9, 40, '6 ok', 'dim' )
    g.box( 2, 48, 6, 33, 'files', 'dim' )
    g.put( 3, 50, 'output.txt', '' ).put( 3, 70, '1.2 kB', 'dim' )
    g.put( 4, 50, 'result.yaml', '' ).put( 4, 70, '512 B', 'dim' )
    g.put( 5, 50, 'residual.png', '' ).put( 5, 70, '12 kB', 'dim' )
    g.box( 8, 48, 14, 33, 'output.txt', 'dim' )
    const env = ENVS[ sel ]
    if ( sel === 2 ) {
      CLUSTER_LOG.slice( 0, cl ).forEach( ( t, i ) => g.put( 9 + i, 50, t.slice( 0, 29 ), i < 3 ? 'dim' : i === 8 ? 'ok' : '' ) )
    } else {
      const lines = [ `-> ${ env.name }  ${ env.chain }`, '', 'iteration 41   residual 3.1e-07', 'iteration 42   residual 1.9e-07' ]
      lines.forEach( ( t, i ) => g.put( 9 + i, 50, t.slice( 0, 29 ), i === 0 ? 'dim' : '' ) )
    }
    // the layers each case went through, which is what makes the rows differ
    g.put( 15, 3, 'layers of the one under the cursor', 'dim' )
    env.chain.split( ' -> ' ).forEach( ( layer, i ) => g.put( 16 + i, 3, ( i ? '→ ' : '  ' ) + layer, 'run' ) )
    footer( g, 'enter: its files · F6 runs it again · F7 interrupts · F8 opens the file' )
    return g
  }

  const add = ( g, ms ) => frames.push( { ms, html: g.html() } )

  add( casesPage( '', 0 ), 1300 )
  for ( const f of [ 's', 'so', 'sol' ] ) add( casesPage( f, 0 ), 380 )
  add( casesPage( 'sol', 0 ), 500 )
  const cmd = ( t ) => 'errand solve' + ( t.every( ( x ) => !x ) ? '' : ` --env ${ [ 'local', 'gpu', 'cluster' ].filter( ( _, i ) => t[ i ] ).join( ',' ) }` )
  for ( const t of [ [ 0, 0, 0 ], [ 1, 0, 0 ], [ 1, 1, 0 ], [ 1, 1, 1 ] ] ) add( dialog( t.map( Boolean ), 0, cmd( t ) ), t.some( Boolean ) ? 650 : 900 )
  add( dialog( [ true, true, true ], 0, cmd( [ 1, 1, 1 ] ) ), 700 )
  add( runsPage( [ '..', '..', '..' ], 0, 0 ), 700 )
  add( runsPage( [ 'ok', '..', '..' ], 0, 0 ), 700 )
  add( runsPage( [ 'ok', 'ok', '..' ], 2, 3 ), 600 )
  for ( let n = 3; n <= 9; n++ ) add( runsPage( [ 'ok', 'ok', n === 9 ? 'ok' : '..' ], 2, n ), n === 9 ? 3600 : 800 )
  return { cols, rows, title: 'errand --tui', frames }
}

export const scenes = { stack, tui }
