#pragma once

#include "dto/TicketDtos.h"
#include "repositories/OrderRepository.h"
#include "repositories/PaymentRepository.h"
#include "services/OrderLifecycleService.h"
#include "services/PaymentSimulation.h"

#include <functional>
#include <memory>
#include <optional>
#include <string>

namespace ticketing
{
enum class StartPaymentOutcome
{
    Started,
    AlreadyPaid,
    InvalidArgument,
    NotFound,
    NotPayable,
    OrderExpired,
    InternalError,
};

struct StartPaymentResult
{
    StartPaymentOutcome outcome{StartPaymentOutcome::InternalError};
    std::optional<PaymentStartResult> value;
};

enum class GetPaymentAttemptOutcome
{
    Found,
    InvalidArgument,
    NotFound,
    InternalError,
};

struct GetPaymentAttemptResult
{
    GetPaymentAttemptOutcome outcome{GetPaymentAttemptOutcome::InternalError};
    std::optional<PaymentAttempt> value;
};

class PaymentService
{
  public:
    void startPayment(std::string orderId,
                      std::string userId,
                      std::function<void(StartPaymentResult)> completion) const;
    void getPaymentAttempt(
        std::string attemptId,
        std::string userId,
        std::function<void(GetPaymentAttemptResult)> completion) const;

  private:
    struct StartState;
    void beginTransaction(const std::shared_ptr<StartState> &state) const;
    void lockOrder(const std::shared_ptr<StartState> &state) const;
    void inspectOrder(const std::shared_ptr<StartState> &state,
                      std::optional<ExpirableOrderRow> order) const;
    void lockProcessingAttempt(const std::shared_ptr<StartState> &state) const;
    void inspectProcessingAttempt(
        const std::shared_ptr<StartState> &state,
        std::optional<LockedPaymentAttempt> attempt) const;
    void timeOutAttempt(const std::shared_ptr<StartState> &state) const;
    void createAttempt(const std::shared_ptr<StartState> &state) const;
    void commitAttempt(const std::shared_ptr<StartState> &state) const;
    void expireOnline(const std::shared_ptr<StartState> &state) const;
    void loadResponse(const std::shared_ptr<StartState> &state,
                      StartPaymentOutcome outcome) const;
    void loadAcceptedAttempt(const std::shared_ptr<StartState> &state) const;
    static void scheduleCompletion(const std::shared_ptr<StartState> &state);
    static void finish(const std::shared_ptr<StartState> &state,
                       StartPaymentResult result,
                       bool rollback = true);

    OrderRepository orderRepository_;
    PaymentRepository paymentRepository_;
    OrderLifecycleService lifecycleService_;
};
}  // namespace ticketing
