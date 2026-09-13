"""Scores a model against the holdout set on style, not content.

I compare the measured stats of generated replies to the measured stats of
the real replies for the same prompts.
"""
import argparse
import json
import random

from app import style
from app.client import ChatClient
from app.prompt import load_or_build
from ingest.personas import ROOT, holdout_path, load_persona, load_runtime, persona_dir


def sample_cases(records, limit, seed):
    cases = []
    for index, record in enumerate(records):
        turns = record["messages"]
        for i in range(len(turns) - 1):
            if turns[i]["role"] == "user" and turns[i + 1]["role"] == "assistant":
                cases.append(
                    {
                        "conversation": index,
                        "history": turns[: i + 1],
                        "reference": turns[i + 1]["content"],
                    }
                )
    rng = random.Random(seed)
    rng.shuffle(cases)
    return cases[:limit]


def profile_of(texts):
    if not texts:
        return {}
    return style.derive([{"messages": [{"role": "assistant", "content": t}]} for t in texts])


# Relative gap per metric, averaged. This is what told me the baseline was
# overusing emoji by 12x before I fixed the prompt.
def compare(reference_stats, generated_stats):
    keys = [
        ("messages_per_burst", "msgs per burst"),
        ("chars_median", "median chars"),
        ("pct_start_uppercase", "% start uppercase"),
        ("pct_end_period", "% end with period"),
        ("pct_with_emoji", "% with emoji"),
        ("pct_question", "% with question mark"),
    ]
    rows = []
    total = 0.0
    for key, label in keys:
        ref = reference_stats.get(key)
        gen = generated_stats.get(key)
        if ref is None or gen is None:
            continue
        scale = max(abs(ref), 1.0)
        delta = abs(gen - ref) / scale
        total += delta
        rows.append((label, ref, gen, delta))
    return rows, (total / len(rows) if rows else float("nan"))


def main():
    parser = argparse.ArgumentParser(
        description="Score a model against the holdout set on style fidelity."
    )
    parser.add_argument("--persona")
    parser.add_argument("--profile")
    parser.add_argument("--model")
    parser.add_argument("--limit", type=int, default=40)
    parser.add_argument("--seed", type=int, default=3)
    parser.add_argument("--save", action="store_true")
    args = parser.parse_args()

    persona_cfg = load_persona(args.persona)
    persona = persona_cfg["persona"]
    runtime_cfg = load_runtime()

    path = holdout_path(persona)
    if not path.exists():
        raise SystemExit(f"{path} missing; run python -m ingest.parse_chat first")
    records = style.load_records(path)
    cases = sample_cases(records, args.limit, args.seed)
    if not cases:
        raise SystemExit("no usable user/assistant pairs in the holdout set")

    client = ChatClient(runtime_cfg, model=args.model, profile=args.profile)
    system_prompt = load_or_build(persona_cfg, runtime_cfg)
    max_turns = runtime_cfg["chat"].get("max_history_turns", 24)

    print(f"persona:  {persona}")
    print(f"model:    {client.describe()}")
    print(f"cases:    {len(cases)} from {path.relative_to(ROOT)}")
    print("")

    generated = []
    references = []
    results = []
    for number, case in enumerate(cases, 1):
        messages = []
        if client.use_system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.extend(case["history"][-max_turns:])
        try:
            reply = client.complete(messages)
        except SystemExit as exc:
            print(f"  case {number}: failed ({exc})")
            continue
        generated.append(reply)
        references.append(case["reference"])
        results.append(
            {
                "prompt": case["history"][-1]["content"],
                "reference": case["reference"],
                "generated": reply,
            }
        )
        print(f"  {number}/{len(cases)}", end="\r")

    print(" " * 30, end="\r")
    if not generated:
        raise SystemExit("no successful generations")

    ref_stats = profile_of(references)
    gen_stats = profile_of(generated)
    rows, score = compare(ref_stats, gen_stats)

    real = f"{persona_cfg.get('display_name', persona)} (real)"
    print(f"{'metric':22} {real:>12} {'model':>12} {'gap':>8}")
    for label, ref, gen, delta in rows:
        print(f"{label:22} {ref:>12.1f} {gen:>12.1f} {delta:>7.1%}")
    print("")
    print(f"mean relative style gap: {score:.1%}  (lower is closer)")

    if args.save:
        out = persona_dir(persona) / f"eval_{client.profile}.json"
        out.write_text(
            json.dumps(
                {
                    "model": client.describe(),
                    "cases": len(generated),
                    "style_gap": score,
                    "reference_stats": ref_stats,
                    "generated_stats": gen_stats,
                    "samples": results[:20],
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        print(f"saved: {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
