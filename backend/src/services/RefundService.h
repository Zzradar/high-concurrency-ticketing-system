#pragma once
#include "repositories/OrderRepository.h"
#include "repositories/RefundRepository.h"
namespace ticketing
{
struct RefundResponse
{
    int status{500};
    std::string code{"INTERNAL_ERROR"};
    Json::Value body;
};
class RefundService
{
  public:
    using Completion = std::function<void(RefundResponse)>;
    void request(std::string order, std::string user, Completion) const;
    void get(std::string id, std::string user, Completion) const;

  private:
    struct State;
    void existing(const std::shared_ptr<State> &, bool raced = false) const;
    void eligibility(const std::shared_ptr<State> &) const;
    static void finish(const std::shared_ptr<State> &, RefundResponse, bool commit = false);
    RefundRepository repository_;
    OrderRepository orders_;
};
} // namespace ticketing
