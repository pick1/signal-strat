#!/usr/bin/env python3
"""
SIGNAL Model Benchmark
======================
Tests candidate LLMs against real article content to determine which model
performs best for the SIGNAL analysis pipeline.

Outputs a comparison table and saves full results to data/benchmark_results.json.
"""

import json
import sys
import time
import argparse
from pathlib import Path
from datetime import datetime
from collections import Counter

PROJECT_DIR = Path(__file__).resolve().parent.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from signald.config import DB_PATH
from signald.analyzer import analyze_with_ollama, parse_json_result

# ─── Test Articles ───────────────────────────────────────────────────────────
# Real articles from today's feed — diverse content types

TEST_ARTICLES = [
    {
        "id": "test_1",
        "source_hint": "article",
        "title": "Using AI to write better code more slowly",
        "content": """Nolan Lawson argues that using AI to write code often leads to writing code more slowly, not faster. The key insight is that AI-generated code requires careful review, validation, and often significant refactoring, which can take longer than writing the code yourself. However, the quality can be higher because you're spending more time thinking about the architecture and edge cases. Lawson suggests treating AI as a rubber ducking partner rather than a code generator, and that the real productivity gain comes from using AI to explore multiple approaches quickly rather than to write final code. The article emphasizes that the bottleneck shifts from writing code to understanding and validating code, which is actually a more valuable skill.""",
    },
    {
        "id": "test_2",
        "source_hint": "article",
        "title": "Fully in-browser container builds",
        "content": """Ochagavia demonstrates a technique for running container builds entirely within the browser using WebAssembly. The approach uses a custom build of the Docker engine compiled to WebAssembly via emscripten, running inside a Service Worker. This enables container builds without any server-side infrastructure — the entire build process happens client-side. Currently supports basic Dockerfile commands (FROM, RUN, COPY, CMD) with Alpine Linux as the base image. Build performance is approximately 10x slower than native, but for CI/CD pipelines this could be interesting for distributing build workloads to client machines rather than centralizing them on build servers.""",
    },
    {
        "id": "test_3",
        "source_hint": "tweet",
        "title": "Norway's Huawei flash storage for LLM training",
        "content": """Norway has deployed 2 petabytes of Huawei flash storage for LLM training infrastructure. This is notable because Norway is generally considered a Western ally, yet they're using Chinese-manufactured storage for what is presumably sensitive AI training workloads. The storage array is Huawei's OceanStor Pacific series, which supports NVMe over Fabrics and can deliver up to 20M IOPS. The deployment raises questions about data sovereignty and supply chain security in the AI infrastructure space. Blocks & Files reports this as part of a broader trend of Chinese storage vendors gaining traction in the AI/ML market despite geopolitical tensions.""",
    },
]

# ─── Candidate Models ────────────────────────────────────────────────────────
CANDIDATES = [
    "gemma4:e4b",
    "qwen3:14b",
    "qwen3:latest",
    "deepseek-r1:14b",
    "deepseek-r1:8b",
    "qwen2.5:7b",
]


# ─── Benchmark ───────────────────────────────────────────────────────────────


def score_result(result: dict, expected_id: str) -> dict:
    """Score a model's output for quality metrics."""
    scores = {}
    issues = []

    # 1. JSON validity
    if not result:
        scores["valid_json"] = False
        issues.append("no result returned")
        return {"score": 0, "issues": issues}
    scores["valid_json"] = True

    # 2. Has required fields
    required = ["title", "category", "tags", "summary", "verdict", "confidence", "next_steps"]
    missing = [f for f in required if not result.get(f)]
    scores["missing_fields"] = missing
    if missing:
        issues.append(f"missing fields: {', '.join(missing)}")

    # 3. Category is valid
    valid_cats = {"viable", "work", "vaporware", "redundant", "watch", "mixed"}
    cat = result.get("category", "")
    scores["valid_category"] = cat in valid_cats
    if not scores["valid_category"]:
        issues.append(f"invalid category: {cat}")

    # 4. Confidence is in range
    conf = result.get("confidence", 0)
    scores["confidence_valid"] = 0 <= conf <= 1
    if not scores["confidence_valid"]:
        issues.append(f"confidence out of range: {conf}")

    # 5. Tags are a list of strings
    tags = result.get("tags", [])
    scores["tags_valid"] = isinstance(tags, list) and len(tags) >= 1
    if not scores["tags_valid"]:
        issues.append(f"tags issue: {type(tags).__name__}")

    # 6. next_steps is a list
    steps = result.get("next_steps", [])
    scores["steps_valid"] = isinstance(steps, list) and len(steps) >= 1
    if not scores["steps_valid"]:
        issues.append(f"steps issue: {type(steps).__name__}")

    # 7. Title is non-trivial
    title = result.get("title", "")
    scores["title_valid"] = len(title) > 5
    if not scores["title_valid"]:
        issues.append("title too short or missing")

    # Calculate overall
    checks = [
        scores["valid_json"],
        scores["valid_category"],
        scores["confidence_valid"],
        scores["tags_valid"],
        scores["steps_valid"],
        scores["title_valid"],
    ]
    total_checks = len(checks)
    passed = sum(1 for c in checks if c)
    scores["quality"] = round(passed / total_checks * 100)

    return {
        "score": scores["quality"],
        "scores": scores,
        "issues": issues,
        "result": result,
    }


def run_test(model: str, article: dict) -> dict:
    """Run a single model on a single article."""
    print(f"    Testing {model} on '{article['id']}'...", end=" ", flush=True)

    start = time.time()
    try:
        result = analyze_with_ollama(
            article["content"],
            article["source_hint"],
            model,
        )
        elapsed = time.time() - start
    except Exception as e:
        elapsed = time.time() - start
        return {
            "model": model,
            "article_id": article["id"],
            "article_title": article["title"],
            "status": "error",
            "error": str(e),
            "time_seconds": round(elapsed, 2),
        }

    scoring = score_result(result, article["id"])
    print(f"{elapsed:.1f}s  score={scoring['score']}/100")

    return {
        "model": model,
        "article_id": article["id"],
        "article_title": article["title"],
        "status": "ok",
        "time_seconds": round(elapsed, 2),
        "category": result.get("category", "unknown"),
        "confidence": result.get("confidence", 0),
        "title": result.get("title", ""),
        "quality_score": scoring["score"],
        "issues": scoring["issues"],
        "detail": scoring["scores"],
    }


def main():
    parser = argparse.ArgumentParser(description="SIGNAL Model Benchmark")
    parser.add_argument("--models", nargs="*", default=None,
                        help="Models to test (default: all candidates)")
    parser.add_argument("--articles", nargs="*", default=None,
                        help="Article IDs to test (default: all)")
    args = parser.parse_args()

    models_to_test = args.models if args.models else CANDIDATES
    articles_to_test = [a for a in TEST_ARTICLES
                        if not args.articles or a["id"] in args.articles]

    print(f"\n═══ SIGNAL Model Benchmark ═══")
    print(f"Models: {', '.join(models_to_test)}")
    print(f"Articles: {', '.join(a['id'] for a in articles_to_test)}")
    print(f"Total runs: {len(models_to_test) * len(articles_to_test)}")
    print()

    results = []
    for model in models_to_test:
        for article in articles_to_test:
            r = run_test(model, article)
            results.append(r)
            # Brief pause between runs to avoid hammering Ollama
            time.sleep(2)

    # ─── Summary ───────────────────────────────────────────────────────────
    print(f"\n\n═══ RESULTS ═══\n")

    # Per-model aggregation
    from collections import defaultdict
    by_model = defaultdict(list)
    for r in results:
        by_model[r["model"]].append(r)

    header = f"{'Model':<22} {'Avg Time':>9} {'Avg Score':>10} {'OK':>4} {'Err':>4}"
    print(header)
    print("-" * len(header))

    model_summaries = []
    for model in models_to_test:
        runs = by_model.get(model, [])
        ok_runs = [r for r in runs if r["status"] == "ok"]
        err_runs = [r for r in runs if r["status"] == "error"]

        avg_time = sum(r["time_seconds"] for r in runs) / len(runs) if runs else 0
        avg_score = sum(r["quality_score"] for r in ok_runs) / len(ok_runs) if ok_runs else 0

        print(f"{model:<22} {avg_time:>7.1f}s  {avg_score:>8.0f}/100  {len(ok_runs):>4}  {len(err_runs):>4}")

        model_summaries.append({
            "model": model,
            "avg_time_seconds": round(avg_time, 1),
            "avg_quality_score": round(avg_score),
            "ok_runs": len(ok_runs),
            "err_runs": len(err_runs),
        })

    # ─── Category Distribution ─────────────────────────────────────────────
    print(f"\n── Category Distribution ──")
    for model in models_to_test:
        runs = by_model.get(model, [])
        cats = Counter(r.get("category", "?") for r in runs)
        print(f"  {model:<22} {dict(cats)}")

    # ─── Issues Summary ────────────────────────────────────────────────────
    print(f"\n── Common Issues ──")
    all_issues = Counter()
    for r in results:
        for issue in r.get("issues", []):
            all_issues[issue] += 1
    for issue, count in all_issues.most_common():
        print(f"  {issue}: {count}x")

    # ─── Save Results ──────────────────────────────────────────────────────
    output = {
        "timestamp": datetime.now().isoformat(),
        "config": {
            "models_tested": models_to_test,
            "articles": [{"id": a["id"], "title": a["title"]} for a in articles_to_test],
        },
        "model_summaries": model_summaries,
        "results": results,
    }

    results_path = PROJECT_DIR / "data" / "benchmark_results.json"
    with open(results_path, "w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\nFull results saved to data/benchmark_results.json")


if __name__ == "__main__":
    main()
