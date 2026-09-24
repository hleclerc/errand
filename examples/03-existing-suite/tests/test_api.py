# Ordinary pytest. Untouched, and it stays runnable with `pytest` alone --
# errand collects it through the Pytest provider, it does not convert it.
import pytest

from geometry import area, perimeter


def test_area( ):
    assert area( 3, 4 ) == 12


def test_perimeter( ):
    assert perimeter( 3, 4 ) == 14


@pytest.mark.parametrize( "w,h", [ ( 1, 1 ), ( 2, 5 ), ( 10, 10 ) ] )
def test_area_is_positive( w, h ):
    assert area( w, h ) > 0


@pytest.mark.slow
def test_big( ):
    assert area( 10 ** 6, 10 ** 6 ) == 10 ** 12
