#include "workers/PaymentReconciliationWorker.h"
#include "observability/PerformanceMetrics.h"

#include <drogon/drogon.h>

#include <algorithm>

namespace ticketing
{
PaymentReconciliationWorker::PaymentReconciliationWorker(
    std::size_t batchSize, double intervalSeconds, double maxBackoffSeconds)
    : batchSize_(batchSize), intervalSeconds_(intervalSeconds),
      maxBackoffSeconds_(maxBackoffSeconds)
{
}

void PaymentReconciliationWorker::start()
{
    if (started_) return;
    started_ = true;
    runCurrentRound();
}

void PaymentReconciliationWorker::runCurrentRound()
{
    auto weakSelf = weak_from_this();
    service_.runOnce(batchSize_, maxBackoffSeconds_,
        [weakSelf](PaymentReconciliationSummary summary) {
            if (auto self = weakSelf.lock())
            {
                PerformanceMetrics::setPaymentReconciliationPending(
                    static_cast<double>(summary.scanned - std::min(summary.scanned, summary.completed)));
                if (summary.completed) PerformanceMetrics::observePaymentReconciliation("mixed", "completed");
                if (summary.retried) PerformanceMetrics::observePaymentReconciliation("mixed", "retried");
                if (summary.failed) PerformanceMetrics::observePaymentReconciliation("mixed", "failed");
                if (summary.failed)
                    LOG_ERROR << "Payment reconciliation failures=" << summary.failed;
                auto weakAgain = weakSelf;
                drogon::app().getDbClient("default")->execSqlAsync(
                    "SELECT status, COUNT(*) AS count FROM refunds GROUP BY status",
                    [weakAgain](const drogon::orm::Result &rows) {
                        for (const auto &row : rows)
                            PerformanceMetrics::setRefundStatusCount(
                                row["status"].as<std::string>(), row["count"].as<double>());
                        if (auto current = weakAgain.lock()) current->scheduleNextRound();
                    },
                    [weakAgain](const drogon::orm::DrogonDbException &) {
                        if (auto current = weakAgain.lock()) current->scheduleNextRound();
                    });
            }
        });
}

void PaymentReconciliationWorker::scheduleNextRound()
{
    auto weakSelf = weak_from_this();
    drogon::app().getLoop()->runAfter(intervalSeconds_, [weakSelf] {
        if (auto self = weakSelf.lock()) self->runCurrentRound();
    });
}
}  // namespace ticketing
