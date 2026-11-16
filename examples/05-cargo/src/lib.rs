//! Ordinary cargo: `cargo test` still works on its own. Nothing here knows about errand.

/// Merges overlapping or touching closed intervals; the result is sorted and disjoint.
pub fn merge( mut spans: Vec<( i64, i64 )> ) -> Vec<( i64, i64 )> {
    spans.retain( |&( a, b )| a <= b );
    spans.sort_unstable();
    let mut out: Vec<( i64, i64 )> = Vec::with_capacity( spans.len() );
    for ( a, b ) in spans {
        match out.last_mut() {
            Some( last ) if a <= last.1 + 1 => last.1 = last.1.max( b ),
            _ => out.push( ( a, b ) ),
        }
    }
    out
}

/// How many integers the intervals cover, counted once.
pub fn covered( spans: Vec<( i64, i64 )> ) -> i64 {
    merge( spans ).iter().map( |&( a, b )| b - a + 1 ).sum()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn overlapping( ) { assert_eq!( merge( vec![ ( 1, 3 ), ( 2, 6 ) ] ), vec![ ( 1, 6 ) ] ); }

    #[test]
    fn touching( ) { assert_eq!( merge( vec![ ( 1, 2 ), ( 3, 4 ) ] ), vec![ ( 1, 4 ) ] ); }

    #[test]
    fn empty_ones_go( ) { assert_eq!( merge( vec![ ( 5, 1 ), ( 7, 7 ) ] ), vec![ ( 7, 7 ) ] ); }

    // Ignored by default: `cargo test -- --ignored` runs it, and so does errand ( below ).
    #[test]
    #[ignore]
    fn many( ) {
        let spans: Vec<_> = ( 0..2_000_000 ).map( |i| ( 2 * i, 2 * i ) ).collect();
        assert_eq!( merge( spans ).len(), 2_000_000 );
    }
}
