"""The chat archive has a durable copy, so nothing is lost with the browser."""
import json
import tempfile
import unittest
from pathlib import Path

from serve.chat_archive import read_archive, save_archive, ARCHIVE_LIMIT


class ChatArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def record(self, identity='chat-1', text='ciao'):
        return {'id': identity, 'title': 'Conversazione', 'model': 'local',
                'updated_at': 1, 'messages': [{'role': 'user', 'text': text}]}

    def test_saving_and_reading_back_the_archive(self):
        save_archive(self.root, [self.record()])
        rows = read_archive(self.root)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['id'], 'chat-1')
        self.assertEqual(rows[0]['messages'][0]['text'], 'ciao')

    def test_no_archive_yet_returns_empty(self):
        self.assertEqual(read_archive(self.root), [])

    def test_a_corrupt_archive_never_hides_the_browser_copy(self):
        save_archive(self.root, [self.record()])
        (self.root / 'chat-archive.json').write_text('{ not json', encoding='utf-8')
        self.assertEqual(read_archive(self.root), [])

    def test_a_broken_row_is_dropped_and_the_rest_kept(self):
        save_archive(self.root, [self.record('a'), {'id': 'b'}])
        rows = read_archive(self.root)
        self.assertEqual([row['id'] for row in rows], ['a'])

    def test_oversized_archive_is_refused_without_touching_the_stored_copy(self):
        save_archive(self.root, [self.record()])
        huge = [self.record('big', 'x' * (ARCHIVE_LIMIT + 10))]
        with self.assertRaises(ValueError):
            save_archive(self.root, huge)
        self.assertEqual([row['id'] for row in read_archive(self.root)], ['chat-1'])

    def test_a_symlinked_archive_is_refused(self):
        target = self.root / 'elsewhere.json'
        target.write_text('[]', encoding='utf-8')
        try:
            (self.root / 'chat-archive.json').symlink_to(target)
        except OSError:
            self.skipTest('creating a symlink needs a privileged account on Windows')
        with self.assertRaises(ValueError):
            save_archive(self.root, [self.record()])

    def test_an_unwritable_root_reports_a_clear_error(self):
        blocker = self.root / 'chat-archive.json'
        blocker.write_text('keep', encoding='utf-8')          # a file where a folder is needed
        with self.assertRaises((OSError, ValueError)):
            save_archive(blocker / 'deeper', [self.record()])


if __name__ == '__main__':
    unittest.main()
