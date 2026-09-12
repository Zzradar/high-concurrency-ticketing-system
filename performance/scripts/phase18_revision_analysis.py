"""Post-measurement counts/resources only; frozen latency statistics are untouched."""
import argparse
import json
from pathlib import Path

def read(path):
    return json.loads(path.read_text(encoding="utf-8"))

def redis_commands(value):
    if isinstance(value, dict):
        return value
    result = {}
    for line in value.splitlines():
        if line.startswith("cmdstat_"):
            name, fields = line.split(":", 1)
            result[name] = dict(field.split("=", 1) for field in fields.split(","))
    return result

def query_features(folder):
    result = {}
    for stage in ["availability-5000", "availability-10000", "browser", "k6", "burst"]:
        before = read(folder / (stage + "-before-database.json"))
        after = read(folder / (stage + "-after-database.json"))
        old = {row["queryid"]: row for row in before["pg"]}
        queries = []
        for row in after["pg"]:
            previous = old.get(row["queryid"], {})
            calls = row["calls"] - previous.get("calls", 0)
            if calls:
                queries.append({"query": row["query"], "calls": calls,
                    "returnedRows": row["rows"] - previous.get("rows", 0)})
        ca, cb = redis_commands(before["redis"]), redis_commands(after["redis"])
        commands = {key: {field: int(value.get(field, 0)) - int(ca.get(key, {}).get(field, 0))
            for field in ["calls", "failed_calls", "rejected_calls"]} for key, value in cb.items()}
        result[stage] = {"sql": queries, "redis": commands}
    return result

def resource_features(folder):
    reads = read(folder / "reads.json")
    browser = read(folder / "browser.json")
    resources = read(folder / "resource-samples.json")
    k6 = read(folder / "k6-summary.json")["metrics"]
    peaks = {key: 0 for key in ["VmHWM", "VmRSS", "Threads", "cgroupMemoryBytes", "cgroupPids"]}
    for sample in resources["samples"]:
        lines = sample["apiProcess"].splitlines()
        for line in lines:
            if ":" in line:
                key, value = line.split(":", 1)
                if key in ["VmHWM", "VmRSS", "Threads"]:
                    peaks[key] = max(peaks[key], int(value.split()[0]))
        peaks["cgroupMemoryBytes"] = max(peaks["cgroupMemoryBytes"], int(lines[-2]))
        peaks["cgroupPids"] = max(peaks["cgroupPids"], int(lines[-1]))
    return {"processObservedPeaks": peaks, "samples": len(resources["samples"]),
        "browserBytes": sum(row.get("bytes", 0) for row in browser["requests"]),
        "k6Requests": k6["http_reqs"]["values"]["count"],
        "k6Checks": k6["checks"]["values"], "k6ErrorRate": k6["http_req_failed"]["values"]["rate"],
        "payloads": [{"seats": row["seatCount"],
            "snapshotBytes": sorted({r["bytes"] for r in row["availability"]["snapshots"]}),
            "deltaBytes": sorted({r["bytes"] for r in row["availability"]["emptyDeltas"]}),
            "layoutWireBytes": sum(r["bytes"] for r in row["layout"]) + row["gzipWire"]["bytes"]}
            for row in reads]}

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--after", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    baseline = Path(__file__).resolve().parents[1] / "experiments/phase18-admission-overload/baseline"
    args.out.mkdir(parents=True, exist_ok=True)
    for name, function in [("resources", resource_features), ("query-features", query_features)]:
        value = {"before": function(baseline), "after": function(args.after)}
        (args.out / (name + ".json")).write_bytes((json.dumps(value, indent=2) + "\n").encode())
