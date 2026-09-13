"""Turns a chat export into OpenAI chat-format JSONL.

The persona's messages become assistant turns, the other person's become user
turns, and 10% of conversations are held out for evaluation.
"""
import argparse
import json
import random
from collections import Counter

from ingest.adapters import available, get_adapter
from ingest.personas import ROOT, holdout_path, load_persona, report_path, turns_path


def filter_records(adapter, records, clone_sender, other_sender):
    kept = []
    dropped = Counter()
    for record in records:
        kind = adapter.classify(record)
        if kind != "text":
            dropped[kind] += 1
            continue
        sender = record["sender"]
        if sender == clone_sender:
            role = "assistant"
        elif sender == other_sender:
            role = "user"
        else:
            dropped["unknown_sender"] += 1
            continue
        kept.append({"role": role, "ts": record["ts"], "text": record["text"].rstrip()})
    return kept, dropped


# A gap of a few hours means a new conversation. I picked 6 hours after looking
# at the timestamp distribution, since it keeps a slow evening together but
# splits separate days apart.
def segment(records, gap_hours):
    gap_ms = gap_hours * 3600 * 1000
    conversations = []
    current = []
    for record in records:
        if current and record["ts"] - current[-1]["ts"] > gap_ms:
            conversations.append(current)
            current = []
        current.append(record)
    if current:
        conversations.append(current)
    return conversations


# People send three short messages in a row instead of one long one. If I
# trained on them separately the model would learn the wrong rhythm, so
# consecutive messages from one sender become a single turn.
def group_bursts(conversation):
    turns = []
    for record in conversation:
        if turns and turns[-1]["role"] == record["role"]:
            turns[-1]["parts"].append(record["text"])
        else:
            turns.append({"role": record["role"], "parts": [record["text"]]})
    return [{"role": t["role"], "content": "\n".join(t["parts"])} for t in turns]


# A conversation has to open with the other person and close with the persona,
# otherwise there is nothing to learn from the ends.
def trim(turns):
    while turns and turns[0]["role"] == "assistant":
        turns.pop(0)
    while turns and turns[-1]["role"] == "user":
        turns.pop()
    return turns


def build_records(conversations):
    records = []
    skipped = 0
    skipped_messages = 0
    for conversation in conversations:
        turns = trim(group_bursts(conversation))
        if len(turns) < 2:
            skipped += 1
            skipped_messages += len(conversation)
            continue
        records.append({"messages": turns})
    return records, skipped, skipped_messages


# tiktoken gives exact counts. If it is not installed I fall back to a rough
# chars/3.6 estimate and say so in the report rather than pretending.
def make_encoder():
    try:
        import tiktoken

        encoder = tiktoken.get_encoding("o200k_base")
        return (lambda s: len(encoder.encode(s))), True
    except Exception:
        return (lambda s: max(1, round(len(s) / 3.6))), False


def count_tokens(records, size):
    total = 0
    assistant = 0
    for record in records:
        for turn in record["messages"]:
            n = size(turn["content"]) + 4
            total += n
            if turn["role"] == "assistant":
                assistant += n
        total += 3
    return total, assistant


def write_jsonl(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--persona")
    parser.add_argument("--format", choices=available())
    parser.add_argument("--gap-hours", type=float)
    parser.add_argument("--holdout", type=float)
    parser.add_argument("--seed", type=int)
    args = parser.parse_args()

    cfg = load_persona(args.persona)
    persona = cfg["persona"]
    ingest_cfg = cfg.get("ingest", {})
    gap_hours = args.gap_hours or ingest_cfg.get("gap_hours", 6.0)
    holdout_frac = args.holdout or ingest_cfg.get("holdout", 0.10)
    seed = args.seed or ingest_cfg.get("seed", 7)

    adapter = get_adapter(args.format or cfg["chat"]["format"])
    raw, sources = adapter.load(ROOT / cfg["chat"]["path"])
    kept, dropped = filter_records(
        adapter, raw, cfg["chat"]["clone_sender"], cfg["chat"]["other_sender"]
    )
    conversations = segment(kept, gap_hours)
    records, skipped, skipped_messages = build_records(conversations)

    rng = random.Random(seed)
    order = list(range(len(records)))
    rng.shuffle(order)
    n_holdout = max(1, round(len(records) * holdout_frac)) if records else 0
    holdout_ids = set(order[:n_holdout])
    train = [r for i, r in enumerate(records) if i not in holdout_ids]
    holdout = [r for i, r in enumerate(records) if i in holdout_ids]

    write_jsonl(turns_path(persona), train)
    write_jsonl(holdout_path(persona), holdout)

    size, exact = make_encoder()
    total_tokens, assistant_tokens = count_tokens(records, size)
    train_tokens = count_tokens(train, size)[0]
    holdout_tokens = count_tokens(holdout, size)[0]

    roles = Counter()
    lengths = []
    for record in records:
        for turn in record["messages"]:
            roles[turn["role"]] += 1
            if turn["role"] == "assistant":
                lengths.append(len(turn["content"]))

    report = {
        "persona": persona,
        "format": adapter.name,
        "source_files": [str(p.relative_to(ROOT)) for p in sources],
        "gap_hours": gap_hours,
        "raw_messages": len(raw),
        "dropped": dict(dropped),
        "usable_messages": len(kept),
        "conversations_total": len(conversations),
        "conversations_skipped": skipped,
        "messages_lost_to_skips": skipped_messages,
        "conversations_kept": len(records),
        "conversations_train": len(train),
        "conversations_holdout": len(holdout),
        "turns_total": roles["user"] + roles["assistant"],
        "turns_user": roles["user"],
        "turns_assistant": roles["assistant"],
        "assistant_chars_mean": round(sum(lengths) / len(lengths), 1) if lengths else 0,
        "tokens_total": total_tokens,
        "tokens_assistant": assistant_tokens,
        "tokens_train": train_tokens,
        "tokens_holdout": holdout_tokens,
        "token_count_exact": exact,
        "outputs": {
            "train": str(turns_path(persona).relative_to(ROOT)),
            "holdout": str(holdout_path(persona).relative_to(ROOT)),
        },
    }
    report_path(persona).parent.mkdir(parents=True, exist_ok=True)
    report_path(persona).write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
