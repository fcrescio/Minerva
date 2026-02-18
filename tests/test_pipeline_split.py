from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

try:
    from minerva.persistence import (
        deserialise_todo,
        deserialise_todo_list,
        read_run_markers,
        serialise_todo,
        serialise_todo_list,
        write_run_markers,
    )
    from minerva.todos import Todo, TodoList
except ModuleNotFoundError as exc:  # pragma: no cover - environment dependent
    PERSISTENCE_IMPORT_ERROR = exc
    deserialise_todo = None
    deserialise_todo_list = None
    read_run_markers = None
    serialise_todo = None
    serialise_todo_list = None
    write_run_markers = None
    Todo = None
    TodoList = None
else:
    PERSISTENCE_IMPORT_ERROR = None

try:
    from minerva import pipeline
    from minerva.llm import (
        generate_random_podcast_script,
        summarise_with_openrouter,
        summarize_with_openrouter,
    )
    from minerva.media import synthesise_speech
    from minerva.notifications import post_text_to_telegram
    from minerva.prompts import build_prompt, load_system_prompt
except ModuleNotFoundError as exc:  # pragma: no cover - environment dependent
    pipeline = None
    IMPORT_ERROR = exc
else:
    IMPORT_ERROR = None


@unittest.skipIf(pipeline is None, f"Skipping compatibility import checks: {IMPORT_ERROR}")
class PipelineCompatibilityFacadeTests(unittest.TestCase):
    def test_pipeline_re_exports_split_symbols(self) -> None:
        self.assertIs(pipeline.summarize_with_openrouter, summarize_with_openrouter)
        self.assertIs(summarise_with_openrouter, summarize_with_openrouter)
        self.assertIs(pipeline.generate_random_podcast_script, generate_random_podcast_script)
        self.assertIs(pipeline.build_prompt, build_prompt)
        self.assertIs(pipeline.load_system_prompt, load_system_prompt)
        self.assertIs(pipeline.synthesise_speech, synthesise_speech)
        self.assertIs(pipeline.post_text_to_telegram, post_text_to_telegram)


@unittest.skipIf(
    serialise_todo is None,
    f"Skipping persistence behavior checks: {PERSISTENCE_IMPORT_ERROR}",
)
class PersistenceBehaviorTests(unittest.TestCase):
    def test_serialise_deserialise_round_trip(self) -> None:
        todo = Todo(
            id="todo-1",
            title="Write tests",
            due_date=datetime(2026, 1, 2, 12, 30, tzinfo=timezone.utc),
            status="open",
            metadata={"priority": 1, "when": datetime(2026, 1, 2, 12, 0, tzinfo=timezone.utc)},
        )
        todo_list = TodoList(id="list-1", display_title="Work", todos=[todo])

        serialised_todo = serialise_todo(todo)
        self.assertEqual(serialised_todo["id"], "todo-1")
        self.assertEqual(serialised_todo["due_date"], "2026-01-02T12:30+00:00")

        deserialised_todo = deserialise_todo(serialised_todo)
        self.assertEqual(deserialised_todo.id, todo.id)
        self.assertEqual(deserialised_todo.title, todo.title)
        self.assertEqual(deserialised_todo.status, todo.status)

        serialised_list = serialise_todo_list(todo_list)
        deserialised_list = deserialise_todo_list(serialised_list)
        self.assertEqual(deserialised_list.id, todo_list.id)
        self.assertEqual(deserialised_list.display_title, todo_list.display_title)
        self.assertEqual(len(deserialised_list.todos), 1)
        self.assertEqual(deserialised_list.todos[0].id, todo.id)

    def test_run_markers_file_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "run-markers.txt"
            markers = {"a": "111", "b": "222"}
            write_run_markers(markers, path)
            self.assertEqual(read_run_markers(path), markers)


if __name__ == "__main__":
    unittest.main()
