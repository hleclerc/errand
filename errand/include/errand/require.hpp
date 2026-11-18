// errand::require: a run asks the machine for more than it was started with, and waits until it is
// given ( ADR 0014 ). The C++ side of `errand.require`, header-only, C++17.
//
//     #include <errand/require.hpp>
//
//     int main() {
//         errand::require( { .gpus = 1, .gpu_ram = "75%" } );     // C++20; in C++17, fill a Needs
//         ...                                                      // CUDA_VISIBLE_DEVICES is set
//     }
//
// Call it early, before what it protects is allocated ( before the first CUDA call ). It only adds to
// the run's claim. Once granted, it sets CUDA_VISIBLE_DEVICES ( and the HIP / ROCR ones ) in this
// process, and returns the cards. Outside errand, with --no-queue, or in an allocation of somebody
// else's, it does nothing and returns an empty list.
//
// The one implementation is errand's: this runs `$ERRAND_PYTHON -m errand require …`, which waits,
// then prints what to set. Its include directory is `{errand_include}` in a runner's build line.
#pragma once

#include <cstdio>
#include <cstdlib>
#include <stdexcept>
#include <string>
#include <vector>

#if defined( _WIN32 )
#define ERRAND_POPEN _popen
#define ERRAND_PCLOSE _pclose
#else
#include <sys/wait.h>
#define ERRAND_POPEN popen
#define ERRAND_PCLOSE pclose
#endif

namespace errand {

/// What a run asks for. `gpu_ram` is what it takes on each of its cards: a size ( "40G" ) or a share
/// ( "75%" ); `gpus` without it takes cards whole. Empty or zero: not asked. That much in all, or,
/// with `extra`, that much more than the run was started with ( several such calls add up ).
struct Needs {
    int         gpus      = 0;
    std::string gpu_ram   = { };
    std::string ram       = { };
    int         cpus      = 0;
    bool        exclusive = false;
    bool        extra     = false;
};

/// Thrown when two runs that grow their claims wait for each other: errand stops the younger, and
/// runs it again, once, with what it requires up front. Let it go through ( or exit ).
struct Rerun : std::runtime_error {
    using std::runtime_error::runtime_error;
};

namespace detail {
    inline std::string env( const char *name ) {
        const char *v = std::getenv( name );
        return v ? v : "";
    }

    inline void set_env( const std::string &name, const std::string &value ) {
        #if defined( _WIN32 )
        _putenv_s( name.c_str(), value.c_str() );
        #else
        setenv( name.c_str(), value.c_str(), 1 );
        #endif
    }

    inline void unset_env( const std::string &name ) {
        #if defined( _WIN32 )
        _putenv_s( name.c_str(), "" );
        #else
        unsetenv( name.c_str() );
        #endif
    }

    inline std::string quoted( const std::string &s ) {
        #if defined( _WIN32 )
        return "\"" + s + "\"";
        #else
        std::string out = "'";
        for ( char c : s )
            out += c == '\'' ? std::string( "'\\''" ) : std::string( 1, c );
        return out + "'";
        #endif
    }

    inline std::vector<int> cards( const std::string &listed ) {
        std::vector<int> out;
        std::string num;
        for ( char c : listed + "," ) {
            if ( c == ',' ) {
                if ( ! num.empty() )
                    out.push_back( std::atoi( num.c_str() ) );
                num.clear();
            } else if ( c >= '0' && c <= '9' )
                num += c;
        }
        return out;
    }
}

/// Grow the run's claim to hold `needs` too, wait until it does, and return the cards it holds.
inline std::vector<int> require( const Needs &needs = { } ) {
    if ( detail::env( "ERRAND_CLAIM_FILE" ).empty() )
        return { };

    std::string python = detail::env( "ERRAND_PYTHON" );
    std::string cmd = detail::quoted( python.empty() ? "python3" : python ) + " -m errand require";
    if ( needs.gpus )
        cmd += " --gpus " + std::to_string( needs.gpus );
    if ( ! needs.gpu_ram.empty() )
        cmd += " --gpu-ram " + detail::quoted( needs.gpu_ram );
    if ( ! needs.ram.empty() )
        cmd += " --ram " + detail::quoted( needs.ram );
    if ( needs.cpus )
        cmd += " --cpus " + std::to_string( needs.cpus );
    if ( needs.exclusive )
        cmd += " --exclusive";
    if ( needs.extra )
        cmd += " --extra";

    // errand's sources first on the path, for the time of the call
    std::string src = detail::env( "ERRAND_SRC" ), path_before = detail::env( "PYTHONPATH" );
    bool had_path = std::getenv( "PYTHONPATH" ) != nullptr;
    if ( ! src.empty() ) {
        #if defined( _WIN32 )
        const char *sep = ";";
        #else
        const char *sep = ":";
        #endif
        detail::set_env( "PYTHONPATH", path_before.empty() ? src : src + sep + path_before );
    }

    std::string out;
    int status = -1;
    if ( FILE *pipe = ERRAND_POPEN( cmd.c_str(), "r" ) ) {
        char buf[ 512 ];
        while ( std::fgets( buf, sizeof buf, pipe ) )
            out += buf;
        status = ERRAND_PCLOSE( pipe );
        #if ! defined( _WIN32 )
        status = WIFEXITED( status ) ? WEXITSTATUS( status ) : -1;
        #endif
    }

    if ( ! src.empty() ) {
        if ( had_path )
            detail::set_env( "PYTHONPATH", path_before );
        else
            detail::unset_env( "PYTHONPATH" );
    }

    if ( status == 75 )
        throw Rerun( "errand::require: stopped, to run again with what it requires up front" );
    if ( status != 0 )
        throw std::runtime_error( "errand::require: `" + cmd + "` failed ( " + std::to_string( status ) + " )" );

    // NAME=value, one per line: set in this process
    std::vector<int> got;
    std::size_t start = 0;
    while ( start < out.size() ) {
        std::size_t end = out.find( '\n', start );
        std::string line = out.substr( start, end == std::string::npos ? std::string::npos : end - start );
        start = end == std::string::npos ? out.size() : end + 1;
        if ( ! line.empty() && line.back() == '\r' )
            line.pop_back();
        std::size_t eq = line.find( '=' );
        if ( eq == std::string::npos )
            continue;
        detail::set_env( line.substr( 0, eq ), line.substr( eq + 1 ) );
        if ( line.compare( 0, eq, "CUDA_VISIBLE_DEVICES" ) == 0 )
            got = detail::cards( line.substr( eq + 1 ) );
    }
    return got;
}

} // namespace errand

#undef ERRAND_POPEN
#undef ERRAND_PCLOSE
