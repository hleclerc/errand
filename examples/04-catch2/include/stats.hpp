// An ordinary header-only library. Nothing here knows about errand.
#pragma once

#include <algorithm>
#include <cmath>
#include <stdexcept>
#include <vector>

namespace stats {

inline double mean( const std::vector<double> &x ) {
    if ( x.empty() ) throw std::invalid_argument( "mean of nothing" );
    double s = 0;
    for ( double v : x ) s += v;
    return s / x.size();
}

// Welford: one pass, and no catastrophic cancellation on large offsets.
inline double variance( const std::vector<double> &x ) {
    if ( x.size() < 2 ) throw std::invalid_argument( "variance needs two values" );
    double m = 0, m2 = 0;
    std::size_t n = 0;
    for ( double v : x ) {
        ++n;
        double d = v - m;
        m += d / n;
        m2 += d * ( v - m );
    }
    return m2 / ( n - 1 );
}

inline double median( std::vector<double> x ) {
    if ( x.empty() ) throw std::invalid_argument( "median of nothing" );
    auto mid = x.begin() + x.size() / 2;
    std::nth_element( x.begin(), mid, x.end() );
    if ( x.size() % 2 ) return *mid;
    double hi = *mid;
    return ( *std::max_element( x.begin(), mid ) + hi ) / 2;
}

} // namespace stats
