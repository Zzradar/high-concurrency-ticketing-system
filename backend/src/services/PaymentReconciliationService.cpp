#include "services/PaymentReconciliationService.h"
#include "observability/PerformanceMetrics.h"

#include <drogon/drogon.h>
#include <drogon/utils/Utilities.h>

#include <algorithm>
#include <optional>
#include <utility>

namespace ticketing
{
struct PaymentReconciliationService::RunState
{
    std::size_t batchSize{};
    double maxBackoffSeconds{};
    std::size_t pending{};
    PaymentReconciliationSummary summary;
    Completion completion;
    bool claimsComplete{};
    std::string leaseToken{drogon::utils::getUuid(true)};
};

void PaymentReconciliationService::runOnce(
    std::size_t batchSize, double maxBackoffSeconds, Completion completion) const
{
    auto state = std::make_shared<RunState>();
    state->batchSize = batchSize;
    state->maxBackoffSeconds = maxBackoffSeconds;
    state->completion = std::move(completion);
    processInbox(state);
}

void PaymentReconciliationService::processInbox(
    const std::shared_ptr<RunState> &state) const
{
    auto client = drogon::app().getDbClient("default");
    client->execSqlAsync(R"SQL(
        WITH claimed AS (
            SELECT id, provider, object_kind, provider_object_id, local_reference_id
            FROM payment_provider_events
            WHERE status = 'PENDING' AND next_retry_at <= clock_timestamp()
            ORDER BY received_at
            FOR UPDATE SKIP LOCKED
            LIMIT $1
        ), wake_payments AS (
            UPDATE payment_attempts AS attempt
            SET provider_payment_id = COALESCE(attempt.provider_payment_id, claimed.provider_object_id),
                next_reconcile_at = CASE WHEN attempt.status IN ('PROCESSING','TIMED_OUT')
                                         THEN clock_timestamp() ELSE NULL END
            FROM claimed
            WHERE claimed.object_kind = 'PAYMENT'
              AND claimed.local_reference_id = attempt.id
              AND claimed.provider = attempt.provider
              AND (attempt.provider_payment_id IS NULL
                   OR attempt.provider_payment_id = claimed.provider_object_id)
            RETURNING claimed.id
        ), wake_refunds AS (
            UPDATE refunds AS refund
            SET provider_refund_id = COALESCE(refund.provider_refund_id, claimed.provider_object_id),
                next_reconcile_at = CASE WHEN refund.status = 'PROCESSING'
                                         THEN clock_timestamp() ELSE NULL END
            FROM claimed
            WHERE claimed.object_kind = 'REFUND'
              AND claimed.local_reference_id = refund.id
              AND claimed.provider = refund.provider
              AND (refund.provider_refund_id IS NULL
                   OR refund.provider_refund_id = claimed.provider_object_id)
            RETURNING claimed.id
        )
        UPDATE payment_provider_events AS event
        SET status = 'PROCESSED', processed_at = clock_timestamp(), last_error = NULL
        FROM claimed
        WHERE event.id = claimed.id
          AND (event.provider_object_id IS NULL
               OR event.id IN (SELECT id FROM wake_payments)
               OR event.id IN (SELECT id FROM wake_refunds))
    )SQL",
        [this, state](const drogon::orm::Result &) { claimPayments(state); },
        [state](const drogon::orm::DrogonDbException &error) {
            LOG_ERROR << "Provider inbox processing failed: " << error.base().what();
            state->summary.failed++;
            auto completion = std::move(state->completion);
            completion(state->summary);
        }, state->batchSize);
}

void PaymentReconciliationService::claimPayments(
    const std::shared_ptr<RunState> &state) const
{
    auto client = drogon::app().getDbClient("default");
    client->execSqlAsync(R"SQL(
        WITH claimed AS (
            SELECT attempt.id,
                   CASE WHEN attempt.provider_status IN ('succeeded','canceled')
                        THEN 'provider_terminal_local_nonterminal'
                        WHEN attempt.next_reconcile_at IS NULL THEN 'missing_schedule'
                        WHEN attempt.reconciliation_lease_until IS NOT NULL THEN 'lease_expired'
                        ELSE 'retry_due' END AS recovery_reason
            FROM payment_attempts AS attempt
            WHERE attempt.provider <> 'simulation'
              AND attempt.status IN ('PROCESSING', 'TIMED_OUT')
              AND (attempt.reconciliation_lease_until IS NULL
                   OR attempt.reconciliation_lease_until <= clock_timestamp())
              AND (attempt.provider_status IN ('succeeded','canceled')
                   OR attempt.next_reconcile_at IS NULL
                   OR attempt.next_reconcile_at <= clock_timestamp())
            ORDER BY (attempt.provider_status IN ('succeeded','canceled')) DESC NULLS LAST,
                     attempt.next_reconcile_at NULLS FIRST, attempt.id
            FOR UPDATE SKIP LOCKED
            LIMIT $1
        ), leased AS (
            UPDATE payment_attempts AS attempt
            SET provider_retry_count = provider_retry_count + 1,
                reconciliation_lease_token = $3,
                reconciliation_lease_until = clock_timestamp() + INTERVAL '30 seconds',
                next_reconcile_at = clock_timestamp() + LEAST($2, power(2, LEAST(provider_retry_count, 5))) * INTERVAL '1 second'
            FROM claimed WHERE attempt.id = claimed.id
            RETURNING attempt.*, claimed.recovery_reason
        )
        SELECT leased.id, leased.order_id, leased.provider, leased.provider_payment_id,
               ticket_order.total_amount, leased.recovery_reason
        FROM leased JOIN orders AS ticket_order ON ticket_order.id = leased.order_id
    )SQL",
        [this, state](const drogon::orm::Result &rows) {
            state->pending += rows.size();
            state->summary.scanned += rows.size();
            for (const auto &row : rows) processPayment(state, row);
            claimRefunds(state);
        },
        [state](const drogon::orm::DrogonDbException &error) {
            LOG_ERROR << "Payment reconciliation claim failed: " << error.base().what();
            state->summary.failed++;
            state->claimsComplete = true;
            finishOne(state);
        }, state->batchSize, state->maxBackoffSeconds, state->leaseToken);
}

void PaymentReconciliationService::claimRefunds(
    const std::shared_ptr<RunState> &state) const
{
    auto client = drogon::app().getDbClient("default");
    client->execSqlAsync(R"SQL(
        WITH claimed AS (
            SELECT refund.id,
                   CASE WHEN refund.reconciliation_lease_until IS NOT NULL THEN 'lease_expired'
                        ELSE 'retry_due' END AS recovery_reason
            FROM refunds AS refund
            WHERE refund.status = 'PROCESSING'
              AND refund.provider_terminal_at IS NULL
              AND refund.next_reconcile_at <= clock_timestamp()
              AND (refund.reconciliation_lease_until IS NULL
                   OR refund.reconciliation_lease_until <= clock_timestamp())
            ORDER BY refund.next_reconcile_at
            FOR UPDATE SKIP LOCKED
            LIMIT $1
        ), leased AS (
            UPDATE refunds AS refund
            SET provider_retry_count = provider_retry_count + 1,
                reconciliation_lease_token = $3,
                reconciliation_lease_until = clock_timestamp() + INTERVAL '30 seconds',
                next_reconcile_at = clock_timestamp() + LEAST($2, power(2, LEAST(provider_retry_count, 5))) * INTERVAL '1 second'
            FROM claimed WHERE refund.id = claimed.id
            RETURNING refund.*, claimed.recovery_reason
        )
        SELECT leased.id, leased.order_id, leased.amount, leased.provider,
               leased.provider_refund_id, attempt.provider_payment_id, leased.recovery_reason
        FROM leased JOIN payment_attempts AS attempt ON attempt.id = leased.payment_attempt_id
    )SQL",
        [this, state](const drogon::orm::Result &rows) {
            state->pending += rows.size();
            state->summary.scanned += rows.size();
            state->claimsComplete = true;
            for (const auto &row : rows) processRefund(state, row);
            if (state->pending == 0) finishOne(state);
        },
        [state](const drogon::orm::DrogonDbException &error) {
            LOG_ERROR << "Refund reconciliation claim failed: " << error.base().what();
            state->summary.failed++;
            state->claimsComplete = true;
            if (state->pending == 0) finishOne(state);
        }, state->batchSize, state->maxBackoffSeconds, state->leaseToken);
}

void PaymentReconciliationService::processPayment(
    const std::shared_ptr<RunState> &state, const drogon::orm::Row &row) const
{
    const auto attemptId = row["id"].as<std::string>();
    const auto orderId = row["order_id"].as<std::string>();
    PerformanceMetrics::observePaymentReconciliation("payment", row["recovery_reason"].as<std::string>());
    auto provider = PaymentProviderFactory::createNamed(row["provider"].as<std::string>());
    CreatePaymentRequest base{.attemptId = attemptId, .orderId = orderId,
                              .amount = row["total_amount"].as<std::int64_t>(),
                              .currency = PaymentProviderFactory::configuredCurrency()};
    auto done = [this, state, attemptId, orderId, provider, base](ProviderResult<ProviderPayment> result) {
        if (result.outcome != ProviderTransportOutcome::Success || !result.value)
        {
            state->summary.retried++; releaseLease(state, true, attemptId);
            return;
        }
        auto payment = std::move(*result.value);
        if (payment.terminal)
        {
            PaymentTerminalSnapshot snapshot{
                .provider = payment.provider, .providerPaymentId = payment.providerPaymentId,
                .providerStatus = payment.providerStatus, .amount = base.amount,
                .succeeded = payment.mappedState == ProviderPaymentState::Succeeded,
                .failureReason = payment.failureCode.value_or("PROVIDER_PAYMENT_FAILED").substr(0, 200),
                .leaseToken = state->leaseToken};
            lifecycleService_.completeProviderPayment(orderId, attemptId, std::move(snapshot),
                [state](OrderLifecycleOutcome outcome) {
                    outcome == OrderLifecycleOutcome::Failed ? state->summary.failed++ : state->summary.completed++;
                    finishOne(state);
                });
            return;
        }
        paymentRepository_.recordProviderPayment(
            drogon::app().getDbClient("default"), attemptId, payment.providerPaymentId,
            payment.providerStatus, state->leaseToken,
            [state](std::size_t updated) {
                if (updated != 1) { state->summary.failed++; finishOne(state); return; }
                state->summary.retried++; finishOne(state);
            }, [state] { state->summary.failed++; finishOne(state); });
    };
    if (row["provider_payment_id"].isNull()) provider->createOrRecoverPayment(base, std::move(done));
    else
    {
        RetrievePaymentRequest retrieve;
        static_cast<CreatePaymentRequest &>(retrieve) = base;
        retrieve.providerPaymentId = row["provider_payment_id"].as<std::string>();
        provider->retrievePayment(std::move(retrieve), std::move(done));
    }
}

void PaymentReconciliationService::processRefund(
    const std::shared_ptr<RunState> &state, const drogon::orm::Row &row) const
{
    const auto refundId = row["id"].as<std::string>();
    PerformanceMetrics::observePaymentReconciliation("refund", row["recovery_reason"].as<std::string>());
    const auto orderId = row["order_id"].as<std::string>();
    if (row["provider_payment_id"].isNull())
    {
        state->summary.retried++; finishOne(state); return;
    }
    auto provider = PaymentProviderFactory::createNamed(row["provider"].as<std::string>());
    auto done = [state, refundId, orderId](ProviderResult<ProviderRefund> result) {
        if (result.outcome != ProviderTransportOutcome::Success || !result.value)
        {
            state->summary.retried++; releaseLease(state, false, refundId); return;
        }
        const auto refund = std::move(*result.value);
        auto client = drogon::app().getDbClient("default");
        if (!refund.terminal)
        {
            client->execSqlAsync(
                "UPDATE refunds SET provider_refund_id = COALESCE(provider_refund_id, $2), "
                "provider_status = $3, provider_last_sync_at = clock_timestamp(), "
                "next_reconcile_at = clock_timestamp() + INTERVAL '2 seconds', "
                "reconciliation_lease_until = NULL, reconciliation_lease_token = NULL "
                "WHERE id = $1 AND status = 'PROCESSING' AND reconciliation_lease_token = $4 "
                "AND (provider_refund_id IS NULL OR provider_refund_id = $2)",
                [state](const drogon::orm::Result &) { state->summary.retried++; finishOne(state); },
                [state](const drogon::orm::DrogonDbException &) { state->summary.failed++; finishOne(state); },
                refundId, refund.providerRefundId, refund.providerStatus, state->leaseToken);
            return;
        }
        const bool succeeded = refund.mappedState == ProviderRefundState::Succeeded;
        const auto safeReason = refund.failureCode.value_or("PROVIDER_REFUND_FAILED").substr(0, 200);
        client->execSqlAsync(R"SQL(
            WITH updated AS (
                UPDATE refunds SET
                    provider_refund_id = COALESCE(provider_refund_id, $2),
                    provider_status = $3,
                    provider_last_sync_at = clock_timestamp(),
                    provider_terminal_at = clock_timestamp(),
                    status = CASE WHEN $4 THEN 'SUCCEEDED' ELSE 'FAILED' END,
                    refunded_at = CASE WHEN $4 THEN clock_timestamp() ELSE NULL END,
                    failed_at = CASE WHEN $4 THEN NULL ELSE clock_timestamp() END,
                    failure_reason = CASE WHEN $4 THEN NULL ELSE $5 END,
                    next_reconcile_at = NULL,
                    reconciliation_lease_until = NULL, reconciliation_lease_token = NULL
                WHERE id = $1 AND status = 'PROCESSING'
                  AND reconciliation_lease_token = $7
                  AND (provider_refund_id IS NULL OR provider_refund_id = $2)
                RETURNING order_id, payment_attempt_id
            )
            INSERT INTO user_notifications (id, user_id, order_id, type, title, message, dedupe_key)
            SELECT $6, ticket_order.user_id, updated.order_id,
                   CASE WHEN $4 THEN 'AUTO_REFUND_COMPLETED' ELSE 'AUTO_REFUND_FAILED' END,
                   CASE WHEN $4 THEN '自动退款已完成' ELSE '自动退款失败' END,
                   CASE WHEN $4 THEN '支付结果晚于订单终态到达，款项已原路全额退回。'
                        ELSE '自动退款未能完成，请联系支持人员处理。' END,
                   CASE WHEN $4 THEN 'auto-refund:' ELSE 'auto-refund-failed:' END || updated.payment_attempt_id
            FROM updated JOIN orders AS ticket_order ON ticket_order.id = updated.order_id
            ON CONFLICT (dedupe_key) DO NOTHING
        )SQL",
            [state](const drogon::orm::Result &) { state->summary.completed++; finishOne(state); },
            [state](const drogon::orm::DrogonDbException &error) {
                LOG_ERROR << "Refund terminal transition failed: " << error.base().what();
                state->summary.failed++; finishOne(state);
            }, refundId, refund.providerRefundId, refund.providerStatus, succeeded,
            safeReason, "NTF-" + drogon::utils::getUuid(true), state->leaseToken);
    };
    if (row["provider_refund_id"].isNull())
        provider->createOrRecoverRefund(
            {.refundId = refundId, .orderId = orderId,
             .providerPaymentId = row["provider_payment_id"].as<std::string>(),
             .amount = row["amount"].as<std::int64_t>()}, std::move(done));
    else
    {
        RetrieveRefundRequest request;
        request.refundId = refundId;
        request.orderId = orderId;
        request.amount = row["amount"].as<std::int64_t>();
        request.providerPaymentId = row["provider_payment_id"].as<std::string>();
        request.providerRefundId = row["provider_refund_id"].as<std::string>();
        provider->retrieveRefund(std::move(request), std::move(done));
    }
}

void PaymentReconciliationService::releaseLease(
    const std::shared_ptr<RunState> &state, bool payment, const std::string &id)
{
    const std::string table = payment ? "payment_attempts" : "refunds";
    drogon::app().getDbClient("default")->execSqlAsync(
        "UPDATE " + table + " SET reconciliation_lease_until = NULL, reconciliation_lease_token = NULL "
        "WHERE id = $1 AND reconciliation_lease_token = $2",
        [state](const drogon::orm::Result &) { finishOne(state); },
        [state](const drogon::orm::DrogonDbException &) { state->summary.failed++; finishOne(state); },
        id, state->leaseToken);
}

void PaymentReconciliationService::finishOne(const std::shared_ptr<RunState> &state)
{
    if (state->pending > 0) --state->pending;
    if (!state->claimsComplete || state->pending != 0 || !state->completion) return;
    auto completion = std::move(state->completion);
    completion(state->summary);
}
}  // namespace ticketing
