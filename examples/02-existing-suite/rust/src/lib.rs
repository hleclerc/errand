// Ordinary cargo. Untouched -- `cargo test` still works on its own.
pub fn area( w: i64, h: i64 ) -> i64 { w * h }
pub fn perimeter( w: i64, h: i64 ) -> i64 { 2 * ( w + h ) }

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn areas( ) { assert_eq!( area( 3, 4 ), 12 ); }

    #[test]
    fn perimeters( ) { assert_eq!( perimeter( 3, 4 ), 14 ); }
}
