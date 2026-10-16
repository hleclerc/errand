# Whatever you already build your tests with. errand does not compile anything
# itself: it runs this once, before any entry, and then expects the binaries.

CXXFLAGS ?= -std=c++17 -O2
LDLIBS   ?= -lCatch2Main -lCatch2

SOURCES  := $(wildcard test_*.cpp)
BINARIES := $(SOURCES:.cpp=)

all: $(BINARIES)

%: %.cpp geometry.h
	$(CXX) $(CXXFLAGS) $< $(LDLIBS) -o $@

clean:
	rm -f $(BINARIES)

.PHONY: all clean
