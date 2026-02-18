# Minerva

This project provides a small command line utility for listing todo lists saved by
[Diana](https://github.com/fcrescio/Diana) in Firebase Firestore.

## Prerequisites

* Python 3.11+
* [uv](https://docs.astral.sh/uv/) for dependency management and execution
* Access to a Firebase service account JSON file with read permissions on the
  Firestore project used by Diana
* The `google-services.json` configuration file that ships with the mobile app
  (this file is **not** committed to the repository)

## Initial setup

1. Place the `google-services.json` file provided with Diana at the repository root.
2. Export the path to your service account credentials so the Firestore client can
   authenticate (or supply the path via the `--credentials` option when running the
   CLI):

   ```bash
   export GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json
   ```
3. Install the project dependencies (this will create an `uv.lock` file which should be
   committed):

   ```bash
   uv pip install -e .
   ```

## Usage

List all session documents stored in the default `sessions` collection and show their todo notes:

```bash
uv run list-todos
```

Command line options:

* `--config` – Path to `google-services.json` (defaults to the repository root).
* `--collection` – Name of the Firestore collection that stores the sessions
  (defaults to `sessions`).
* `--credentials` – Path to the service account JSON file. When omitted the CLI falls
  back to the `GOOGLE_APPLICATION_CREDENTIALS` environment variable.

Todo items are displayed in chronological order, with the closest `dueDate` first
and undated entries listed last. Each todo retains its associated metadata for
easy inspection.

## Summarize and publish todos with atomic commands

The summarization workflow is split across three standalone commands so that
each step can be automated independently or combined in custom pipelines. The
output of one command acts as the input for the next:

1. **Fetch todos from Firestore** – Export the selected session documents to a
   JSON file while tracking change markers for each session.

   ```bash
   uv run fetch-todos --output todo_dump.json
   ```

   * Filter sessions with `--summary-group`.
   * Skip regeneration when the todos have not changed by pointing
     `--run-cache-file` to a marker file and enabling `--skip-if-run`.

2. **Generate a natural language summary** – Feed the exported JSON dump to an
   LLM provider (OpenRouter by default) and store the generated narration text.

   ```bash
   uv run summarize-todos --todos todo_dump.json --output todo_summary.txt
   ```

   * Choose the provider with `--provider` (`openrouter` or `groq`) and override
     the model via `--model`.
   * Set the appropriate API key (`OPENROUTER_API_KEY` or `GROQ_API_KEY`).
   * Supply custom instructions with `--system-prompt-file`.
   * Run markers stored in the JSON dump are written back to the cache file so
     subsequent fetches can detect unchanged data.

3. **Publish the narration** – Convert the summary to speech using
   [fal.ai](https://fal.ai) and optionally post the audio to Telegram as a voice
   message.

   ```bash
   uv run publish-summary --summary todo_summary.txt --speech-output todo-summary.wav
   ```

   * Provide a `FAL_KEY` environment variable to enable speech synthesis, or
     pass an existing audio file with `--existing-audio`.
   * Upload the narration to Telegram with `--telegram` (enabled by default) and
     the `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` environment variables or the
     matching CLI flags. You can target multiple destinations by passing
     `--telegram-chat-id` more than once or via a comma-separated list. Each
     chat ID can be numeric or a channel handle (e.g. `@my_channel`).
     Converting audio for Telegram voice messages requires an `ffmpeg` binary
     available on your `PATH`.

Each command prints human-friendly progress information and can be composed with
other tooling or scheduled jobs to tailor the automation to your needs.



## Container run-plan configuration

The Docker entrypoint builds cron jobs from a TOML run plan. By default it reads
`/data/minerva-run-plan.toml`; override this path with `MINERVA_RUN_PLAN_FILE`.
If the file is missing, Minerva uses an in-memory default equivalent to:

- `hourly` on `0 * * * *` with `fetch -> summarize -> publish`
- `daily` on `0 6 * * *` with `fetch -> summarize -> publish -> podcast`

### Config schema reference

Top-level keys:

- `[global]`: defaults merged into every unit.
- `[[unit]]`: one scheduled run definition per block.

Supported keys:

```toml
[global]
mode = "hourly"                      # default mode when unit omits mode
actions = ["fetch", "summarize"]    # default action list (unit appends)

[global.env]                          # exported as plain env vars
MINERVA_LOG_LEVEL = "INFO"

[global.paths]                        # mapped to MINERVA_* path env vars
data_dir = "/data"
state_dir = "/data/state"
prompts_dir = "/data/prompts"
unit_state_dir = "/data/state/units/default"
run_cache_file = "/data/state/marker.txt"
summary_file = "/data/state/summary.txt"

[global.options]                      # mapped to MINERVA_* option env vars
fetch_args = "--summary-group work"
summary_args = "--provider openrouter"
daily_podcast_args = "--post-to-telegram"

[global.providers]                    # exported as MINERVA_PROVIDER_<NAME>
llm = "openrouter"

[global.tokens]                       # exported as MINERVA_TOKEN_<NAME>
openrouter = "${OPENROUTER_API_KEY}"

[global.action.fetch]                 # per-action args (merged global + unit)
args = ["--collection", "sessions"]

[[unit]]
name = "hourly"                      # unique unit name
schedule = "0 * * * *"               # 5-field cron expression
enabled = true
mode = "hourly"
actions = ["publish"]                # appended to global actions

  [unit.env]
  CUSTOM_TAG = "hourly"

  [unit.paths]
  summary_file = "/data/state/hourly-summary.txt"

  [unit.options]
  hourly_fetch_args = "--skip-if-run"

  [unit.action.publish]
  args = ["--telegram-caption", "Hourly update"]
```

Actions execute in order. Built-in actions are `fetch`, `summarize`, `publish`, and
`podcast`. For backward compatibility, run plans also accept the alias
`summarise`, which is normalized to `summarize`. If a required artifact is missing (for example, summary without todo dump),
Minerva skips that action and downstream actions for that unit run.

### Global defaults vs unit overrides

Merge order is deterministic:

1. Built-in defaults
2. `[global]`
3. `[[unit]]`
4. environment overrides
5. CLI overrides

Behavior by value type:

- Scalars (`mode`, individual paths/options/env values): unit overrides global.
- Lists (`actions`, action `args`): appended in order `global + unit`.
- Maps (`tokens`, `providers`, nested tables): merged per key, unit wins on conflicts.

Example:

```toml
[global]
actions = ["fetch", "summarize"]

[global.action.summarize]
args = ["--provider", "openrouter"]

[[unit]]
name = "daily"
schedule = "0 6 * * *"
actions = ["publish", "podcast"]

  [unit.action.summarize]
  args = ["--model", "meta-llama/llama-3.3-70b-instruct"]
```

Resolved `daily` action chain becomes:
`fetch -> summarize -> publish -> podcast`, and summarize args become:
`--provider openrouter --model meta-llama/llama-3.3-70b-instruct`.

### Run a custom plan in Docker

A ready-to-edit example is included at:
`docker/examples/minerva-run-plan.toml`.

Mount your plan and run Minerva with it:

```bash
docker run --rm \
  -e OPENROUTER_API_KEY="$OPENROUTER_API_KEY" \
  -e TELEGRAM_BOT_TOKEN="$TELEGRAM_BOT_TOKEN" \
  -e TELEGRAM_CHAT_ID="$TELEGRAM_CHAT_ID" \
  -v "$PWD/docker/examples/minerva-run-plan.toml:/data/minerva-run-plan.toml:ro" \
  -v "$PWD/docker/prompts:/data/prompts:ro" \
  ghcr.io/<org>/minerva:latest
```

Or choose any in-container path:

```bash
docker run --rm \
  -e MINERVA_RUN_PLAN_FILE=/config/custom-plan.toml \
  -v "$PWD/my-plan.toml:/config/custom-plan.toml:ro" \
  ghcr.io/<org>/minerva:latest
```

You can inspect and validate before scheduling:

```bash
minerva-run list-units --plan /data/minerva-run-plan.toml
minerva-run validate --plan /data/minerva-run-plan.toml
```

`minerva-run hourly` and `minerva-run daily` remain backward compatible aliases
for `minerva-run unit hourly` / `minerva-run unit daily`.

### Migration guide: legacy env vars -> plan keys

Use this mapping when migrating existing Docker setups:

| Legacy env var | New run-plan key |
|---|---|
| `MINERVA_DATA_DIR` | `[global.paths].data_dir` |
| `MINERVA_STATE_DIR` | `[global.paths].state_dir` |
| `MINERVA_UNIT_STATE_DIR` | `[global.paths].unit_state_dir` (or `[unit.paths]`) |
| `MINERVA_PROMPTS_DIR` | `[global.paths].prompts_dir` |
| `MINERVA_RUN_CACHE_FILE` | `[global.paths].run_cache_file` |
| `MINERVA_TODO_DUMP_FILE` | `[global.paths].todo_dump_file` |
| `MINERVA_SUMMARY_FILE` | `[global.paths].summary_file` |
| `MINERVA_SPEECH_FILE` | `[global.paths].speech_file` |
| `MINERVA_PODCAST_TEXT_FILE` | `[global.paths].podcast_text_file` |
| `MINERVA_PODCAST_AUDIO_FILE` | `[global.paths].podcast_audio_file` |
| `MINERVA_PODCAST_TOPIC_FILE` | `[global.paths].podcast_topic_file` |
| `MINERVA_CONFIG_PATH` | `[global.paths].config_path` |
| `MINERVA_FETCH_ARGS` | `[global.options].fetch_args` |
| `MINERVA_SUMMARY_ARGS` | `[global.options].summary_args` |
| `MINERVA_PUBLISH_ARGS` | `[global.options].publish_args` |
| `MINERVA_SHARED_ARGS` | `[global.options].shared_args` |
| `MINERVA_PODCAST_ARGS` | `[global.options].podcast_args` |
| `MINERVA_PODCAST_TELEGRAM_ARGS` | `[global.options].podcast_telegram_args` |
| `MINERVA_PODCAST_LANGUAGE` | `[global.options].podcast_language` |
| `MINERVA_HOURLY_FETCH_ARGS` | `[unit.options].hourly_fetch_args` (typically `name = "hourly"`) |
| `MINERVA_HOURLY_SUMMARY_ARGS` | `[unit.options].hourly_summary_args` |
| `MINERVA_HOURLY_PUBLISH_ARGS` | `[unit.options].hourly_publish_args` |
| `MINERVA_DAILY_FETCH_ARGS` | `[unit.options].daily_fetch_args` (typically `name = "daily"`) |
| `MINERVA_DAILY_SUMMARY_ARGS` | `[unit.options].daily_summary_args` |
| `MINERVA_DAILY_PUBLISH_ARGS` | `[unit.options].daily_publish_args` |
| `MINERVA_DAILY_PODCAST_ARGS` | `[unit.options].daily_podcast_args` |

### Secret handling recommendations

- Put **non-secret runtime settings** in the run plan (schedules, actions, file paths,
  model/provider selection, prompt arguments).
- Keep **secrets in environment variables** (for example `OPENROUTER_API_KEY`,
  `GROQ_API_KEY`, `FAL_KEY`, `TELEGRAM_BOT_TOKEN`) and reference them from plan
  tokens/secrets if needed (`"${OPENROUTER_API_KEY}"`).
- Mount plan files as read-only volumes and keep them in version control only when they
  contain no sensitive material.
- Prefer platform secret stores (Docker/Kubernetes/CI secret managers) for tokens,
  then inject them into the container environment at runtime.

## Generate a random podcast episode

Create a random podcast script, optionally narrate it, and publish it to Telegram:

```bash
uv run generate-podcast --output random_podcast.txt
```

Useful options:

* `--prompt-template-file` – Load the podcast user prompt from an external `.txt` template.
  Supported placeholders are `{language}`, `{language_clause}`, `{previous_topics}`, and
  `{previous_topics_clause}`.
* `--topic-history-file` / `--topic-history-limit` – Track and inject recently used topics so
  the next run can avoid repeating subjects.
* `--speech` / `--no-speech` – Enable or disable speech synthesis for the generated script.
* `--telegram-chat-id` (repeatable or comma-separated) – Publish to one or more Telegram chats.
