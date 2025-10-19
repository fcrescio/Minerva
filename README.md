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

List all todo lists stored in the default `todoLists` collection:

```bash
uv run list-todos
```

Command line options:

* `--config` – Path to `google-services.json` (defaults to the repository root).
* `--collection` – Name of the Firestore collection that stores the todo lists
  (defaults to `todoLists`).
* `--credentials` – Path to the service account JSON file. When omitted the CLI falls
  back to the `GOOGLE_APPLICATION_CREDENTIALS` environment variable.

The command prints a table for each todo list document and any nested subcollections
(e.g. individual todo items) that belong to it.
