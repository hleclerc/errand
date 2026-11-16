// A second suite: a second binary, built by the same build, run as a run of its own.
#include <catch2/catch_test_macros.hpp>
#include <catch2/catch_approx.hpp>

#include <limits>
#include "stats.hpp"

TEST_CASE( "a single value has no variance", "[edges]" ) {
    REQUIRE_THROWS_AS( stats::variance( { 1.0 } ), std::invalid_argument );
}

TEST_CASE( "an even count takes the middle two", "[edges]" ) {
    REQUIRE( stats::median( { 1, 100 } ) == Catch::Approx( 50.5 ) );
}

TEST_CASE( "infinity propagates", "[edges]" ) {
    double inf = std::numeric_limits<double>::infinity();
    REQUIRE( stats::mean( { 1, inf } ) == inf );
}
