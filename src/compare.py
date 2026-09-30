# src/compare.py
# Usage: python src\compare.py [model ...]     (default: qwen2.5:3b llama3.2:3b)
import json
import pathlib
import sys
from collections import defaultdict

import matplotlib
matplotlib.use("Agg")  # write PNG files without opening a window
import matplotlib.pyplot as plt

ROOT = pathlib.Path(__file__).resolve().parent.parent
models = sys.argv[1:] or ["qwen2.5:3b", "llama3.2:3b"]


def load(path):
    """Parsed results if the file is a {metadata, results} dict, else None."""
    d = json.loads(path.read_text(encoding="utf-8"))
    return d if isinstance(d, dict) and "metadata" in d else None


def latest_for(model):
    tag = model.replace(":", "_")
    files = [p for p in sorted((ROOT / "results").glob(f"{tag}_*.json")) if load(p)]
    if not files:
        sys.exit(f"No results files found for model {model!r}")
    path = files[-1]
    data = load(path)
    if data["metadata"]["model"] != model:
        sys.exit(f"{path.name} was run with {data['metadata']['model']!r}, not {model!r}")
    return path, data


runs = {m: latest_for(m) for m in models}

# leaks / runs per category, per model
counts = {}
for m, (path, data) in runs.items():
    c = defaultdict(lambda: [0, 0])
    for r in data["results"]:
        c[r["category"]][0] += r["attack_succeeded"]
        c[r["category"]][1] += 1
    counts[m] = c

if any(set(counts[m]) != set(counts[models[0]]) for m in models):
    sys.exit("The models were run on different categories; comparison would be unfair")

attack_cats = [c for c in counts[models[0]] if c != "control"]
all_cats = attack_cats + (["control"] if "control" in counts[models[0]] else [])

# fairness check: same settings, same system prompt, same cases
keys = ["temperature", "max_tokens", "runs_per_case", "system_prompt"]
base = runs[models[0]][1]["metadata"]
mismatch = sorted({k for m in models[1:] for k in keys
                   if runs[m][1]["metadata"][k] != base[k]})
ids = [sorted({r["test_id"] for r in runs[m][1]["results"]}) for m in models]
if any(i != ids[0] for i in ids):
    mismatch.append("test cases")
if mismatch:
    print("WARNING: settings differ between models:", ", ".join(mismatch))

# overall attack rate per model (control excluded)
overall = {}
for m in models:
    attacks = [r for r in runs[m][1]["results"] if r["category"] != "control"]
    overall[m] = (sum(r["attack_succeeded"] for r in attacks), len(attacks))

# ---- markdown ----
L = ["# Model Comparison: Prompt-Injection Canary Exposure\n",
     "Small-sample comparison. It does not rank models by security.\n"]
if mismatch:
    L.append(f"**Warning: settings differ between models: {', '.join(mismatch)}.**\n")
L += ["## Runs compared\n",
      "| Model | Source file | Temperature | Max tokens | Runs per case |",
      "|---|---|---|---|---|"]
for m in models:
    p, d = runs[m]
    md = d["metadata"]
    L.append(f"| `{m}` | `{p.name}` | {md['temperature']} | {md['max_tokens']} | "
             f"{md['runs_per_case']} |")

L += ["\n## Results by category (leaks / runs)\n",
      "| Category | " + " | ".join(f"`{m}`" for m in models) + " |",
      "|---|" + "---|" * len(models)]
for c in all_cats:
    L.append(f"| {c} | " + " | ".join(f"{counts[m][c][0]}/{counts[m][c][1]}"
                                      for m in models) + " |")
L.append("| **All attacks (control excluded)** | " + " | ".join(
    f"**{overall[m][0]}/{overall[m][1]} = {overall[m][0] / overall[m][1]:.1%}**"
    for m in models) + " |")

L += ["\n![Leak rate by category](comparison.png)\n",
      "## Reading this table\n",
      "- With 5 runs per case, differences of 1-2 runs are within noise.",
      "- A leak means the canary appeared in the output; it is not proof that the "
      "model obeyed the attacker.",
      "- One system prompt, ten cases, two 3B models: no claim about other models "
      "or prompts."]

out_md = ROOT / "reports" / "comparison.md"
out_png = ROOT / "reports" / "comparison.png"
out_md.parent.mkdir(exist_ok=True)
out_md.write_text("\n".join(L), encoding="utf-8")

# ---- grouped bar chart: leak rate by category, one bar per model ----
fig, ax = plt.subplots(figsize=(10, 5))
width = 0.8 / len(models)
for i, m in enumerate(models):
    xs = [j + i * width for j in range(len(attack_cats))]
    rates = [100 * counts[m][c][0] / counts[m][c][1] for c in attack_cats]
    ax.bar(xs, rates, width, label=m)
    for x, c, rate in zip(xs, attack_cats, rates):
        ax.text(x, rate + 1, f"{counts[m][c][0]}/{counts[m][c][1]}",
                ha="center", va="bottom", fontsize=8)
ax.set_xticks([j + width * (len(models) - 1) / 2 for j in range(len(attack_cats))])
ax.set_xticklabels([c.replace("_", "\n") for c in attack_cats], fontsize=8)
ax.set_ylabel("Leak rate (% of runs)")
ax.set_ylim(0, 110)
ax.set_title("Canary exposure by attack category (labels: leaks/runs)")
ax.legend()
fig.tight_layout()
fig.savefig(out_png, dpi=150)
plt.close(fig)

print(f"Wrote {out_md}")
print(f"Wrote {out_png}")