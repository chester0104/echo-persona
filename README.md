# echo-persona

I built this to clone how a specific person texts, then have the clone talk back in their actual voice. You give it a chat export and a few minutes of audio, and you get a chatbot that types like them, holds their opinions, and speaks with a cloned copy of their voice. There is a SvelteKit site on top so other people can try it.

The two personas that ship with it are me and a friend. Both of us agreed to this. If you want to clone anyone else, get their consent first. I put more on that in [LICENSE](LICENSE).

## What it does

I did not want to guess at anyone's texting style, so the pipeline measures it. It counts messages per burst, median message length, how often they capitalise, how often they use emoji, how often they push back or swear or send a one word reply, and which words are distinctively theirs. Those numbers go into a system prompt as instructions. I found that stating the measured rates directly works far better than describing the style in words. My first prompt had the model using emoji in 25% of messages when the real person uses them in 2%. Adding "about 1 message in 24 has an emoji" fixed it.

On top of the style it also knows who they are: what they study, their siblings and close friends, what shows they like, what they complain about. That part comes from a one time pass over their messages plus whatever I added by hand.

## Setup

You need Python 3.11+, ffmpeg on your PATH, and Node 20+ if you want the site.

```
pip install requests tiktoken
cp .env.example .env
```

Put your keys in `.env`. I never print them or pass them on the command line.

```
OPENAI_API_KEY=""
ELEVENLABS_API_KEY=""
TOGETHER_API_KEY=""
```

Drop a chat export in `chat/<format>/<name>/` and any audio in `voice/<name>/`, then:

```
python clone.py <name>
```

That parses the chat, builds the prompt, converts and denoises the audio, and creates the ElevenLabs clone. It works out which participant is the person being cloned by matching the folder name, which handles Instagram's styled unicode display names.

Then talk to them:

```
python -m app.chat_cli --persona <name>
```

## The stages, if you want to run them one at a time

| stage | command |
| --- | --- |
| parse the chat | `python -m ingest.parse_chat --persona <name>` |
| build the prompt | `python -m app.prompt --persona <name> --rebuild` |
| convert audio | `python -m app.convert_voice --persona <name>` |
| denoise | `python -m app.denoise_voice --persona <name>` |
| clone the voice | `python -m app.clone_voice --persona <name>` |
| derive interests | `python -m app.interests --persona <name>` |
| score against holdout | `python -m app.evaluate --persona <name>` |
| fine tune on Together | `python -m app.finetune_together --persona <name> --start` |

`inspect_chat` is worth running first on any new export. It prints the sender strings so you can copy them exactly.

## Integrations

**OpenAI compatible chat.** The default model is `gpt-5.6-terra`, but it is just a base URL and model name in `config/runtime.json`. I kept the example block byte identical between calls so the prompt cache hits. The site uses a smaller card without examples, which drops the cost by about 20x and keeps message text off the server.

**ElevenLabs instant voice cloning.** One multipart POST to `/v1/voices/add`. The returned `voice_id` is saved to `config/voice_id.json` and checked before every run so I never make a duplicate. The key needs Text to Speech, Voices write, Models access, User access, and History read. Nothing else. Instant cloning needs a paid plan. Generated audio is cached by a hash of the text plus voice settings, so repeating a line costs nothing.

**Together AI fine tuning.** LoRA on Qwen3 8B. The script validates the JSONL and previews the job, and does nothing unless you pass `--start`. Switching the chat to the fine tuned model is one profile change in `config/runtime.json`.

**SvelteKit site.** TypeScript, Tailwind, deployed on Vercel. The personas are loaded from an environment variable that holds only the measured style cards, never the transcripts. There is a per IP rate limit and a daily cap, and an admin panel behind a token.

**Google Authenticator private mode.** Each persona has a public card and a private one. The private card includes the heavier topics. It unlocks with a rotating six digit code, which I implemented as standard TOTP with node's crypto so there is no library in the path of a secret. Every person gets their own secret, so I can revoke one without touching the others:

```
python -m app.totp_setup --grant friend --days 30
python -m app.totp_setup --revoke friend
```

## Updating things that change

Interests change, so there is a command for the current phase:

```
python -m app.now <name> "reading a lot of sci-fi lately"
```

That rebuilds the prompt and refreshes every env file. Then `python -m app.env_sync` keeps `web/.env.local`, `web/.env.example`, and `VERCEL_ENV.txt` in agreement, because I had them drift once and it cost me an evening.

## Privacy

`chat/`, `voice/`, `data/`, every `.env`, the voice id, and the TOTP grants are all gitignored. The site never receives conversation data. Check with `git status --porcelain` before your first push.

## Layout

```
clone.py               one command pipeline
ingest/                export adapters, parser, persona config
app/                   prompt, chat, audio, voice, fine tune, eval
config/personas/       one JSON per person
web/                   the SvelteKit site
```
