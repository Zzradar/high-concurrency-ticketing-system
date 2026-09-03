#include "security/PasswordHasher.h"

#include <argon2.h>
#include <openssl/rand.h>

#include <array>
#include <stdexcept>
#include <vector>

namespace ticketing
{
std::string PasswordHasher::hash(std::string_view password,
                                 const AuthConfig &config)
{
    std::array<unsigned char, 16> salt{};
    if (RAND_bytes(salt.data(), static_cast<int>(salt.size())) != 1)
    {
        throw std::runtime_error("password salt generation failed");
    }
    constexpr std::uint32_t hashLength = 32;
    const auto encodedLength = argon2_encodedlen(
        config.argon2TimeCost, config.argon2MemoryCostKib,
        config.argon2Parallelism, salt.size(), hashLength, Argon2_id);
    std::vector<char> encoded(encodedLength);
    const auto status = argon2id_hash_encoded(
        config.argon2TimeCost, config.argon2MemoryCostKib,
        config.argon2Parallelism, password.data(), password.size(), salt.data(),
        salt.size(), hashLength, encoded.data(), encoded.size());
    if (status != ARGON2_OK)
    {
        throw std::runtime_error(argon2_error_message(status));
    }
    return encoded.data();
}

bool PasswordHasher::verify(std::string_view password,
                            std::string_view encodedHash)
{
    const std::string encoded{encodedHash};
    return argon2id_verify(encoded.c_str(), password.data(), password.size()) ==
           ARGON2_OK;
}
}  // namespace ticketing
