import json
import unittest
from unittest.mock import Mock
from serve.voicestudio_jobs import action


class AudiobookPlanTests(unittest.TestCase):
    def test_cover_upload_keeps_only_original_generated_filename(self):
        client=Mock();client._busy.acquire.return_value=True
        client._request.return_value=(b'{"path":"C:/original/outputs/audiobook_covers/012345abcdef.png"}',None,None)
        result=action(client,{'kind':'audiobook','action':'cover','file_name':'cover.png','file_base64':'iVBORw0KGgo='})
        self.assertEqual(result['cover_path'],'012345abcdef.png')
        self.assertEqual(client._request.call_args.args[0],'/audiobook/cover')
        client._busy.release.assert_called_once()

    def test_cover_rejects_invalid_file_and_foreign_native_filename(self):
        for payload in ({'file_name':'../cover.png','file_base64':'iVBORw0KGgo='},
                        {'file_name':'cover.png','file_base64':'PGh0bWw+'}):
            client=Mock()
            with self.assertRaises(ValueError):action(client,{'kind':'audiobook','action':'cover',**payload})
            client._request.assert_not_called()
        client=Mock();client._busy.acquire.return_value=True
        client._request.return_value=(b'{"path":"C:/original/secret.txt"}',None,None)
        with self.assertRaises(RuntimeError):action(client,{'kind':'audiobook','action':'cover','file_name':'cover.png','file_base64':'iVBORw0KGgo='})

    def test_project_rename_is_partial_and_inspect_preserves_native_state(self):
        client=Mock();client._busy.acquire.return_value=True
        client._request.return_value=(b'{"id":"project-1","state":{"timeline":[1,2]}}',None,None)
        result=action(client,{'kind':'projects','action':'inspect','id':'project-1'})
        self.assertEqual(result['result']['state']['timeline'],[1,2])
        action(client,{'kind':'projects','action':'rename','id':'project-1','name':' New name '})
        args,kwargs=client._request.call_args
        self.assertEqual(args,('/projects/project-1',{'name':'New name'}))
        self.assertEqual(kwargs['method'],'PATCH')

    def test_manuscript_import_uses_native_format_and_rejects_paths(self):
        client=Mock();client._request.return_value=(b'{"text":"# Imported\\nHello","chapters":1}',None,None)
        result=action(client,{'kind':'audiobook','action':'import','file_name':'book.md','file_base64':'IyBUZXN0'})
        self.assertEqual(result['result']['chapters'],1)
        self.assertEqual(client._request.call_args.args[0],'/audiobook/import')
        client.reset_mock()
        with self.assertRaises(ValueError):action(client,{'kind':'audiobook','action':'import','file_name':'../book.md','file_base64':'IyBUZXN0'})
        client._request.assert_not_called()

    def test_batch_download_validates_language_and_original_mp4(self):
        client=Mock();client._request.return_value=(b'\0\0\0\x18ftypisom'+b'\0'*12,None,'video/mp4')
        result=action(client,{'kind':'batch','action':'download','id':'original-job','language':'it'})
        self.assertEqual(result['filename'],'original-job-it.mp4')
        self.assertEqual(client._request.call_args.args[0],'/batch/download/original-job/it')
        client.reset_mock()
        with self.assertRaises(ValueError):action(client,{'kind':'batch','action':'download','id':'original-job','language':'../it'})
        client._request.assert_not_called()
        client._request.return_value=(b'HTML error',None,'text/html')
        with self.assertRaises(RuntimeError):action(client,{'kind':'batch','action':'download','id':'original-job','language':'it'})

    def test_batch_rejects_remote_provider_and_invalid_media_before_native_call(self):
        for values in ({'translation_provider':'openai'}, {'file_name':'../video.mp4'}, {'langs':['../en']}, {'preserve_bg':'yes'}):
            client=Mock()
            with self.assertRaises(ValueError):
                action(client,{'kind':'batch','action':'enqueue','file_name':'video.mp4','file_base64':'eA==','langs':['en'],**values})
            client._request.assert_not_called()

    def test_batch_uses_original_queue_and_explicit_local_translation(self):
        client=Mock();client._busy.acquire.return_value=True
        client._request.return_value=(b'{"job_id":"original-job","status":"queued"}',None,None)
        result=action(client,{'kind':'batch','action':'enqueue','file_name':'video.mp4','file_base64':'eA==','langs':['en','it'],'preserve_bg':False})
        self.assertEqual(result['result']['job_id'],'original-job')
        args,kwargs=client._request.call_args
        self.assertEqual(args[0],'/batch/enqueue')
        self.assertIn(b'argos',kwargs['raw_body'])
        self.assertIn(b'en,it',kwargs['raw_body'])
        client._busy.release.assert_called_once()

    def test_plan_uses_original_parser_without_starting_generation(self):
        client = Mock()
        plan = {'chapters': [{'title': 'Capitolo', 'spans': []}]}
        client._request.return_value = (json.dumps(plan).encode(), None, None)
        result = action(client, {'action': 'plan', 'kind': 'audiobook', 'text': '# Capitolo\nCiao', 'default_voice': 'voice-1'})
        self.assertEqual(result['result'], plan)
        client._request.assert_called_once_with('/audiobook/plan', {'text': '# Capitolo\nCiao', 'default_voice': 'voice-1'}, timeout=15)

    def test_invalid_plan_never_contacts_native_backend(self):
        for values in ({'text': ''}, {'text': 'x' * 100001}, {'text': 'x', 'default_voice': '../private'}, {'text': True}):
            client = Mock()
            with self.assertRaises(ValueError):
                action(client, {'action': 'plan', 'kind': 'audiobook', **values})
            client._request.assert_not_called()
