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
     matching CLI flags. The chat ID can be numeric or a channel handle (e.g.
     `@my_channel`). Converting audio for Telegram voice messages requires an
     `ffmpeg` binary available on your `PATH`.

Each command prints human-friendly progress information and can be composed with
other tooling or scheduled jobs to tailor the automation to your needs.
