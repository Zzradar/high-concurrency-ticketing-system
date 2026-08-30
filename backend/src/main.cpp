#include <drogon/drogon.h>

#include <exception>
#include <string>

int main(int argc, char *argv[])
{
    const std::string configPath =
        argc > 1 ? argv[1] : "config/config.json";

    try
    {
        drogon::app().loadConfigFile(configPath);
        LOG_INFO << "Starting ticketing backend with config: " << configPath;
        drogon::app().run();
    }
    catch (const std::exception &error)
    {
        LOG_FATAL << "Backend startup failed: " << error.what();
        return 1;
    }

    return 0;
}
