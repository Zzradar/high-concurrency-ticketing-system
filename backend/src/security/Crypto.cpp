#include "security/Crypto.h"

#include <openssl/crypto.h>
#include <openssl/evp.h>
#include <openssl/rand.h>

#include <array>
#include <stdexcept>
#include <vector>

namespace
{
std::string toHex(const unsigned char *bytes, std::size_t size)
{
    static constexpr char digits[] = "0123456789abcdef";
    std::string result(size * 2, '0');
    for (std::size_t index = 0; index < size; ++index)
    {
        result[index * 2] = digits[bytes[index] >> 4];
        result[index * 2 + 1] = digits[bytes[index] & 0x0f];
    }
    return result;
}
}  // namespace

namespace ticketing
{
std::string randomHex(std::size_t byteCount)
{
    std::vector<unsigned char> bytes(byteCount);
    if (byteCount == 0 || RAND_bytes(bytes.data(), static_cast<int>(byteCount)) != 1)
    {
        throw std::runtime_error("CSPRNG failed");
    }
    return toHex(bytes.data(), bytes.size());
}

std::string sha256Hex(std::string_view value)
{
    std::array<unsigned char, EVP_MAX_MD_SIZE> digest{};
    unsigned int size = 0;
    auto *context = EVP_MD_CTX_new();
    if (!context || EVP_DigestInit_ex(context, EVP_sha256(), nullptr) != 1 ||
        EVP_DigestUpdate(context, value.data(), value.size()) != 1 ||
        EVP_DigestFinal_ex(context, digest.data(), &size) != 1)
    {
        EVP_MD_CTX_free(context);
        throw std::runtime_error("SHA-256 failed");
    }
    EVP_MD_CTX_free(context);
    return toHex(digest.data(), size);
}

bool constantTimeEqual(std::string_view left, std::string_view right)
{
    if (left.size() != right.size()) return false;
    return CRYPTO_memcmp(left.data(), right.data(), left.size()) == 0;
}
}  // namespace ticketing
