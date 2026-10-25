"""Only our HTTP relay and cancellation ownership; no original engine execution."""
import io
import json
import unittest
from unittest.mock import Mock
from serve.voicestudio_render import forward,cancel,render_payload


class NativeStream(io.BytesIO):
    headers={'x-omnivoice-backend':'original','Content-Type':'text/event-stream'}


class RenderRelayTests(unittest.TestCase):
    def test_cover_only_uses_generated_original_token(self):
        self.assertEqual(render_payload({'text':'Chapter','cover_path':'012345abcdef.png'})['cover_path'],'012345abcdef.png')
        for name in ('../cover.png','C:/user/cover.png','cover.png','012345abcdef.exe'):
            with self.assertRaises(ValueError):render_payload({'text':'Chapter','cover_path':name})

    def test_native_options_preserve_explicit_zero_false_and_unset_defaults(self):
        values={'text':'Chapter','line_gap_ms':0,'paragraph_gap_ms':350,'trim_edges':False,
                'num_step':32,'guidance_scale':2.0,'position_temperature':0.0,'class_temperature':0.0,
                'postprocess_output':False,'seed':0,'emo_text':'calm','emo_alpha':0.0,'vary_repeats':True}
        result=render_payload(values)
        for key,value in values.items():self.assertEqual(result[key],value)
        plain=render_payload({'text':'Chapter'})
        for key in values:
            if key!='text':self.assertNotIn(key,plain)


    def test_cast_lexicon_and_emotion_vector_forward_native_fields(self):
        values={'text':'Chapter [voice:ANNA] hello','voice_map':{'ANNA':'profile-1','BOB':'profile-2'},
                'lexicon':{'Gimli':'GIM-lee','AI':'A-I'},'emo_vector':[10,20,30,40,50,60,70,80]}
        result=render_payload(values)
        self.assertEqual(result['voice_map'],{'ANNA':'profile-1','BOB':'profile-2'})
        self.assertEqual(result['lexicon'],{'Gimli':'GIM-lee','AI':'A-I'})
        self.assertEqual(result['emo_vector'],[10.0,20.0,30.0,40.0,50.0,60.0,70.0,80.0])
        plain=render_payload({'text':'Chapter'})
        for key in ('voice_map','lexicon','emo_vector'):self.assertNotIn(key,plain)

    def test_cast_lexicon_and_emotion_vector_reject_invalid_values(self):
        cases=[
            {'voice_map':{}},{'voice_map':{'ANNA':'profile with space'}},{'voice_map':{'[bad]':'profile-1'}},
            {'voice_map':{'ANNA':'profile-1'},'extra':1} if False else {'voice_map':[('ANNA','profile-1')]},
            {'lexicon':{}},{'lexicon':{'x'*201:'ok'}},{'lexicon':{'word':'r'*501}},
            {'emo_vector':[1,2,3]},{'emo_vector':[1,2,3,4,5,6,7,'8']},{'emo_vector':[1,2,3,4,5,6,7,-1]},
            {'emo_vector':[1,2,3,4,5,6,7,101]},{'emo_vector':[1,2,3,4,5,6,7,float('nan')]},
        ]
        for payload in cases:
            with self.subTest(payload=payload),self.assertRaises(ValueError):render_payload({'text':'Chapter',**payload})

    def test_native_options_reject_invalid_types_bounds_and_nonfinite_values(self):
        for key,value in [('line_gap_ms',5001),('paragraph_gap_ms',-1),('num_step',True),('num_step',0),
                          ('seed',2**32),('guidance_scale',float('nan')),('class_temperature',float('inf')),
                          ('position_temperature',101),('postprocess_output','false'),('trim_edges',1),
                          ('emo_alpha',1.1),('emo_text','x'*501),('vary_repeats',None)]:
            with self.subTest(key=key,value=value):
                with self.assertRaises(ValueError):render_payload({'text':'Chapter',key:value})

    def test_resume_uses_listed_original_job_without_resending_script(self):
        client=Mock();client.base_url='http://127.0.0.1:3900';client._busy.acquire.return_value=True
        client._request.return_value=(b'{"jobs":[{"job_id":"native-book","status":"failed"}]}',None,None)
        events=b'data: {"type":"done","output":"resumed.m4b"}\n\n'
        client._opener.open.return_value=NativeStream(events)
        handler=Mock();handler.headers={'Content-Length':'100','X-Strata-Voice-Request':'request-123'}
        handler._read_body.return_value=b'{"resume_job_id":"native-book"}';handler.wfile=io.BytesIO()
        forward(handler,client)
        request=client._opener.open.call_args.args[0]
        self.assertEqual(request.full_url,'http://127.0.0.1:3900/audiobook/resume/native-book')
        self.assertEqual(json.loads(request.data),{})
        self.assertEqual(handler.wfile.getvalue(),events)
        client._busy.release.assert_called_once()

    def test_resume_rejects_unknown_jobs_and_payload_overrides(self):
        for payload in ({'resume_job_id':'../private'}, {'resume_job_id':'native-book','text':'override'},
                        {'resume_job_id':'missing-book'}):
            with self.subTest(payload=payload):
                client=Mock();client._busy.acquire.return_value=True
                client._request.return_value=(b'{"jobs":[]}',None,None)
                handler=Mock();handler.headers={'Content-Length':'100','X-Strata-Voice-Request':'request-123'}
                handler._read_body.return_value=json.dumps(payload).encode()
                with self.assertRaises(ValueError):forward(handler,client)
                client._opener.open.assert_not_called()
                client._busy.release.assert_called_once()

    def test_resume_never_restarts_active_or_completed_native_jobs(self):
        for state in ('running','pending','queued','done',None):
            with self.subTest(state=state):
                client=Mock();client._busy.acquire.return_value=True
                client.base_url='http://127.0.0.1:3900';client._opener.open.return_value=NativeStream(b'')
                client._request.return_value=(json.dumps({'jobs':[{'job_id':'native-book','status':state}]}).encode(),None,None)
                handler=Mock();handler.headers={'Content-Length':'100','X-Strata-Voice-Request':'request-123'}
                handler._read_body.return_value=b'{"resume_job_id":"native-book"}'
                handler.wfile=io.BytesIO()
                with self.assertRaises(ValueError):forward(handler,client)
                client._opener.open.assert_not_called()

    def test_relay_preserves_original_events_and_releases_guard(self):
        events=b'data: {"type":"started","job_id":"native-1"}\n\ndata: {"type":"done","output":"native.m4b"}\n\n'
        client=Mock();client.base_url='http://127.0.0.1:3900';client._busy.acquire.return_value=True;client._opener.open.return_value=NativeStream(events)
        handler=Mock();handler.headers={'Content-Length':'100','X-Strata-Voice-Request':'request-123'};handler._read_body.return_value=json.dumps({'text':'Chapter','format':'mp3','metadata':{'title':'My book'}}).encode();handler.wfile=io.BytesIO()
        forward(handler,client)
        self.assertEqual(handler.wfile.getvalue(),events)
        sent=json.loads(client._opener.open.call_args.args[0].data)
        self.assertEqual(sent['format'],'mp3');self.assertEqual(sent['metadata']['title'],'My book')
        client._busy.release.assert_called_once();self.assertIsNone(client._render_transfer)

    def test_cancel_only_owns_matching_request(self):
        client=Mock();response=Mock();event=Mock();client._render_transfer=('request-123',response,event)
        with self.assertRaises(ValueError):cancel(client,{'request_id':'another-request'})
        response.fp.raw._sock.shutdown.assert_not_called()
        self.assertTrue(cancel(client,{'request_id':'request-123'})['cancellation_requested'])
        response.fp.raw._sock.shutdown.assert_called_once();event.set.assert_called_once()
