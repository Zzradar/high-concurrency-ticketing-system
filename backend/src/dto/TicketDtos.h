#pragma once

#include <json/json.h>

#include <cstdint>
#include <optional>
#include <string>
#include <vector>

namespace ticketing
{
struct TicketEvent
{
    std::string id;
    std::string name;
    std::string description;
    std::string city;
    std::string venue;
    std::string dateRange;
    std::string status;
    std::string cover;
    std::int64_t sessionCount{};
    std::string category;

    Json::Value toJson() const
    {
        Json::Value value;
        value["id"] = id;
        value["name"] = name;
        value["description"] = description;
        value["city"] = city;
        value["venue"] = venue;
        value["dateRange"] = dateRange;
        value["status"] = status;
        value["cover"] = cover;
        value["sessionCount"] = Json::Int64(sessionCount);
        value["category"] = category;
        return value;
    }
};

struct TicketSession
{
    std::string id;
    std::string eventId;
    std::string date;
    std::string time;
    std::string weekday;
    std::string venue;
    std::string gateTime;
    std::string status;
    std::int64_t priceFrom{};
    std::string availability;

    Json::Value toJson() const
    {
        Json::Value value;
        value["id"] = id;
        value["eventId"] = eventId;
        value["date"] = date;
        value["time"] = time;
        value["weekday"] = weekday;
        value["venue"] = venue;
        value["gateTime"] = gateTime;
        value["status"] = status;
        value["priceFrom"] = Json::Int64(priceFrom);
        value["availability"] = availability;
        return value;
    }
};

struct Seat
{
    std::string id;
    std::string sessionId;
    std::string label;
    std::string row;
    std::int32_t number{};
    std::string status;
    std::string zone;
    std::int64_t price{};

    Json::Value toJson() const
    {
        Json::Value value;
        value["id"] = id;
        value["sessionId"] = sessionId;
        value["label"] = label;
        value["row"] = row;
        value["number"] = number;
        value["status"] = status;
        value["zone"] = zone;
        value["price"] = Json::Int64(price);
        return value;
    }
};

struct Reservation
{
    std::string id;
    std::string userId;
    std::string sessionId;
    std::vector<std::string> seatIds;
    std::string status;
    std::string expiresAt;
    std::string createdAt;

    Json::Value toJson() const
    {
        Json::Value value;
        value["id"] = id;
        value["userId"] = userId;
        value["sessionId"] = sessionId;
        value["seatIds"] = Json::Value{Json::arrayValue};
        for (const auto &seatId : seatIds)
        {
            value["seatIds"].append(seatId);
        }
        value["status"] = status;
        value["expiresAt"] = expiresAt;
        value["createdAt"] = createdAt;
        return value;
    }
};

struct TicketOrder
{
    std::string id;
    std::string reservationId;
    std::string eventId;
    std::string sessionId;
    std::vector<std::string> seatIds;
    std::string status;
    std::int64_t totalAmount{};
    std::string expiresAt;
    std::string createdAt;
    std::optional<std::string> paidAt;

    Json::Value toJson() const
    {
        Json::Value value;
        value["id"] = id;
        value["reservationId"] = reservationId;
        value["eventId"] = eventId;
        value["sessionId"] = sessionId;
        value["seatIds"] = Json::Value{Json::arrayValue};
        for (const auto &seatId : seatIds)
        {
            value["seatIds"].append(seatId);
        }
        value["status"] = status;
        value["totalAmount"] = Json::Int64(totalAmount);
        value["expiresAt"] = expiresAt;
        value["createdAt"] = createdAt;
        if (paidAt)
        {
            value["paidAt"] = *paidAt;
        }
        return value;
    }
};

struct ReservationResult
{
    Reservation reservation;
    TicketOrder order;

    Json::Value toJson() const
    {
        Json::Value value;
        value["reservation"] = reservation.toJson();
        value["order"] = order.toJson();
        return value;
    }
};

struct CheckoutSession
{
    std::string id;
    std::string userId;
    std::string sessionId;
    std::vector<std::string> seatIds;
    std::string status;
    std::int64_t revision{};
    std::optional<std::string> reservationId;
    std::string createdAt;
    std::string updatedAt;
    std::optional<ReservationResult> formalResult;

    Json::Value toJson() const
    {
        Json::Value value;
        value["id"] = id;
        value["userId"] = userId;
        value["sessionId"] = sessionId;
        value["seatIds"] = Json::Value{Json::arrayValue};
        for (const auto &seatId : seatIds)
        {
            value["seatIds"].append(seatId);
        }
        value["status"] = status;
        value["revision"] = Json::Int64(revision);
        if (reservationId)
        {
            value["reservationId"] = *reservationId;
        }
        value["createdAt"] = createdAt;
        value["updatedAt"] = updatedAt;
        if (formalResult)
        {
            value["reservation"] = formalResult->reservation.toJson();
            value["order"] = formalResult->order.toJson();
        }
        return value;
    }
};

struct PaymentAttempt
{
    std::string id;
    std::string orderId;
    std::string status;
    std::string startedAt;
    std::string processingDeadline;
    std::string scheduledCompleteAt;
    std::optional<std::string> completedAt;
    std::optional<std::string> timedOutAt;
    std::optional<std::string> acceptedAt;
    std::optional<std::string> failureReason;

    Json::Value toJson() const
    {
        Json::Value value;
        value["id"] = id;
        value["orderId"] = orderId;
        value["status"] = status;
        value["startedAt"] = startedAt;
        value["processingDeadline"] = processingDeadline;
        value["scheduledCompleteAt"] = scheduledCompleteAt;
        if (completedAt) value["completedAt"] = *completedAt;
        if (timedOutAt) value["timedOutAt"] = *timedOutAt;
        if (acceptedAt) value["acceptedAt"] = *acceptedAt;
        if (failureReason) value["failureReason"] = *failureReason;
        return value;
    }
};

struct PaymentStartResult
{
    std::string disposition;
    TicketOrder order;
    std::optional<PaymentAttempt> paymentAttempt;

    Json::Value toJson() const
    {
        Json::Value value;
        value["disposition"] = disposition;
        value["order"] = order.toJson();
        value["paymentAttempt"] = paymentAttempt
                                      ? paymentAttempt->toJson()
                                      : Json::Value{Json::nullValue};
        return value;
    }
};

struct UserNotification
{
    std::string id;
    std::string orderId;
    std::string type;
    std::string title;
    std::string message;
    std::string createdAt;
    std::optional<std::string> readAt;

    Json::Value toJson() const
    {
        Json::Value value;
        value["id"] = id;
        value["orderId"] = orderId;
        value["type"] = type;
        value["title"] = title;
        value["message"] = message;
        value["createdAt"] = createdAt;
        if (readAt) value["readAt"] = *readAt;
        return value;
    }
};
}  // namespace ticketing
