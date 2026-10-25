import json,tempfile,unittest
from pathlib import Path
from serve.audio_library import AudioLibrary

class AudioLibraryTests(unittest.TestCase):
    def test_batch_failure_removes_only_its_own_outputs(self):
        from unittest.mock import patch
        from serve.configuration import atomic_json
        with tempfile.TemporaryDirectory() as root:
            library=AudioLibrary(root);original=library.save(b'RIFFkeep',{})
            calls=0
            def write(path,record):
                nonlocal calls
                calls+=1
                if calls==3:raise OSError('disk full')
                atomic_json(path,record)
            with patch('serve.audio_library.atomic_json',write):
                with self.assertRaises(OSError):library.save_batch([(b'RIFFstem',{'voice':name}) for name in ('vocals','bass','drums','other')])
            self.assertEqual([entry['id'] for entry in library.list()],[original['id']])
            self.assertEqual(library.read(original['id']),b'RIFFkeep')
    def test_batch_capacity_is_checked_before_any_output_is_written(self):
        with tempfile.TemporaryDirectory() as root:
            library=AudioLibrary(root);library.folder.mkdir(parents=True)
            for index in range(98):(library.folder/f'{index}.wav').write_bytes(b'keep')
            with self.assertRaisesRegex(ValueError,'capacity'):library.save_batch([(b'RIFFstem',{})]*4)
            self.assertEqual(len(list(library.folder.glob('*.wav'))),98)
            self.assertFalse(list(library.folder.glob('*.json')))
    def test_identity_collision_never_deletes_existing_audio(self):
        from unittest.mock import patch
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as root:
            library=AudioLibrary(root);entry=library.save(b'RIFFkeep',{})
            with patch('serve.audio_library.uuid.uuid4',return_value=SimpleNamespace(hex=entry['id'])):
                with self.assertRaises(FileExistsError):library.save(b'RIFFnew',{})
            self.assertEqual(library.read(entry['id']),b'RIFFkeep')
    def test_four_outputs_have_independent_integrity_records(self):
        with tempfile.TemporaryDirectory() as root:
            library=AudioLibrary(root);items=[(b'RIFF'+name.encode(),{'voice':name}) for name in ('vocals','bass','drums','other')]
            entries=library.save_batch(items)
            self.assertEqual(len(library.list()),4)
            for entry,(audio,_) in zip(entries,items):self.assertEqual(library.read(entry['id']),audio)
    def test_saved_metadata_integrity_readback_and_scoped_removal(self):
        with tempfile.TemporaryDirectory() as root:
            library=AudioLibrary(root);entry=library.save(b'RIFFaudio',{'model':'kokoro','voice':'if_sara','audio_seconds':1,'elapsed_seconds':2,'input':'private text'})
            self.assertNotIn('input',entry);self.assertEqual(library.list()[0]['id'],entry['id']);self.assertEqual(library.read(entry['id']),b'RIFFaudio')
            unrelated=Path(root)/'other.wav';unrelated.write_bytes(b'keep')
            self.assertTrue(library.delete(entry['id'])['removed']);self.assertFalse(library.list());self.assertEqual(unrelated.read_bytes(),b'keep')
    def test_traversal_and_changed_audio_are_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            library=AudioLibrary(root);entry=library.save(b'RIFFaudio',{})
            for value in ('../other','',None):
                with self.assertRaises(ValueError):library.read(value)
            (library.folder/(entry['id']+'.wav')).write_bytes(b'CHANGED!!')
            with self.assertRaises(ValueError):library.read(entry['id'])
    def test_manifest_failure_does_not_leave_unregistered_audio(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as root:
            library=AudioLibrary(root)
            with patch('serve.audio_library.atomic_json',side_effect=OSError('disk full')):
                with self.assertRaises(OSError):library.save(b'RIFFaudio',{})
            self.assertFalse(list(library.folder.glob('*.wav')))

if __name__=='__main__':unittest.main()
