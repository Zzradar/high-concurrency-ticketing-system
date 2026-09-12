# Waiting Room capability evidence

Real isolated API/PostgreSQL/Redis and frozen Edge/Playwright binary and launch topology. This is new capability evidence, not an OFF A/B run. The browser fixture uses temporary capability data and allows its own port 18183 origin; no baseline/protocol file changed.

Nine native browser gates pass: direct seat URL and safe login return, explicit join, PAUSED, two real tabs sharing one position, 35-second real hidden interval with no status/heartbeat and expired presence, real Redis outage HTTP 503 recovery, real 429, generation reset requiring explicit join, admitted seat navigation without waiting polls, back navigation and logout cleanup. Availability maximum in-flight is 1. Browser JSON contains request timing/status and native visibility, no session credentials. The separate cache-polling capability has the longer 91-second hidden availability gate.

Public HTTP contract 2/2, full Vitest 285/285, production real API build, CTest 36/36 and frozen baseline evidence 7/7 pass. Public metadata is advisory and includes only required/state/prequeueStartsAt. Protected requests still enforce authoritative admission; 409 now includes typed state and polling guidance. In-flight responses are fenced on route, logout and unmount. Existing checkout recovery and release remain accessible without qualification.

Diagnostics waiting-ui-v1/v2 are CLOSED selector/build-timing fixture failures superseded by this successful run. They are not deployment candidates or formal measurement data. This shared-host capability run does not represent a production SLA.
