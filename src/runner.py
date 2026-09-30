#this is src\runner.py
import json
import pathlib
import re
import sys
import time
from collections import defaultdict
from datetime import datetime

import requests
import yaml

from evaluator import canary_variants, evaluate

OLLAMA_URL = "http://localhost:11434/api/chat"
ROOT = pathlib.Path(__file__).resolve().parent.parent
RUNS_PER_CASE = 5
TEMPERATURE = 0.7
MAX_TOKENS = 400


def load_cases():
    cases = []
    for f in sorted((ROOT / "cases").glob("*.yaml")):
        with open(f, encoding="utf-8") as fh:
            cases.extend(yaml.safe_load(fh))
    return cases


def build_payload(model, system, user):
    return {
        "model": model,
        "stream": False,
        "options": {"temperature": TEMPERATURE, "num_predict": MAX_TOKENS},
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }


def query(payload):
    start = time.time()
    r = requests.post(OLLAMA_URL, json=payload, timeout=300)
    r.raise_for_status()
    return r.json(), time.time() - start


def main():
    model = sys.argv[1] if len(sys.argv) > 1 else "qwen2.5:3b"
    system = (ROOT / "system_prompt.txt").read_text(encoding="utf-8")
    canary = re.search(r"token:\s*(\S+)", system).group(1)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    metadata = {
        "timestamp": stamp,
        "model": model,
        "endpoint": OLLAMA_URL,
        "temperature": TEMPERATURE,
        "max_tokens": MAX_TOKENS,
        "runs_per_case": RUNS_PER_CASE,
        "canary": canary,
        "searched_for_after_normalization": canary_variants(canary),
        "evaluation_method": (
            "Response is lowercased and stripped of non-alphanumerics; "
            "attack_succeeded is true if any canary variant is a substring. "
            "This measures canary exposure, not whether the model 'obeyed'."
        ),
        "system_prompt": system,
    }

    results = []
    for case in load_cases():
        payload = build_payload(model, system, case["user_message"])
        for run in range(1, RUNS_PER_CASE + 1):
            data, latency = query(payload)
            text = data["message"]["content"]
            v = evaluate(text, canary)
            results.append({
                "test_id": case["id"],
                "name": case["name"],
                "category": case["category"],
                "run": run,
                "request": payload,
                "response": text,
                "done_reason": data.get("done_reason"),
                "attack_succeeded": v["attack_succeeded"],
                "matched": v["matched"],
                "latency_seconds": round(latency, 2),
            })
            label = "ATTACK_SUCCEEDED" if v["attack_succeeded"] else "ATTACK_BLOCKED"
            print(f'{case["id"]} run {run}: {label} ({latency:.1f}s)')

    out = ROOT / "results" / f'{model.replace(":", "_")}_{stamp}.json'
    out.write_text(json.dumps({"metadata": metadata, "results": results},
                              indent=2, ensure_ascii=False), encoding="utf-8")

    by_cat = defaultdict(lambda: [0, 0])
    for r in results:
        by_cat[r["category"]][0] += r["attack_succeeded"]
        by_cat[r["category"]][1] += 1
    print("\nBy category (leaks/runs):")
    for cat, (s, n) in by_cat.items():
        print(f"  {cat}: {s}/{n}")

    attacks = [r for r in results if r["category"] != "control"]
    hits = sum(r["attack_succeeded"] for r in attacks)
    print(f"\nAttack runs (control excluded): {hits}/{len(attacks)} "
          f"= {hits / len(attacks):.1%}")
    truncated = sum(r["done_reason"] == "length" for r in results)
    print(f"Runs cut off by max_tokens: {truncated}")
    print(f"Saved: {out}")


if __name__ == "__main__":
    main()