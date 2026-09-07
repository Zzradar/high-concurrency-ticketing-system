#include "payments/StripeConfig.h"
#include <cstdlib>
#include <iostream>
#include <limits>
#include <stdexcept>

int main()
{
    using ticketing::StripeConfig;
    try
    {
        unsetenv("STRIPE_PROCESSING_GRACE_SECONDS");
        if (StripeConfig::load().processingGraceSeconds != 600.0)
            throw std::runtime_error("default grace must be 600 seconds");
        setenv("STRIPE_PROCESSING_GRACE_SECONDS", "720.5", 1);
        if (StripeConfig::load().processingGraceSeconds != 720.5)
            throw std::runtime_error("configured grace ignored");
        for (const auto *invalid : {"0", "-1", "nan", "inf", "1e999", "abc", "600seconds"})
        {
            setenv("STRIPE_PROCESSING_GRACE_SECONDS", invalid, 1);
            bool rejected = false;
            try { StripeConfig::load(); }
            catch (const std::invalid_argument &) { rejected = true; }
            if (!rejected) throw std::runtime_error("invalid grace accepted");
        }
        unsetenv("STRIPE_PROCESSING_GRACE_SECONDS");
        StripeConfig config;
        config.secretKey = "test";
        config.webhookSecret = "test";
        StripeConfig::validate(config);
        for (const double invalid : {0.0, -1.0, std::numeric_limits<double>::infinity(),
                                     std::numeric_limits<double>::quiet_NaN()})
        {
            config.processingGraceSeconds = invalid;
            bool rejected = false;
            try { StripeConfig::validate(config); }
            catch (const std::invalid_argument &) { rejected = true; }
            if (!rejected) throw std::runtime_error("startup accepted invalid grace");
        }
    }
    catch (const std::exception &error) { std::cerr << error.what() << '\n'; return 1; }
    return 0;
}
