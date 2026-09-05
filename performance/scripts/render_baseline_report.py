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
        "## Discovery 与 first observed unstable",
        "",
        table(data["discovery"]["headers"], data["discovery"]["rows"]),
        "",
        "## Spike 与恢复",
        "",
        table(data["spikes"]["headers"], data["spikes"]["rows"]),
        "",
        "## Local endurance / short soak",
        "",
        data["endurance"].strip(),
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
