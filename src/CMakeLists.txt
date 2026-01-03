# _libremidi nanobind extension module
nanobind_add_module(_libremidi aldakit/_libremidi.cpp)
target_link_libraries(_libremidi PUBLIC libremidi)

set_target_properties(_libremidi PROPERTIES
    RUNTIME_OUTPUT_DIRECTORY_RELEASE "${CMAKE_SOURCE_DIR}/src/aldakit"
    ARCHIVE_OUTPUT_DIRECTORY_RELEASE "${CMAKE_SOURCE_DIR}/src/aldakit"
    LIBRARY_OUTPUT_DIRECTORY_RELEASE "${CMAKE_SOURCE_DIR}/src/aldakit"
)

# _alda_parser nanobind extension module
nanobind_add_module(_alda_parser aldakit/_alda_parser.cpp)
target_link_libraries(_alda_parser PUBLIC alda-parser)
target_include_directories(_alda_parser PRIVATE
    ${CMAKE_SOURCE_DIR}/thirdparty/alda-parser/include
)

set_target_properties(_alda_parser PROPERTIES
    RUNTIME_OUTPUT_DIRECTORY_RELEASE "${CMAKE_SOURCE_DIR}/src/aldakit"
    ARCHIVE_OUTPUT_DIRECTORY_RELEASE "${CMAKE_SOURCE_DIR}/src/aldakit"
    LIBRARY_OUTPUT_DIRECTORY_RELEASE "${CMAKE_SOURCE_DIR}/src/aldakit"
)

# Install directive for scikit-build-core
install(TARGETS _libremidi LIBRARY DESTINATION aldakit)
install(TARGETS _alda_parser LIBRARY DESTINATION aldakit)
