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

## Summarise and publish todos with atomic commands

The summarisation workflow is split across three standalone commands so that
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

The Docker entrypoint can now build cron jobs from a TOML run plan.
By default it reads `/data/minerva-run-plan.toml`; override this with
`MINERVA_RUN_PLAN_FILE`.

If the file is missing, Minerva uses an in-memory default that preserves the
previous behaviour:

- `hourly` unit on `0 * * * *` with actions `fetch -> summarize -> publish`
- `daily` unit on `0 6 * * *` with actions `fetch -> summarize -> publish -> podcast`

Schema:

```toml
[global]
# optional default mode when a unit omits `mode`
mode = "hourly"
# default ordered action pipeline for units
actions = ["fetch", "summarize", "publish"]

[global.env]
# merged into process environment
MINERVA_LOG_LEVEL = "INFO"

[global.paths]
# shared paths (unit values override these)
prompts_dir = "/data/prompts"
# optional: defaults now resolve under /data/state/units/<unit-name>/
# unit_state_dir = "/data/state/units/hourly"
run_cache_file = "/data/state/hourly-run-marker.txt"

[global.options]
# maps to MINERVA_* option env vars
fetch_args = "--summary-group work"
summary_args = "--provider openrouter"

[global.providers]
# exported as MINERVA_PROVIDER_<NAME>
llm = "openrouter"

[global.tokens]
# exported as MINERVA_TOKEN_<NAME>
openrouter = "${OPENROUTER_API_KEY}"

[global.action.fetch]
# optional per-action args merged with unit action args
args = ["--collection", "sessions"]

[[unit]]
name = "hourly"
schedule = "0 * * * *"
enabled = true
mode = "hourly"

  [unit.options]
  hourly_fetch_args = "--skip-if-run"

[[unit]]
name = "daily"
schedule = "0 6 * * *"
enabled = true
mode = "daily"
actions = ["fetch", "summarize", "publish", "podcast"]

  [unit.paths]
  summary_file = "/data/state/daily-summary.txt"

  [unit.action.publish]
  args = ["--telegram-caption", "Daily digest"]
```

The entrypoint generates one cron line per enabled unit and executes:

```bash
/usr/local/bin/minerva-run unit <unit-name> --plan <plan-file>
```

You can inspect and validate the run plan directly from the CLI:

```bash
minerva-run list-units --plan /data/minerva-run-plan.toml
minerva-run validate --plan /data/minerva-run-plan.toml
```

`minerva-run hourly` and `minerva-run daily` are still accepted for backward
compatibility and are mapped to `unit hourly` / `unit daily`.


Actions are executed in order. Built-in action names are `fetch`, `summarize`, `publish`, and `podcast`.
If a required artifact is missing (for example summary without todo dump), Minerva skips that action and all downstream actions for that unit run.

### Per-unit state directory defaults and migration

By default, each unit now writes runtime artifacts under:

- `${MINERVA_STATE_DIR}/units/<unit-name>/`

This means the default files are now resolved as:

- `todo_dump.json`
- `todo_summary.txt`
- `todo-summary.wav`
- `summary_run_marker.txt`
- `random_podcast_topics.txt`

inside the selected unit directory.

This behavior keeps units isolated and avoids collisions between hourly/daily runs.

Migration notes:

- Existing setups that relied on shared single paths can keep the old behavior by setting explicit path overrides (for example `MINERVA_TODO_DUMP_FILE`, `MINERVA_SUMMARY_FILE`, `MINERVA_RUN_CACHE_FILE`, `MINERVA_SPEECH_FILE`, and `MINERVA_PODCAST_TOPIC_FILE`).
- You can also set `unit_state_dir` in `[global.paths]` or `[unit.paths]` to choose a custom base directory per unit.
- Minerva creates the unit directory (and any parent directories for overridden artifact paths) before actions execute.

Configuration is merged in this deterministic order:

1. built-in defaults
2. `[global]`
3. `[[unit]]`
4. environment overrides (if set)
5. CLI overrides

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
