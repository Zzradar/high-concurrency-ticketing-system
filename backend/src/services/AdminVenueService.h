#pragma once
#include "repositories/AdminVenueRepository.h"
namespace ticketing {
class AdminVenueService {
 public: static Json::Value validate(const Json::Value &);
};
}
