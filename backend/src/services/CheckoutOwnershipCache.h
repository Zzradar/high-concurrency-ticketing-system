#pragma once
#include <functional>
#include <string>
namespace ticketing
{
class CheckoutOwnershipCache
{
  public:
    static void lookup(const std::string &checkout,const std::string &user,const std::string &session,
                       std::function<void(std::string)> hit,std::function<void()> miss);
    static void store(const std::string &checkout,const std::string &user,const std::string &session);
};
}
