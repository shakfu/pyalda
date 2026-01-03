# Alda Parser Library
# A standalone C parser for the Alda music language

cmake_minimum_required(VERSION 3.15)
project(alda-parser C)

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)

# Source files
set(ALDA_PARSER_SOURCES
    src/tokens.c
    src/error.c
    src/scanner.c
    src/ast.c
    src/parser.c
)

# Header files
set(ALDA_PARSER_HEADERS
    include/alda/alda.h
    include/alda/tokens.h
    include/alda/error.h
    include/alda/scanner.h
    include/alda/ast.h
    include/alda/parser.h
)

# Create the library
add_library(alda-parser STATIC ${ALDA_PARSER_SOURCES} ${ALDA_PARSER_HEADERS})

# Set include directories
target_include_directories(alda-parser
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
        $<INSTALL_INTERFACE:include>
)

# Compiler warnings
if(CMAKE_C_COMPILER_ID MATCHES "GNU|Clang")
    target_compile_options(alda-parser PRIVATE
        -Wall -Wextra -Wpedantic
    )
endif()

# Installation rules (optional)
install(TARGETS alda-parser
    ARCHIVE DESTINATION lib
    LIBRARY DESTINATION lib
)

install(DIRECTORY include/alda
    DESTINATION include
)
