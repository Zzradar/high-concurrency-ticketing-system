cmake_minimum_required(VERSION 3.20)

project(ticketing_backend VERSION 0.1.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

option(TICKETING_FETCH_DROGON "Fetch the pinned Drogon release when it is not installed" OFF)

include(CTest)

find_package(OpenSSL REQUIRED)
find_package(Threads REQUIRED)
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
    src/observability/Phase14Metrics.cpp
    src/observability/PerformanceMetrics.cpp
    src/controllers/HealthController.cpp
    src/controllers/EventController.cpp
    src/repositories/EventRepository.cpp
    src/repositories/SalesWindowRepository.cpp
    src/services/EventService.cpp
    src/controllers/SessionController.cpp
    src/repositories/SessionRepository.cpp
    src/services/SessionService.cpp
    src/controllers/SeatController.cpp
    src/repositories/SeatRepository.cpp
    src/services/SeatService.cpp
    src/services/SeatDisplayStatus.cpp
    src/services/SeatMapComputeExecutor.cpp
    src/controllers/ReservationController.cpp
    src/repositories/ReservationRepository.cpp
    src/services/ReservationService.cpp
    src/controllers/RefundController.cpp
    src/repositories/RefundRepository.cpp
    src/services/RefundService.cpp
    src/services/RefundLifecycleService.cpp
    src/controllers/OrderController.cpp
    src/controllers/PaymentController.cpp
    src/controllers/StripeWebhookController.cpp
    src/controllers/NotificationController.cpp
    src/repositories/OrderRepository.cpp
    src/repositories/PaymentRepository.cpp
    src/repositories/ProviderEventRepository.cpp
    src/repositories/NotificationRepository.cpp
    src/services/OrderService.cpp
    src/services/OrderLifecycleService.cpp
    src/services/PaymentSimulation.cpp
    src/payments/SimulationPaymentProvider.cpp
    src/payments/StripeConfig.cpp
    src/payments/StripePaymentProvider.cpp
    src/payments/StripeWebhookVerifier.cpp
    src/services/PaymentService.cpp
    src/services/PaymentReconciliationService.cpp
    src/services/NotificationService.cpp
    src/services/OrderExpiryService.cpp
    src/workers/OrderExpiryWorker.cpp
    src/workers/PaymentReconciliationWorker.cpp
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
    add_test(NAME phase12_source_contract COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/tests/phase12_source_contract_test.py")
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
        NAME seat_split_source_contract
        COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/tests/seat_split_source_contract_test.py"
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
    add_test(
        NAME phase11_payment_provider_source_contract
        COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/tests/phase11_payment_provider_source_contract_test.py"
    )
    add_test(
        NAME phase11_schema_contract
        COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/tests/phase11_schema_contract_test.py"
    )
    add_executable(stripe_config_unit tests/stripe_config_unit.cpp src/payments/StripeConfig.cpp)
    target_include_directories(stripe_config_unit PRIVATE src)
    add_test(NAME stripe_config_unit COMMAND stripe_config_unit)
    add_executable(stripe_webhook_verifier_unit
        tests/stripe_webhook_verifier_unit.cpp
        src/payments/StripeWebhookVerifier.cpp
        src/security/Crypto.cpp
    )
    target_include_directories(stripe_webhook_verifier_unit PRIVATE src)
    target_link_libraries(stripe_webhook_verifier_unit PRIVATE OpenSSL::Crypto)
    add_test(NAME stripe_webhook_verifier_unit COMMAND stripe_webhook_verifier_unit)
    add_executable(password_hash_executor_unit
        tests/password_hash_executor_unit.cpp
        src/security/PasswordHashExecutor.cpp
        src/security/PasswordHasher.cpp
    )
    target_include_directories(password_hash_executor_unit PRIVATE src "${ARGON2_INCLUDE_DIR}")
    target_link_libraries(password_hash_executor_unit PRIVATE
        "${ARGON2_LIBRARY}" OpenSSL::Crypto Threads::Threads)
    add_test(NAME password_hash_executor_unit COMMAND password_hash_executor_unit)
    add_executable(seat_map_compute_executor_unit
        tests/seat_map_compute_executor_unit.cpp
        src/services/SeatMapComputeExecutor.cpp
    )
    target_include_directories(seat_map_compute_executor_unit PRIVATE src)
    target_link_libraries(seat_map_compute_executor_unit PRIVATE Threads::Threads)
    add_test(NAME seat_map_compute_executor_unit COMMAND seat_map_compute_executor_unit)
    set_tests_properties(seat_map_compute_executor_unit PROPERTIES TIMEOUT 15)
    add_executable(seat_display_status_unit
        tests/seat_display_status_unit.cpp
        src/services/SeatDisplayStatus.cpp
    )
    target_include_directories(seat_display_status_unit PRIVATE src)
    add_test(NAME seat_display_status_unit COMMAND seat_display_status_unit)
endif()

option(TICKETING_PHASE12_EXTERNAL_TESTS "Register tests requiring the isolated Phase12 Docker environment" OFF)
if(BUILD_TESTING AND TICKETING_PHASE12_EXTERNAL_TESTS)
    add_test(NAME phase12_migration COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/tests/phase12_migration_test.py")
    add_test(NAME phase12_buyer_refund COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/tests/phase12_buyer_refund_integration_test.py")
    set_tests_properties(phase12_migration phase12_buyer_refund PROPERTIES RUN_SERIAL TRUE LABELS integration)
endif()

if(BUILD_TESTING)
    add_executable(phase14_observation_unit tests/phase14_observation_unit.cpp)
    target_include_directories(phase14_observation_unit PRIVATE src)
    target_link_libraries(phase14_observation_unit PRIVATE Threads::Threads)
    add_test(NAME phase14_observation_unit COMMAND phase14_observation_unit)
    add_test(NAME phase14_metrics_source_contract COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/tests/phase14_metrics_source_contract_test.py")
endif()

option(TICKETING_PHASE16_EXTERNAL_TESTS "Register tests requiring the isolated Phase16 PostgreSQL/Redis environment" OFF)
if(BUILD_TESTING AND TICKETING_PHASE16_EXTERNAL_TESTS)
    add_test(NAME phase16_migration COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/tests/phase16_migration_test.py")
    set_tests_properties(phase16_migration PROPERTIES RUN_SERIAL TRUE LABELS integration)
endif()

# Compile Lua source into the binary; no runtime working-directory dependency.
file(MAKE_DIRECTORY "${CMAKE_CURRENT_BINARY_DIR}/generated/availability")
set(PHASE16_SCRIPT_HEADER "${CMAKE_CURRENT_BINARY_DIR}/generated/availability/AvailabilityScripts.h")
file(WRITE "${PHASE16_SCRIPT_HEADER}" "#pragma once\n#include <string_view>\nnamespace ticketing::availability_scripts {\n")
foreach(script common init apply expire read hold)
    set(script_path "${CMAKE_CURRENT_SOURCE_DIR}/src/availability/${script}.lua")
    set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS "${script_path}")
    file(READ "${script_path}" script_text)
    file(APPEND "${PHASE16_SCRIPT_HEADER}" "inline constexpr std::string_view ${script} = R\"p16lua(${script_text})p16lua\";\n")
endforeach()
file(APPEND "${PHASE16_SCRIPT_HEADER}" "}\n")
target_include_directories(ticketing_backend PRIVATE "${CMAKE_CURRENT_BINARY_DIR}/generated")
target_sources(ticketing_backend PRIVATE
    src/services/CheckoutOwnershipCache.cpp
    src/services/SeatAvailabilityReadModel.cpp
    src/workers/SeatAvailabilityProjectionWorker.cpp)
if(BUILD_TESTING AND TICKETING_PHASE16_EXTERNAL_TESTS)
    add_test(NAME phase16_read_model COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/tests/phase16_read_model_test.py")
    set_tests_properties(phase16_read_model PROPERTIES RUN_SERIAL TRUE LABELS integration)
endif()

if(BUILD_TESTING)
    add_test(NAME phase16_source_contract COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/tests/phase16_source_contract_test.py")
endif()
if(BUILD_TESTING AND TICKETING_PHASE16_EXTERNAL_TESTS)
    add_test(NAME phase16_api COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/tests/phase16_api_test.py")
    set_tests_properties(phase16_api PROPERTIES RUN_SERIAL TRUE LABELS integration)
endif()

if(BUILD_TESTING)
    add_test(NAME phase15_source_contract COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/tests/phase15_source_contract_test.py")
endif()
option(TICKETING_PHASE15_EXTERNAL_TESTS "Register isolated Phase15 database/HTTP gates" OFF)
if(BUILD_TESTING AND TICKETING_PHASE15_EXTERNAL_TESTS)
    add_test(NAME phase15_migration COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/tests/phase15_migration_test.py")
    add_test(NAME phase15_read_api COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/tests/phase15_read_api_test.py")
    set_tests_properties(phase15_migration phase15_read_api PROPERTIES RUN_SERIAL TRUE LABELS integration)
endif()
