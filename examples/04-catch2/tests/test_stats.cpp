// Ordinary Catch2. `./build/default/test_stats` runs it on its own, exactly as before.
#include <catch2/catch_test_macros.hpp>
#include <catch2/catch_approx.hpp>
#include <catch2/benchmark/catch_benchmark.hpp>

#include <numeric>
#include "stats.hpp"

TEST_CASE( "mean", "[stats]" ) {
    REQUIRE( stats::mean( { 1, 2, 3, 4 } ) == Catch::Approx( 2.5 ) );
    REQUIRE_THROWS( stats::mean( { } ) );
}

TEST_CASE( "variance", "[stats]" ) {
    REQUIRE( stats::variance( { 2, 4, 4, 4, 5, 5, 7, 9 } ) == Catch::Approx( 32.0 / 7 ) );
}

// A large offset is where the textbook formula loses every digit; Welford keeps them.
TEST_CASE( "variance far from zero", "[stats][slow]" ) {
    std::vector<double> x( 1000000 );
    for ( std::size_t i = 0; i < x.size(); ++i ) x[ i ] = 1e9 + ( i % 2 );
    double n = x.size();
    REQUIRE( stats::variance( x ) == Catch::Approx( 0.25 * n / ( n - 1 ) ) );
}

TEST_CASE( "median", "[stats]" ) {
    REQUIRE( stats::median( { 3, 1, 2 } ) == 2 );
    REQUIRE( stats::median( { 4, 1, 3, 2 } ) == Catch::Approx( 2.5 ) );
}

// Catch2 measures this itself; errand writes the numbers into the run's result.yaml.
TEST_CASE( "speed", "[stats][benchmark]" ) {
    std::vector<double> x( 10000 );
    std::iota( x.begin(), x.end(), 0.0 );
    BENCHMARK( "mean_10k" ) { return stats::mean( x ); };
    BENCHMARK( "median_10k" ) { return stats::median( x ); };
}
