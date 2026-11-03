"""Replay saved task-context JSON without running discovery or modifying a project."""
import argparse
import json
from pathlib import Path
import statistics
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agents" / "scripts"))
from context_presentation import present_context


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="+", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    rows = []
    for index, path in enumerate(args.inputs):
        text = path.read_text(encoding="utf-8-sig")
        # Also accept saved command output with a short header before the JSON.
        payload = json.JSONDecoder().raw_decode(text[text.index("{"):])[0]
        payload = {k: v for k, v in payload.items()
                   if k not in {"context_digest", "presentation", "presentation_reason"}}
        if "shared_context" in payload or "omitted_details" in payload:
            parser.error("Use saved expanded --full output, not a summary.")
        sizes, timings = {}, {"expanded": [], "summary": []}
        for iteration in range(25):
            for label in (("expanded", "summary") if iteration % 2 == 0 else ("summary", "expanded")):
                start = time.perf_counter()
                result = present_context(Path.cwd(), payload, full=label == "expanded")
                rendered = json.dumps(result, ensure_ascii=True, indent=2) + "\n"
                timings[label].append((time.perf_counter() - start) * 1000)
                sizes[label] = len(rendered.encode("utf-8"))
        rows.append({"sample": index + 1, "targets": len(payload.get("results", [payload])),
                     "bytes": sizes, "reduction_percent": round(100 * (1 - sizes["summary"] / sizes["expanded"]), 2),
                     "presentation_median_ms": {k: round(statistics.median(v), 2) for k, v in timings.items()}})
    report = {"method": "25 alternating expanded/summary presentations of identical saved native payloads; includes JSON serialization, excludes discovery and model execution.",
              "limitations": "No token, cost, host truncation threshold or end-to-end speedup claim. No source text or input paths included.",
              "samples": rows}
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
