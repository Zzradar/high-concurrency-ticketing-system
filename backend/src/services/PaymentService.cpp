#include "services/PaymentService.h"

#include <drogon/drogon.h>
#include <drogon/utils/Utilities.h>

#include <utility>

namespace ticketing
{
struct PaymentService::StartState
{
    std::string orderId;
    std::string userId;
    ExpirableOrderRow order;
    std::shared_ptr<PaymentProvider> provider;
    std::optional<PaymentAttempt> attempt;
    OrderRepository::TransactionPtr transaction;
    std::function<void(StartPaymentResult)> completion;
    bool createdAttempt{};
    bool responseLoading{};
    std::optional<std::string> clientSecret;
    bool finished{};
};

void PaymentService::startPayment(
    std::string orderId,
    std::string userId,
    std::function<void(StartPaymentResult)> completion) const
{
    if (orderId.empty() || userId.empty())
    {
        completion({StartPaymentOutcome::InvalidArgument, std::nullopt});
        return;
    }
    auto state = std::make_shared<StartState>();
    state->orderId = std::move(orderId);
    state->userId = std::move(userId);
    state->completion = std::move(completion);
    try
    {
        state->provider = PaymentProviderFactory::create();
    }
    catch (const std::exception &error)
    {
        LOG_ERROR << "Payment provider configuration failed: " << error.what();
        finish(state, {StartPaymentOutcome::InternalError, std::nullopt}, false);
        return;
    }
    beginTransaction(state);
}

void PaymentService::beginTransaction(
    const std::shared_ptr<StartState> &state) const
{
    auto client = drogon::app().getDbClient("default");
    client->newTransactionAsync(
        [this, state](const OrderRepository::TransactionPtr &transaction) {
            if (!transaction)
            {
                finish(state, {StartPaymentOutcome::InternalError, std::nullopt}, false);
                return;
            }
            state->transaction = transaction;
            lockOrder(state);
        });
}

void PaymentService::lockOrder(const std::shared_ptr<StartState> &state) const
{
    orderRepository_.lockOrderForUser(
        state->transaction, state->orderId, state->userId,
        [this, state](std::optional<ExpirableOrderRow> order) {
            inspectOrder(state, std::move(order));
        },
        [state] { finish(state, {StartPaymentOutcome::InternalError, std::nullopt}); });
}

void PaymentService::inspectOrder(
    const std::shared_ptr<StartState> &state,
    std::optional<ExpirableOrderRow> order) const
{
    if (!order)
    {
        finish(state, {StartPaymentOutcome::NotFound, std::nullopt});
        return;
    }
    state->order = std::move(*order);
    if (state->order.status == "PAID")
    {
        state->transaction->rollback();
        state->transaction.reset();
        loadAcceptedAttempt(state);
        return;
    }
    if (state->order.status == "EXPIRED")
    {
        finish(state, {StartPaymentOutcome::OrderExpired, std::nullopt});
        return;
    }
    if (state->order.status != "PENDING_PAYMENT")
    {
        finish(state, {StartPaymentOutcome::NotPayable, std::nullopt});
        return;
    }
    lockProcessingAttempt(state);
}

void PaymentService::lockProcessingAttempt(
    const std::shared_ptr<StartState> &state) const
{
    paymentRepository_.lockProcessingForOrder(
        state->transaction, state->orderId,
        [this, state](std::optional<LockedPaymentAttempt> attempt) {
            inspectProcessingAttempt(state, std::move(attempt));
        },
        [state] { finish(state, {StartPaymentOutcome::InternalError, std::nullopt}); });
}

void PaymentService::inspectProcessingAttempt(
    const std::shared_ptr<StartState> &state,
    std::optional<LockedPaymentAttempt> attempt) const
{
    if (attempt && !attempt->deadlinePassed && attempt->startedBeforeOrderExpiry)
    {
        state->attempt = std::move(attempt->value);
        state->transaction->rollback();
        state->transaction.reset();
        startProvider(state, StartPaymentOutcome::ReusedProcessing);
        return;
    }
    if (attempt)
    {
        state->attempt = std::move(attempt->value);
        timeOutAttempt(state);
        return;
    }
    if (state->order.expired)
    {
        state->transaction->rollback();
        state->transaction.reset();
        expireOnline(state);
        return;
    }
    createAttempt(state);
}

void PaymentService::timeOutAttempt(
    const std::shared_ptr<StartState> &state) const
{
    paymentRepository_.markTimedOut(
        state->transaction, state->attempt->id,
        [this, state](std::size_t updated) {
            if (updated != 1)
            {
                finish(state, {StartPaymentOutcome::InternalError, std::nullopt});
                return;
            }
            state->attempt.reset();
            if (state->order.expired)
            {
                auto transaction = state->transaction;
                transaction->setCommitCallback([this, state](bool committed) {
                    if (!committed)
                    {
                        finish(state, {StartPaymentOutcome::InternalError, std::nullopt}, false);
                        return;
                    }
                    expireOnline(state);
                });
                state->transaction.reset();
                transaction.reset();
                return;
            }
            createAttempt(state);
        },
        [state] { finish(state, {StartPaymentOutcome::InternalError, std::nullopt}); });
}

void PaymentService::createAttempt(const std::shared_ptr<StartState> &state) const
{
    const auto attemptId = "PAY-" + drogon::utils::getUuid(true);
    const auto delay = state->provider->scheduledDelaySeconds().value_or(0.0);
    paymentRepository_.createAttempt(
        state->transaction, attemptId, state->orderId,
        delay, state->provider->processingGraceSeconds(), state->provider->name(),
        [this, state](PaymentAttempt attempt) {
            state->attempt = std::move(attempt);
            state->createdAttempt = true;
            commitAttempt(state);
        },
        [state] { finish(state, {StartPaymentOutcome::InternalError, std::nullopt}); });
}

void PaymentService::commitAttempt(const std::shared_ptr<StartState> &state) const
{
    auto transaction = state->transaction;
    transaction->setCommitCallback([this, state](bool committed) {
        if (!committed)
        {
            finish(state, {StartPaymentOutcome::InternalError, std::nullopt}, false);
            return;
        }
        startProvider(state, StartPaymentOutcome::StartedNew);
    });
    state->transaction.reset();
    transaction.reset();
}

void PaymentService::expireOnline(const std::shared_ptr<StartState> &state) const
{
    lifecycleService_.expireForWorker(
        state->orderId,
        [state](OrderLifecycleOutcome outcome) {
            finish(state,
                   {outcome == OrderLifecycleOutcome::Failed
                        ? StartPaymentOutcome::InternalError
                        : StartPaymentOutcome::OrderExpired,
                    std::nullopt},
                   false);
        });
}

void PaymentService::loadResponse(const std::shared_ptr<StartState> &state,
                                  StartPaymentOutcome outcome) const
{
    if (state->responseLoading || state->finished) return;
    state->responseLoading = true;
    auto client = drogon::app().getDbClient("default");
    orderRepository_.findByIdForUser(
        client, state->orderId, state->userId,
        [state, outcome](std::optional<TicketOrder> order) {
            if (!order)
            {
                finish(state, {StartPaymentOutcome::InternalError, std::nullopt}, false);
                return;
            }
            finish(state,
                   {outcome,
                    PaymentStartResult{
                                       .disposition =
                                           outcome == StartPaymentOutcome::StartedNew
                                               ? "STARTED_NEW"
                                               : outcome == StartPaymentOutcome::ReusedProcessing
                                                     ? "REUSED_PROCESSING"
                                                     : "ALREADY_PAID",
                                       .order = std::move(*order),
                                       .paymentAttempt = state->attempt,
                                       .paymentActionProvider = state->clientSecret
                                                                    ? std::optional<std::string>{state->provider->name()}
                                                                    : std::nullopt,
                                       .paymentActionClientSecret = state->clientSecret}},
                   false);
        },
        [state] { finish(state, {StartPaymentOutcome::InternalError, std::nullopt}, false); });
}

void PaymentService::loadAcceptedAttempt(
    const std::shared_ptr<StartState> &state) const
{
    auto client = drogon::app().getDbClient("default");
    paymentRepository_.findLastAcceptedForOrder(
        client, state->orderId,
        [this, state](std::optional<PaymentAttempt> attempt) {
            state->attempt = std::move(attempt);
            loadResponse(state, StartPaymentOutcome::AlreadyPaid);
        },
        [state] { finish(state, {StartPaymentOutcome::InternalError, std::nullopt}, false); });
}

void PaymentService::startProvider(const std::shared_ptr<StartState> &state,
                                   StartPaymentOutcome outcome) const
{
    const CreatePaymentRequest request{.attemptId = state->attempt->id,
                                       .orderId = state->orderId,
                                       .amount = state->order.totalAmount,
                                       .currency = PaymentProviderFactory::configuredCurrency()};
    auto completion = [this, state, outcome](ProviderResult<ProviderPayment> result) {
        handleProviderResult(state, outcome, std::move(result));
    };
    if (state->attempt->providerPaymentId)
    {
        RetrievePaymentRequest retrieve;
        static_cast<CreatePaymentRequest &>(retrieve) = request;
        retrieve.providerPaymentId = *state->attempt->providerPaymentId;
        state->provider->retrievePayment(std::move(retrieve), std::move(completion));
    }
    else state->provider->createOrRecoverPayment(request, std::move(completion));
}

void PaymentService::handleProviderResult(
    const std::shared_ptr<StartState> &state, StartPaymentOutcome outcome,
    ProviderResult<ProviderPayment> result) const
{
    auto client = drogon::app().getDbClient("default");
    if (result.outcome != ProviderTransportOutcome::Success || !result.value)
    {
        paymentRepository_.schedulePaymentRetry(
            client, state->attempt->id,
            [this, state, outcome] { loadResponse(state, outcome); },
            [state] { finish(state, {StartPaymentOutcome::InternalError, std::nullopt}, false); });
        return;
    }
    const auto payment = std::move(*result.value);
    if (payment.terminal)
    {
        PaymentTerminalSnapshot snapshot{
            .provider = payment.provider, .providerPaymentId = payment.providerPaymentId,
            .providerStatus = payment.providerStatus, .amount = state->order.totalAmount,
            .succeeded = payment.mappedState == ProviderPaymentState::Succeeded,
            .failureReason = payment.failureCode.value_or("PROVIDER_PAYMENT_FAILED").substr(0, 200)};
        lifecycleService_.completeProviderPayment(
            state->orderId, state->attempt->id, std::move(snapshot),
            [this, state, outcome](OrderLifecycleOutcome lifecycleOutcome) {
                if (lifecycleOutcome == OrderLifecycleOutcome::Failed)
                {
                    LOG_ERROR << "Provider payment lifecycle transaction failed";
                    if (!state->finished)
                        finish(state, {StartPaymentOutcome::InternalError, std::nullopt}, false);
                    return;
                }
                if (!state->finished)
                    paymentRepository_.findByIdForUser(
                        drogon::app().getDbClient("default"), state->attempt->id, state->userId,
                        [this, state, outcome](std::optional<PaymentAttempt> attempt) {
                            state->attempt = std::move(attempt);
                            state->clientSecret.reset();
                            loadResponse(state, outcome);
                        }, [state] { finish(state, {StartPaymentOutcome::InternalError, std::nullopt}, false); });
            });
        return;
    }
    if (payment.clientSecret) state->clientSecret = payment.clientSecret;
    paymentRepository_.recordProviderPayment(
        client, state->attempt->id, payment.providerPaymentId,
        payment.providerStatus, "",
        [this, state, outcome, payment](std::size_t updated) {
            if (updated != 1)
            {
                LOG_ERROR << "Provider payment collision for attempt " << state->attempt->id;
                if (!state->finished)
                    finish(state, {StartPaymentOutcome::InternalError, std::nullopt}, false);
                return;
            }
            state->attempt->providerPaymentId = payment.providerPaymentId;
            state->attempt->providerStatus = payment.providerStatus;
            loadResponse(state, outcome);
        },
        [state] {
            if (!state->finished)
                finish(state, {StartPaymentOutcome::InternalError, std::nullopt}, false);
        });
}

void PaymentService::getPaymentAttempt(
    std::string attemptId,
    std::string userId,
    std::function<void(GetPaymentAttemptResult)> completion) const
{
    if (attemptId.empty() || userId.empty())
    {
        completion({GetPaymentAttemptOutcome::InvalidArgument, std::nullopt});
        return;
    }
    auto completionPtr = std::make_shared<std::function<void(GetPaymentAttemptResult)>>(std::move(completion));
    paymentRepository_.findByIdForUser(
        drogon::app().getDbClient("default"), attemptId, userId,
        [completionPtr](std::optional<PaymentAttempt> attempt) {
            (*completionPtr)({attempt ? GetPaymentAttemptOutcome::Found
                                      : GetPaymentAttemptOutcome::NotFound,
                              std::move(attempt)});
        },
        [completionPtr] { (*completionPtr)({GetPaymentAttemptOutcome::InternalError, std::nullopt}); });
}

void PaymentService::finish(const std::shared_ptr<StartState> &state,
                            StartPaymentResult result,
                            bool rollback)
{
    if (state->finished) return;
    state->finished = true;
    if (rollback && state->transaction) state->transaction->rollback();
    state->transaction.reset();
    auto completion = std::move(state->completion);
    completion(std::move(result));
}
}  // namespace ticketing
