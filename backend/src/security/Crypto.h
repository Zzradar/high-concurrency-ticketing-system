#pragma once

#include <cstddef>
#include <string>
#include <string_view>

namespace ticketing
{
std::string randomHex(std::size_t byteCount);
std::string sha256Hex(std::string_view value);
bool constantTimeEqual(std::string_view left, std::string_view right);
}  // namespace ticketing
