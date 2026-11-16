// An integration test: a test target of its own, so a run of its own under errand.
use intervals::covered;

#[test]
fn counted_once( ) { assert_eq!( covered( vec![ ( 1, 10 ), ( 5, 15 ) ] ), 15 ); }

#[test]
fn apart( ) { assert_eq!( covered( vec![ ( 1, 1 ), ( 10, 10 ) ] ), 2 ); }
