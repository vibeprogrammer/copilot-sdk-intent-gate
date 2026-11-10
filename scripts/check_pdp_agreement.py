"""Check every decision a PDP made in saved transcripts against the demo's policy rules.

    python scripts/check_pdp_agreement.py results/2026-11-10-D-gate-openfga.jsonl

For each gated tool call that reached the PDP, each AuthZEN evaluation intent-agent produced is decided again
by the stand-in's explicit rules (standins/indykite_standin.py) and compared with what the PDP answered.
Exit status 1 on any disagreement. No network.
"""

from __future__ import annotations

import collections
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from standins.indykite_standin import decide


def main(paths: list[str]) -> int:
    counts: collections.Counter[str] = collections.Counter()
    bad = []
    for path in paths:
        for line in Path(path).read_text().splitlines():
            rec = json.loads(line)
            pdp = rec.get("pdp", "standin")
            for d in rec["permission_decisions"]:
                for ev, got in zip(d.get("evaluations") or [], d.get("decisions") or [], strict=False):
                    counts[f"{pdp} decisions"] += 1
                    counts[f"{pdp} permits" if got else f"{pdp} denies"] += 1
                    if decide(ev)[0] != got:
                        bad.append((path, rec["scenario"], rec["repeat"], ev, got))
    for key in sorted(counts):
        print(f"{key}: {counts[key]}")
    print(f"disagreements with the demo policy rules: {len(bad)}")
    for b in bad:
        print("  ", b)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
