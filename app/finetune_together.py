"""Uploads the training data to Together and starts a LoRA fine tune.
"""
import argparse
import json

import requests

from ingest.personas import ROOT, holdout_path, load_persona, load_runtime, require_key, turns_path

API_ROOT = "https://api.together.xyz/v1"


# Together rejects malformed JSONL with an unhelpful error, so I check it
# locally first.
def validate(path):
    problems = []
    rows = 0
    with path.open(encoding="utf-8") as handle:
        for number, line in enumerate(handle, 1):
            line = line.strip()
            if not line:
                continue
            rows += 1
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                problems.append(f"line {number}: invalid json ({exc})")
                continue
            messages = record.get("messages")
            if not isinstance(messages, list) or len(messages) < 2:
                problems.append(f"line {number}: needs a messages list with 2+ turns")
                continue
            roles = [m.get("role") for m in messages]
            if any(r not in ("system", "user", "assistant") for r in roles):
                problems.append(f"line {number}: unexpected role in {roles}")
            if "assistant" not in roles:
                problems.append(f"line {number}: no assistant turn to train on")
            if any(not (m.get("content") or "").strip() for m in messages):
                problems.append(f"line {number}: empty content in a turn")
    return rows, problems


def upload(key, path, timeout=600):
    with path.open("rb") as handle:
        response = requests.post(
            f"{API_ROOT}/files",
            headers={"Authorization": f"Bearer {key}"},
            files={"file": (path.name, handle, "application/jsonl")},
            data={"purpose": "fine-tune", "file_name": path.name},
            timeout=timeout,
        )
    if response.status_code not in (200, 201):
        raise SystemExit(f"upload failed {response.status_code}: {response.text[:600]}")
    return response.json()


def build_job(cfg, training_file_id, validation_file_id, suffix):
    lora = cfg.get("lora", {})
    job = {
        "training_file": training_file_id,
        "model": cfg.get("base_model", "Qwen/Qwen3-8B"),
        "n_epochs": lora.get("n_epochs", 3),
        "batch_size": lora.get("batch_size", 8),
        "learning_rate": lora.get("learning_rate", 1e-4),
        "suffix": suffix,
        "training_type": {
            "type": "Lora",
            "lora_r": lora.get("lora_r", 32),
            "lora_alpha": lora.get("lora_alpha", 64),
            "lora_dropout": lora.get("lora_dropout", 0.05),
            "lora_trainable_modules": lora.get("trainable_modules", "all-linear"),
        },
        "train_on_inputs": False,
    }
    if validation_file_id:
        job["validation_file"] = validation_file_id
        job["n_evals"] = lora.get("n_evals", 3)
    return job


def launch(key, job, timeout=120):
    response = requests.post(
        f"{API_ROOT}/fine-tunes",
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
        data=json.dumps(job).encode("utf-8"),
        timeout=timeout,
    )
    if response.status_code not in (200, 201):
        raise SystemExit(f"fine-tune failed {response.status_code}: {response.text[:600]}")
    return response.json()


def main():
    parser = argparse.ArgumentParser(
        description="Upload training data to Together AI and start a LoRA fine-tune."
    )
    parser.add_argument("--persona")
    parser.add_argument("--start", action="store_true", help="actually upload and launch")
    parser.add_argument("--no-validation", action="store_true")
    parser.add_argument("--suffix")
    args = parser.parse_args()

    persona_cfg = load_persona(args.persona)
    persona = persona_cfg["persona"]
    runtime_cfg = load_runtime()
    cfg = runtime_cfg.get("finetune", {})

    train = turns_path(persona)
    holdout = holdout_path(persona)
    if not train.exists():
        raise SystemExit(f"{train} missing; run python -m ingest.parse_chat first")

    rows, problems = validate(train)
    print(f"training file:   {train.relative_to(ROOT)}  ({rows} conversations)")
    if holdout.exists() and not args.no_validation:
        vrows, vproblems = validate(holdout)
        print(f"validation file: {holdout.relative_to(ROOT)}  ({vrows} conversations)")
        problems += vproblems
    print(f"base model:      {cfg.get('base_model', 'Qwen/Qwen3-8B')}")
    print(f"lora:            {json.dumps(cfg.get('lora', {}))}")

    if problems:
        print("\nvalidation problems:")
        for problem in problems[:20]:
            print(f"  {problem}")
        raise SystemExit(f"{len(problems)} problem(s) found; fix before uploading")
    print("validation: ok")

    suffix = args.suffix or f"echo-{persona}"
    job_preview = build_job(cfg, "<training_file_id>", "<validation_file_id>", suffix)
    print("\njob that would be submitted:")
    print(json.dumps(job_preview, indent=2))

    # Nothing is uploaded and no job starts without --start. I wanted to be
    # able to preview the exact job body without spending anything.
    if not args.start:
        print("\nnothing was uploaded and no job was started.")
        print("to run it for real:")
        print(f"  python -m app.finetune_together --persona {persona} --start")
        return

    key = require_key(cfg.get("api_key_env", "TOGETHER_API_KEY"))
    print("\nuploading training file...")
    train_file = upload(key, train)
    train_id = train_file.get("id")
    print(f"  training_file: {train_id}")

    validation_id = None
    if holdout.exists() and not args.no_validation:
        print("uploading validation file...")
        validation_id = upload(key, holdout).get("id")
        print(f"  validation_file: {validation_id}")

    job = build_job(cfg, train_id, validation_id, suffix)
    result = launch(key, job)
    job_id = result.get("id")
    print(f"\nfine-tune job: {job_id}")
    print(f"output model:  {result.get('model_output_name', '(pending)')}")
    print("\nwatch it with:")
    print(f"  curl -H \"Authorization: Bearer $TOGETHER_API_KEY\" {API_ROOT}/fine-tunes/{job_id}")
    print("\nwhen it finishes, point the chat at it by editing config/runtime.json:")
    print('  "chat": { "profile": "together-finetuned" }')


if __name__ == "__main__":
    main()
