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

## Summarise todos with an LLM

The project also exposes a processing pipeline that pushes the retrieved session
todo lists to an LLM provider (OpenRouter by default) and prints the generated
summary. When available, the summary is additionally synthesised into a speech
track using [fal.ai](https://fal.ai) and saved to `todo-summary.wav` in the
current directory. The generated audio can optionally be uploaded to a Telegram
channel by providing bot credentials:

```bash
uv run summarize-todos
```

Additional options mirror those of `list-todos`. You can select the provider with
`--provider` (`openrouter` or `groq`) and override the target model with
`--model`. Depending on the provider you must set either `OPENROUTER_API_KEY` or
`GROQ_API_KEY`. Optional `OPENROUTER_APP_URL` and `OPENROUTER_APP_TITLE`
variables allow identifying your integration in OpenRouter dashboards. To
replace the default LLM instructions, point `--system-prompt-file` to a text file
whose contents should be used as the system prompt when generating the summary.
To receive the audio summary you must also export a `FAL_KEY` with your fal.ai API
token. To post the generated narration to Telegram as a voice message, enable the
`--telegram` flag and supply bot credentials via the `--telegram-token` and
`--telegram-chat-id` options or the `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`
environment variables. The chat ID can be the numeric identifier or the channel
handle (e.g. `@my_channel`). Converting the generated WAV file to the Opus
format used by Telegram voice messages requires an `ffmpeg` binary available in
your `PATH`.

The command prints a table for each todo list document and any nested subcollections
(e.g. individual todo items) that belong to it.
