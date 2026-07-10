from __future__ import annotations


def format_data_quality_summary(result: dict) -> str:
    lines = ["[CryptoDB Data Quality]", ""]
    for key, value in result.items():
        lines.append(f"{key}: {value}")
    return "\n".join(lines)
