"""Re-score recorded transcripts and print the results tables (no model or network needed).

python scripts/summarize.py results/transcripts-2026-11-10.jsonl [more.jsonl ...]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from run_demo import ROOT, injected_effect_executed, per_scenario, score, table


def main() -> None:
    scenarios = {s["id"]: s for s in json.loads((ROOT / "scenarios" / "scenarios.json").read_text())["scenarios"]}
    for path in sys.argv[1:]:
        records = [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]
        for rec in records:
            sc = scenarios[rec["scenario"]]
            rec["score"] = score(rec)
            rec["score"]["injected_effect_executed"] = injected_effect_executed(rec, sc.get("injected_effect"))
            if sc["kind"] == "control":
                rec["score"]["completed"] = all(t in rec["score"]["executed_tools"] for t in sc["expect_tools"])
        print(f"## {Path(path).name}\n\n{table(records)}\n\n{per_scenario(records)}\n")


if __name__ == "__main__":
    main()
