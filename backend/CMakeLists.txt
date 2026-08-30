cmake_minimum_required(VERSION 3.20)

project(ticketing_backend VERSION 0.1.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

option(TICKETING_FETCH_DROGON "Fetch the pinned Drogon release when it is not installed" OFF)

include(CTest)

find_package(Drogon 1.9 CONFIG QUIET)

if(NOT Drogon_FOUND)
    if(NOT TICKETING_FETCH_DROGON)
        message(FATAL_ERROR
            "Drogon was not found. Install Drogon >= 1.9 or configure with "
            "-DTICKETING_FETCH_DROGON=ON.")
    endif()

    include(FetchContent)
    set(BUILD_EXAMPLES OFF CACHE BOOL "" FORCE)
    set(BUILD_CTL OFF CACHE BOOL "" FORCE)
    set(BUILD_ORM ON CACHE BOOL "" FORCE)
    set(BUILD_POSTGRESQL ON CACHE BOOL "" FORCE)
    set(TICKETING_BUILD_TESTING "${BUILD_TESTING}")
    set(BUILD_TESTING OFF CACHE BOOL "" FORCE)
    FetchContent_Declare(
        drogon
        GIT_REPOSITORY https://github.com/drogonframework/drogon.git
        GIT_TAG v1.9.13
        GIT_SHALLOW TRUE
    )
    FetchContent_MakeAvailable(drogon)
    set(BUILD_TESTING "${TICKETING_BUILD_TESTING}" CACHE BOOL "" FORCE)
endif()

add_executable(ticketing_backend
    src/main.cpp
    src/controllers/HealthController.cpp
    src/controllers/EventController.cpp
    src/repositories/EventRepository.cpp
    src/services/EventService.cpp
    src/controllers/SessionController.cpp
    src/repositories/SessionRepository.cpp
    src/services/SessionService.cpp
    src/controllers/SeatController.cpp
    src/repositories/SeatRepository.cpp
    src/services/SeatService.cpp
)

target_include_directories(ticketing_backend PRIVATE src)
target_link_libraries(ticketing_backend PRIVATE Drogon::Drogon)

if(MSVC)
    target_compile_options(ticketing_backend PRIVATE /W4 /permissive-)
else()
    target_compile_options(ticketing_backend PRIVATE -Wall -Wextra -Wpedantic)
endif()

if(BUILD_TESTING)
    find_package(Python3 COMPONENTS Interpreter REQUIRED)
    add_test(
        NAME schema_contract
        COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/tests/schema_contract_test.py"
    )
    add_test(
        NAME read_api_source_contract
        COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/tests/read_api_source_contract_test.py"
    )
endif()
