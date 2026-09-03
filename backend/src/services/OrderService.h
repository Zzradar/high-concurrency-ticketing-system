#pragma once

#include "dto/TicketDtos.h"
#include "repositories/OrderRepository.h"
#include "services/OrderLifecycleService.h"

#include <functional>
#include <optional>
#include <string>

namespace ticketing
{
enum class GetOrderOutcome
{
    Found,
    InvalidArgument,
    NotFound,
    InternalError,
};

struct GetOrderResult
{
    GetOrderOutcome outcome{GetOrderOutcome::InternalError};
    std::optional<TicketOrder> value;
};

enum class CancelOrderOutcome
{
    Cancelled,
    InvalidArgument,
    NotFound,
    NotCancellable,
    OrderExpired,
    InternalError,
};

struct CancelOrderResult
{
    CancelOrderOutcome outcome{CancelOrderOutcome::InternalError};
    std::optional<TicketOrder> value;
};

class OrderService
{
  public:
    using Completion = std::function<void(GetOrderResult)>;

    void getOrder(const std::string &orderId,
                  const std::string &userId,
                  Completion completion) const;

    void cancelOrder(const std::string &orderId,
                     const std::string &userId,
                     std::function<void(CancelOrderResult)> completion) const;

  private:
    OrderRepository repository_;
    OrderLifecycleService lifecycleService_;
};
}  // namespace ticketing
