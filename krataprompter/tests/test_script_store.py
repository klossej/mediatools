import concurrent.futures
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import serve
from script_store import MAX_SCRIPT_BYTES, ScriptError, ScriptStore


class ScriptStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = self.enterContext(TemporaryDirectory())
        self.root = Path(self.directory) / "scripts"
        self.store = ScriptStore(self.root)

    def test_last_opened_survives_restart(self) -> None:
        self.assertIsNone(self.store.previous())
        first = self.store.save("Ääni.md", "Första.\n*#\nToinen.", None)
        self.store.save("Studio.md", "Next.", None)
        self.assertEqual(self.store.previous()["name"], "Studio.md")
        opened = self.store.open("Ääni.md")
        self.assertEqual(opened["revision"], first["revision"])
        restarted = ScriptStore(self.root)
        self.assertEqual(set(restarted.list()), {"Studio.md", "Ääni.md"})
        self.assertEqual(restarted.previous()["content"], "Första.\n*#\nToinen.")
        (self.root / "Ääni.md").unlink()
        self.assertIsNone(restarted.previous())

    def test_existing_file_requires_current_revision(self) -> None:
        created = self.store.save("Live.md", "First.", None)
        with self.assertRaises(ScriptError) as collision:
            self.store.save("Live.md", "A duplicate.", None)
        self.assertEqual(collision.exception.status, 409)

        saved = self.store.save("Live.md", "Latest.", created["revision"])
        self.assertNotEqual(saved["revision"], created["revision"])
        with self.assertRaises(ScriptError) as stale:
            self.store.save("Live.md", "Stale.", created["revision"])
        self.assertEqual(stale.exception.status, 409)
        self.assertEqual((self.root / "Live.md").read_text(encoding="utf-8"), "Latest.")

    def test_concurrent_saves_cannot_both_replace_the_same_revision(self) -> None:
        revision = self.store.save("Live.md", "Initial.", None)["revision"]

        def update(content):
            try:
                self.store.save("Live.md", content, revision)
            except ScriptError as exc:
                return exc.status, content
            return 200, content

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = dict(pool.map(update, ["First edit.", "Second edit."]))
        self.assertEqual(set(results), {200, 409})
        self.assertEqual(self.store.previous()["content"], results[200])

    def test_successive_updates_preserve_exact_markdown_bytes(self) -> None:
        name = "Ääni.md"
        original = "\ufeff---\r\nversion: 26.11.24 22:06\r\n---\r\nFörsta.\r\n*#\r\nToinen.  "
        first = self.store.save(name, original, None)
        unchanged = self.store.save(name, original, first["revision"])
        self.assertEqual(unchanged["revision"], first["revision"])
        self.assertFalse((self.root / ".revisions").exists())

        second = self.store.save(name, "Andra versionen.", first["revision"])
        restarted = ScriptStore(self.root)
        restarted.save(name, "Tredje versionen.", second["revision"])

        history = self.root / ".revisions" / name
        self.assertEqual((history / f"{first['revision']}.md").read_bytes(), original.encode("utf-8"))
        self.assertEqual((history / f"{second['revision']}.md").read_bytes(), b"Andra versionen.")
        self.assertEqual(restarted.open(name)["content"], "Tredje versionen.")
        self.assertEqual(restarted.list(), [name])

    def test_failed_archive_leaves_current_script_and_previous_pointer_intact(self) -> None:
        first = self.store.save("Live.md", "Original manuscript.", None)
        self.store.save("Another.md", "Other script.", None)
        (self.root / ".revisions").write_text("Blocked revision folder.", encoding="utf-8")

        with self.assertRaises(ScriptError) as failed:
            self.store.save("Live.md", "Replacement.", first["revision"])
        self.assertEqual(failed.exception.status, 500)
        self.assertEqual((self.root / "Live.md").read_bytes(), b"Original manuscript.")
        self.assertEqual(self.store.previous()["name"], "Another.md")

    def test_an_existing_archive_is_never_overwritten(self) -> None:
        first = self.store.save("Live.md", "Original manuscript.", None)
        history = self.root / ".revisions" / "Live.md"
        history.mkdir(parents=True)
        archived = history / f"{first['revision']}.md"
        archived.write_bytes(b"Existing archive.")

        with self.assertRaises(ScriptError) as failed:
            self.store.save("Live.md", "Replacement.", first["revision"])
        self.assertEqual(failed.exception.status, 500)
        self.assertEqual(archived.read_bytes(), b"Existing archive.")
        self.assertEqual(self.store.previous()["content"], "Original manuscript.")

    def test_storage_rejects_invalid_names_and_non_regular_files(self) -> None:
        outside = Path(self.directory) / "outside.md"
        outside.write_text("Outside the script folder.", encoding="utf-8")
        (self.root / "link.md").symlink_to(outside)
        (self.root / "directory.md").mkdir()
        self.assertEqual(self.store.list(), [])
        for name in ["../outside.md", "sub\\file.md", ".previous", "x.txt", "\udfff.md"]:
            with self.subTest(name=repr(name)), self.assertRaises(ScriptError) as invalid:
                self.store.save(name, "Contents.", None)
            self.assertEqual(invalid.exception.status, 400)
        for name in ["link.md", "directory.md"]:
            with self.subTest(name=name), self.assertRaises(ScriptError) as invalid:
                self.store.open(name)
            self.assertEqual(invalid.exception.status, 404)
        self.assertEqual(outside.read_text(encoding="utf-8"), "Outside the script folder.")

    def test_storage_bounds_utf8_manuscripts(self) -> None:
        with self.assertRaises(ScriptError) as big:
            self.store.save("big.md", "ä" * (MAX_SCRIPT_BYTES // 2 + 1), None)
        self.assertEqual(big.exception.status, 413)
        with self.assertRaises(ScriptError) as invalid:
            self.store.save("bad.md", "\udfff", None)
        self.assertEqual(invalid.exception.status, 400)
        self.assertEqual(self.store.list(), [])


class DataDirectoryTests(unittest.TestCase):
    def setUp(self) -> None:
        root = Path(self.enterContext(TemporaryDirectory())).resolve()
        self.live = root / "live"
        self.dev = root / "dev"
        self.enterContext(patch.multiple(
            serve, DEFAULT_DATA_DIRECTORY=self.live, DEVELOPMENT_DATA_DIRECTORY=self.dev,
        ))

    def test_development_uses_a_separate_store(self) -> None:
        live = ScriptStore(serve.resolve_data_directory(None, False))
        live.save("Studio.md", "Original manuscript.", None)
        dev = ScriptStore(serve.resolve_data_directory(None, True))
        self.assertEqual(dev.list(), [])
        dev.save("Studio.md", "Development test.", None)
        self.assertEqual(live.previous()["content"], "Original manuscript.")
        with self.assertRaisesRegex(ValueError, "must be separate"):
            serve.resolve_data_directory(self.dev, False)

    def test_development_refuses_links_to_the_live_folder(self) -> None:
        self.dev.symlink_to(self.live, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "must not be a symlink"):
            serve.resolve_data_directory(None, True)
        self.assertEqual(serve.resolve_data_directory(None, False), self.live)
