cmake_minimum_required(VERSION 3.20)

project(ticketing_backend VERSION 0.1.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

option(TICKETING_FETCH_DROGON "Fetch the pinned Drogon release when it is not installed" OFF)

include(CTest)

find_package(OpenSSL REQUIRED)
find_path(ARGON2_INCLUDE_DIR NAMES argon2.h REQUIRED)
find_library(ARGON2_LIBRARY NAMES argon2 REQUIRED)

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
    set(BUILD_REDIS ON CACHE BOOL "" FORCE)
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
    src/observability/PerformanceMetrics.cpp
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
    src/controllers/ReservationController.cpp
    src/repositories/ReservationRepository.cpp
    src/services/ReservationService.cpp
    src/controllers/OrderController.cpp
    src/controllers/PaymentController.cpp
    src/controllers/NotificationController.cpp
    src/repositories/OrderRepository.cpp
    src/repositories/PaymentRepository.cpp
    src/repositories/NotificationRepository.cpp
    src/services/OrderService.cpp
    src/services/OrderLifecycleService.cpp
    src/services/PaymentSimulation.cpp
    src/services/PaymentService.cpp
    src/services/NotificationService.cpp
    src/services/OrderExpiryService.cpp
    src/workers/OrderExpiryWorker.cpp
    src/controllers/CheckoutSessionController.cpp
    src/repositories/CheckoutSessionRepository.cpp
    src/services/CheckoutSessionService.cpp
    src/services/SeatHoldService.cpp
    src/security/AuthConfig.cpp
    src/security/Crypto.cpp
    src/security/PasswordHasher.cpp
    src/security/PasswordHashExecutor.cpp
    src/repositories/UserRepository.cpp
    src/repositories/UserSessionRepository.cpp
    src/services/AuthSessionCache.cpp
    src/services/AuthSessionService.cpp
    src/security/AuthHttp.cpp
    src/services/LoginRateLimiter.cpp
    src/services/AuthService.cpp
    src/filters/AuthFilter.cpp
    src/controllers/AuthController.cpp
)

target_include_directories(ticketing_backend PRIVATE src "${ARGON2_INCLUDE_DIR}")
target_link_libraries(ticketing_backend PRIVATE Drogon::Drogon OpenSSL::Crypto "${ARGON2_LIBRARY}")

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
    add_test(
        NAME phase3_schema_contract
        COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/tests/phase3_schema_contract_test.py"
    )
    add_test(
        NAME reservation_source_contract
        COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/tests/reservation_source_contract_test.py"
    )
    add_test(
        NAME order_source_contract
        COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/tests/order_source_contract_test.py"
    )
    add_test(
        NAME order_expiry_source_contract
        COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/tests/order_expiry_source_contract_test.py"
    )
    add_test(
        NAME phase5_schema_contract
        COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/tests/phase5_schema_contract_test.py"
    )
    add_test(
        NAME checkout_session_source_contract
        COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/tests/checkout_session_source_contract_test.py"
    )
    add_test(
        NAME seat_hold_source_contract
        COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/tests/seat_hold_source_contract_test.py"
    )
    add_test(
        NAME phase8_schema_contract
        COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/tests/phase8_schema_contract_test.py"
    )
    add_test(
        NAME order_lifecycle_source_contract
        COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/tests/order_lifecycle_source_contract_test.py"
    )
    add_test(
        NAME payment_source_contract
        COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/tests/payment_source_contract_test.py"
    )
    add_test(
        NAME phase9_auth_schema_contract
        COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/tests/phase9_auth_schema_contract_test.py"
    )
    add_test(
        NAME auth_core_source_contract
        COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/tests/auth_core_source_contract_test.py"
    )
    add_test(
        NAME auth_http_source_contract
        COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/tests/auth_http_source_contract_test.py"
    )
    add_test(
        NAME authenticated_routes_source_contract
        COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/tests/authenticated_routes_source_contract_test.py"
    )
    add_test(
        NAME order_recovery_source_contract
        COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/tests/order_recovery_source_contract_test.py"
    )
    add_test(
        NAME operation_disposition_source_contract
        COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/tests/operation_disposition_source_contract_test.py"
    )
    add_test(
        NAME performance_metrics_source_contract
        COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/tests/performance_metrics_source_contract_test.py"
    )
endif()
