"""Fail-closed resource qualification and explicitly conditional scale estimates."""
import math


def stop_reason(samples):
    if not samples:
        return "missing resource observations"
    last = samples[-1]
    required = ("memory", "memoryLimit", "fd", "fdLimit", "linuxAvailable", "linuxTotal", "cpuFraction")
    if any(k not in last or not math.isfinite(last[k]) or last[k] < 0 for k in required):
        return "incomplete resource observation"
    if min(last["memoryLimit"], last["fdLimit"], last["linuxTotal"]) <= 0:
        return "invalid resource limits"
    if last.get("oom", False) or last.get("restarted", False):
        return "OOM or restart"
    if last["memory"] >= .85 * last["memoryLimit"]:
        return "container memory >= 85%"
    if last["fd"] >= .8 * last["fdLimit"]:
        return "FD >= 80%"
    if last["linuxAvailable"] < .25 * last["linuxTotal"]:
        return "Docker/WSL available memory < 25%"
    if len(samples) >= 3 and all(s["cpuFraction"] > .9 for s in samples[-3:]):
        return "generator CPU > 90% for three observations"
    if len(samples) >= 3 and all(s.get("swapOutPages", 0) > 0 for s in samples[-3:]):
        return "sustained swap-out"
    return None


def estimate(samples, docker_bytes, host_total, host_available, reserved_bytes):
    valid = sorted((s for s in samples if s.get("valid")), key=lambda s: s["vus"])
    result = {"status": "INCONCLUSIVE", "inputs": samples, "reserveBytes": reserved_bytes,
              "formula": "max(OLS prediction, last peak + max adjacent marginal * added VUs) * 1.30 + independent reserve",
              "targets": [], "actualTensOfThousandsExecuted": False}
    if len(valid) < 3 or len({s["vus"] for s in valid}) != len(valid):
        result["reason"] = "Need at least three distinct qualified calibration samples"
        return result
    xs, ys = [s["vus"] for s in valid], [s["peakBytes"] for s in valid]
    xm, ym = sum(xs) / len(xs), sum(ys) / len(ys)
    slope = sum((x-xm)*(y-ym) for x, y in zip(xs, ys)) / sum((x-xm)**2 for x in xs)
    intercept = ym-slope*xm
    marginal = max(0, max((ys[i]-ys[i-1])/(xs[i]-xs[i-1]) for i in range(1, len(xs))))
    for target in (10000, 20000, 30000):
        linear = max(0, intercept + slope*target)
        conservative = ys[-1] + marginal*(target-xs[-1])
        generator = max(linear, conservative)*1.3
        safe_memory = generator + reserved_bytes <= docker_bytes*.7 and host_available-generator >= host_total*.25
        result["targets"].append({"actualVUs": target, "linearBytes": linear, "conservativeBytes": conservative,
            "generatorWith30PercentMarginBytes": generator, "memoryCondition": safe_memory,
            "status": "INCONCLUSIVE" if safe_memory else "UNSAFE"})
    result.update(slopeBytesPerVU=slope, interceptBytes=intercept, maxMarginalBytesPerVU=marginal)
    result["status"] = "UNSAFE" if not result["targets"][0]["memoryCondition"] else "INCONCLUSIVE"
    result["reason"] = "Memory estimates cannot establish CPU, FD/port, 3000-VU stability or SUT correctness qualification"
    return result
