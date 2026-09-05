"""Render the sanitized Phase 10A baseline report from committed aggregate data."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def table(headers: list[str], rows: list[list[Any]]) -> str:
    rendered = [[str(value) for value in row] for row in rows]
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    lines.extend("| " + " | ".join(row) + " |" for row in rendered)
    return "\n".join(lines)


def percentiles(metric: dict[str, Any]) -> str:
    values = []
    for percentile in ("p50", "p95", "p99"):
        pair = "; ".join(f"{value:.3f}" for value in metric[percentile])
        values.append(f"{percentile}={pair}")
    return "; ".join(values)


def latency_semantics(data: dict[str, Any]) -> str:
    details = data["multiRequestLatency"]
    payment_start = details["paymentStart"]
    checkout = details["checkout"]
    payment = details["paymentLifecycle"]
    rows = [
        [
            "payment-start",
            percentiles(payment_start["aggregateHttpRequestLatencyMs"]),
            "单次 pay-start HTTP 请求",
            "不适用（该 workload 不等待完成）",
        ],
        [
            "checkout",
            percentiles(checkout["aggregateHttpRequestLatencyMs"]),
            "create / confirm：未单独捕获",
            percentiles(checkout["flowDurationMs"])
            + " (`iteration_duration`)",
        ],
        [
            "payment-lifecycle",
            percentiles(payment["aggregateHttpRequestLatencyMs"]),
            "pay-start / poll：未单独捕获",
            percentiles(payment["flowDurationMs"])
            + " (`iteration_duration`); poll/payment="
            + "; ".join(f"{value:.3f}" for value in payment["pollRequestsPerPayment"]),
        ],
    ]
    notes = "\n".join(
        [
            table(
                ["工作负载", "聚合 HTTP 请求延迟（两次运行，ms）", "端点级 HTTP 延迟", "完整流程时长（两次运行，ms）"],
                rows,
            ),
            "",
            f"- payment-start：{payment_start['note']}",
            f"- checkout：{checkout['note']}",
            f"- payment-lifecycle：{payment['note']}",
            f"- Mixed：{details['mixedLatencyScope']}",
        ]
    )
    return notes


def render(data: dict[str, Any]) -> str:
    metadata = data["metadata"]
    sections = [
        "# Phase 10A 本地性能 Baseline",
        "",
        "> 这是单机 Docker Desktop / WSL2 环境下的可追溯基线，不是生产 SLO、生产容量或生产级耐久认证。",
        "",
        "## 测试身份与环境",
        "",
        table(["字段", "值"], [[key, value] for key, value in metadata.items()]),
        "",
        "## 方法与判据",
        "",
        data["methodology"].strip(),
        "",
        "## Confirmed stable 基线",
        "",
        table(data["stable"]["headers"], data["stable"]["rows"]),
        "",
        "## 多请求流程延迟语义",
        "",
        latency_semantics(data),
        "",
        "## Discovery 与 first observed unstable",
        "",
        table(data["discovery"]["headers"], data["discovery"]["rows"]),
        "",
        "## Spike 与恢复",
        "",
        table(data["spikes"]["headers"], data["spikes"]["rows"]),
        "",
        "## Extended steady observation",
        "",
        data["extendedSteady"].strip(),
        "",
        "## 系统、PostgreSQL 与 Redis 证据",
        "",
        data["observations"].strip(),
        "",
        "## 正确性与回归",
        "",
        data["correctness"].strip(),
        "",
        "## Phase 10B 候选实验（未实施）",
        "",
        data["candidates"].strip(),
        "",
        "## 限制与未执行项",
        "",
        data["limitations"].strip(),
        "",
        "## 资料与开源参考",
        "",
        "\n".join(f"- {item}" for item in data["references"]),
        "",
    ]
    report = "\n".join(sections)
    forbidden = ("sessionToken", "csrfToken", "Ticketing123!", "ticketing_session=")
    leaked = [value for value in forbidden if value in report]
    if leaked:
        raise ValueError(f"report contains sensitive fields: {leaked}")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    data = json.loads(args.input.read_text(encoding="utf-8"))
    args.output.write_text(render(data), encoding="utf-8", newline="\n")
    print(f"[PASS] rendered sanitized report: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
