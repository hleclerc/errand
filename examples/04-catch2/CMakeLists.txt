# Whatever you already build with. errand runs it, during the preparation; it compiles nothing itself.
cmake_minimum_required( VERSION 3.20 )
project( stats CXX )

set( CMAKE_CXX_STANDARD 17 )
set( CMAKE_CXX_STANDARD_REQUIRED ON )

# An installed Catch2 v3 when there is one, else fetched once into the build directory.
find_package( Catch2 3 QUIET )
if( NOT Catch2_FOUND )
    include( FetchContent )
    FetchContent_Declare( Catch2
        URL https://github.com/catchorg/Catch2/archive/refs/tags/v3.7.1.tar.gz
        DOWNLOAD_EXTRACT_TIMESTAMP TRUE )
    FetchContent_MakeAvailable( Catch2 )
endif()

# One binary per tests/test_*.cpp, named after it: what `binary = "{build_dir}/{stem}"` finds.
file( GLOB SUITES CONFIGURE_DEPENDS tests/test_*.cpp )
foreach( source ${SUITES} )
    get_filename_component( name ${source} NAME_WE )
    add_executable( ${name} ${source} )
    target_include_directories( ${name} PRIVATE include )
    target_link_libraries( ${name} PRIVATE Catch2::Catch2WithMain )
endforeach()
