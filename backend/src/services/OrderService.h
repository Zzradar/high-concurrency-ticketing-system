#pragma once

#include "dto/TicketDtos.h"
#include "repositories/OrderRepository.h"

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

class OrderService
{
  public:
    using Completion = std::function<void(GetOrderResult)>;

    void getOrder(const std::string &orderId,
                  const std::string &userId,
                  Completion completion) const;

  private:
    OrderRepository repository_;
};
}  // namespace ticketing
