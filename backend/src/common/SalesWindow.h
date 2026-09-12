#pragma once
#include <json/json.h>
#include <string>
namespace ticketing
{
enum class SalesWindowState { NotStarted, Open, Ended };
struct SalesWindow
{
    std::string startsAt, endsAt, state, evaluatedAt;
    Json::Value toJson() const
    {
        Json::Value value; value["startsAt"]=startsAt; value["endsAt"]=endsAt;
        value["state"]=state; value["evaluatedAt"]=evaluatedAt; return value;
    }
    template<class Row> static SalesWindow fromRow(const Row &row)
    {
        return {row["sales_starts_at"].template as<std::string>(),
                row["sales_ends_at"].template as<std::string>(),
                row["sales_state"].template as<std::string>(),
                row["sales_evaluated_at"].template as<std::string>()};
    }
};
}
