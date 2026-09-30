# src/report.py
# Usage: python src\report.py [model]      (default model: qwen2.5:3b)
import json
import pathlib
import sys
from collections import defaultdict

ROOT = pathlib.Path(__file__).resolve().parent.parent
model = sys.argv[1] if len(sys.argv) > 1 else "qwen2.5:3b"
tag = model.replace(":", "_")


def load(path):
    """Parsed results if the file is a {metadata, results} dict, else None
    (the old v1 results file is a plain list and gets skipped)."""
    d = json.loads(path.read_text(encoding="utf-8"))
    return d if isinstance(d, dict) and "metadata" in d else None


candidates = [p for p in sorted((ROOT / "results").glob(f"{tag}_*.json")) if load(p)]
if not candidates:
    sys.exit(f"No results files found for model {model!r} in {ROOT / 'results'}")
latest = candidates[-1]
data = load(latest)
meta, res = data["metadata"], data["results"]
if meta["model"] != model:
    sys.exit(f"{latest.name} was run with {meta['model']!r}, not {model!r}")

cats = defaultdict(lambda: [0, 0])
first_leak = {}
for r in res:
    cats[r["category"]][0] += r["attack_succeeded"]
    cats[r["category"]][1] += 1
    if r["attack_succeeded"] and r["category"] not in first_leak:
        first_leak[r["category"]] = r

attacks = [r for r in res if r["category"] != "control"]
hits = sum(r["attack_succeeded"] for r in attacks)
cut = sum(r["done_reason"] == "length" for r in res)

L = [f"# Prompt Injection Evaluation Report\n",
     f"- Model: `{meta['model']}` | Temperature: {meta['temperature']} | "
     f"Max tokens: {meta['max_tokens']} | Runs per case: {meta['runs_per_case']}",
     f"- Source file: `{latest.name}`",
     f"- Attack runs leaking the canary (control excluded): **{hits}/{len(attacks)} "
     f"= {hits / len(attacks):.1%}**",
     f"- Runs cut off by max_tokens: {cut}\n",
     "## Results by category\n", "| Category | Leaks / runs |", "|---|---|"]
for c, (s, n) in cats.items():
    L.append(f"| {c} | {s}/{n} |")

L += ["\n## Example leaks (first leaking run per category)\n"]
for c, r in first_leak.items():
    L += [f"### {r['test_id']} - {r['name']} ({c})",
          "**Attack:**", "```", r["request"]["messages"][1]["content"].strip(), "```",
          "**Response:**", "```", r["response"].strip()[:600], "```\n"]

L += ["## Method\n",
      meta["evaluation_method"],
      "\n## Limitations\n",
      f"- One small local model ({meta['model']}); results say nothing about "
      "other models, including frontier models.",
      f"- Only {meta['runs_per_case']} runs per case at temperature "
      f"{meta['temperature']}; results vary between runs, so per-category "
      "numbers are rough.",
      "- The only automated criterion is canary exposure. A response can name the "
      "token while refusing (counted as a leak), and an off-task response counts "
      "as blocked.",
      "- Ten hand-written cases; no coverage claim.",
      "- Single system prompt and a fictional domain."]

out = ROOT / "reports" / f"report_{tag}.md"
out.parent.mkdir(exist_ok=True)
out.write_text("\n".join(L), encoding="utf-8")
print(f"Wrote {out}")