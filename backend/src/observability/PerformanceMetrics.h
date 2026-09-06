#pragma once

#include <memory>

namespace ticketing
{
class PasswordHashObserver;

class PerformanceMetrics final
{
  public:
    static void registerWithApplication();
    static std::shared_ptr<PasswordHashObserver> passwordHashObserver();
};
}  // namespace ticketing
