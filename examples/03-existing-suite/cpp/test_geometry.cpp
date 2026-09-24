// Ordinary Catch2. Untouched -- errand runs the binary and reads its report.
#include <catch2/catch_test_macros.hpp>
#include <catch2/benchmark/catch_benchmark.hpp>

#include "geometry.h"

TEST_CASE( "area", "[geometry]" ) {
    REQUIRE( area( 3, 4 ) == 12 );
}

TEST_CASE( "perimeter", "[geometry]" ) {
    REQUIRE( perimeter( 3, 4 ) == 14 );
}

// Catch2's own benchmarks land in result.yaml like any other numbers, dated
// and per machine -- which is the thing a C++ suite usually never had.
TEST_CASE( "area is cheap", "[geometry][!benchmark]" ) {
    BENCHMARK( "area" ) { return area( 3, 4 ); };
}
