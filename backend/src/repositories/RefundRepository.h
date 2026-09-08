#pragma once
#include "dto/TicketDtos.h"
#include <drogon/orm/DbClient.h>
#include <functional>
namespace ticketing
{
class RefundRepository
{
  public:
    using Rows = std::function<void(const drogon::orm::Result &)>;
    using Error = std::function<void()>;
    static Json::Value publicJson(const drogon::orm::Row &row);
    void find(const drogon::orm::DbClientPtr &, const std::string &, const std::string &, Rows,
              Error) const;
    void buyerForOrder(const drogon::orm::DbClientPtr &, const std::string &, Rows, Error) const;
    void accepted(const drogon::orm::DbClientPtr &, const std::string &, Rows, Error) const;
    void create(const drogon::orm::DbClientPtr &, const std::string &, const std::string &,
                const std::string &, Rows, Error) const;
    void lock(const drogon::orm::DbClientPtr &, const std::string &, Rows, Error) const;
    void claim(const drogon::orm::DbClientPtr &, std::size_t, double, const std::string &, Rows,
               Error) const;
};
} // namespace ticketing
