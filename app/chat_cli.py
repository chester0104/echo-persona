"""Terminal chat. Each reply is printed and, if a voice exists, spoken.
"""
import argparse
import sys

from app.client import ChatClient
from app.prompt import dynamic_context, load_or_build
from ingest.personas import load_persona, load_runtime, prompt_path

BANNER = """echo-persona  |  {who}
model: {model}
prompt: {tokens} cached prefix  |  {voice}
commands: /reset  /usage  /prompt  /voice on|off  /quit
"""


# Keep the last N turns but never start on an assistant message, since the
# model expects the user to go first.
def trim_history(history, max_turns):
    if max_turns <= 0 or len(history) <= max_turns:
        return history
    trimmed = history[-max_turns:]
    while trimmed and trimmed[0]["role"] != "user":
        trimmed.pop(0)
    return trimmed


def prompt_tokens(text):
    try:
        import tiktoken

        return f"{len(tiktoken.get_encoding('o200k_base').encode(text)):,} tokens"
    except Exception:
        return f"{len(text):,} chars"


# Voice is optional. If the module or the key is missing I just run text only
# and say so once.
def make_speaker(persona_cfg, runtime_cfg, enabled):
    if not enabled:
        return None
    try:
        from app.tts import Speaker
    except ImportError:
        return None
    try:
        return Speaker(persona_cfg, runtime_cfg)
    except SystemExit as exc:
        print(f"[voice disabled: {exc}]")
        return None


def main():
    parser = argparse.ArgumentParser(description="Chat with a cloned persona.")
    parser.add_argument("--persona")
    parser.add_argument("--model")
    parser.add_argument("--base-url")
    parser.add_argument("--profile")
    parser.add_argument("--rebuild-prompt", action="store_true")
    parser.add_argument("--no-voice", action="store_true")
    parser.add_argument("--once")
    args = parser.parse_args()

    persona_cfg = load_persona(args.persona)
    runtime_cfg = load_runtime()
    system_prompt = load_or_build(persona_cfg, runtime_cfg, rebuild=args.rebuild_prompt)

    if not prompt_path(persona_cfg["persona"]).exists():
        raise SystemExit("system prompt missing; run: python -m app.prompt --rebuild")

    client = ChatClient(
        runtime_cfg, model=args.model, base_url=args.base_url, profile=args.profile
    )
    voice_wanted = runtime_cfg.get("tts", {}).get("enabled", False) and not args.no_voice
    speaker = make_speaker(persona_cfg, runtime_cfg, voice_wanted)

    max_turns = runtime_cfg["chat"].get("max_history_turns", 24)
    history = []

    def respond(text):
        history.append({"role": "user", "content": text})
        messages = []
        if client.use_system_prompt:
            messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "system", "content": dynamic_context(persona_cfg)})
        messages.extend(trim_history(history, max_turns))
        reply = client.complete(messages)
        history.append({"role": "assistant", "content": reply})
        return reply

    if args.once:
        reply = respond(args.once)
        print(reply)
        if speaker:
            speaker.speak(reply)
        return

    voice_state = "voice on" if speaker else "voice off"
    print(
        BANNER.format(
            who=persona_cfg.get("display_name", persona_cfg["persona"]),
            model=client.describe(),
            tokens=prompt_tokens(system_prompt),
            voice=voice_state,
        )
    )

    while True:
        try:
            line = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line:
            continue
        if line in ("/quit", "/exit", "/q"):
            break
        if line == "/reset":
            history.clear()
            print("[history cleared]")
            continue
        if line == "/usage":
            print(f"[{client.last_usage or 'no calls yet'}]")
            continue
        if line == "/prompt":
            print(f"[{prompt_path(persona_cfg['persona'])}]")
            print(f"[{prompt_tokens(system_prompt)}, {len(history)} live turns]")
            continue
        if line.startswith("/voice"):
            want = line.split()[-1] if len(line.split()) > 1 else "on"
            speaker = make_speaker(persona_cfg, runtime_cfg, want != "off")
            print(f"[voice {'on' if speaker else 'off'}]")
            continue

        try:
            reply = respond(line)
        except SystemExit as exc:
            print(f"[error: {exc}]", file=sys.stderr)
            history.pop()
            continue

        name = persona_cfg.get("display_name", persona_cfg["persona"]).lower()
        for part in reply.split("\n"):
            if part.strip():
                print(f"{name}> {part}")
        if speaker:
            try:
                speaker.speak(reply)
            except SystemExit as exc:
                print(f"[voice error: {exc}]", file=sys.stderr)


if __name__ == "__main__":
    main()
