import json,sqlite3,tempfile,unittest
from pathlib import Path
from serve.harness_history import sessions,read
class SharedHistoryTests(unittest.TestCase):
 def test_claude_native_jsonl_is_read_only_and_text_paginated(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);path=root/'data/claude-home/projects/project/abc-123.jsonl';path.parent.mkdir(parents=True)
   events=[{'type':'system','message':{'content':'ignore'}},{'type':'user','message':{'content':'Claude title'}},{'type':'assistant','message':{'content':[{'type':'thinking','thinking':'private'},{'type':'text','text':'x'*8500},{'type':'tool_use','name':'Read'}]}}]
   path.write_text('\n'.join(json.dumps(e) for e in events),encoding='utf-8');original=path.read_bytes()
   row=sessions(root,kind='claude')['sessions'][0];self.assertEqual(row['title'],'Claude title')
   result=read(root,'claude','abc-123');self.assertEqual(result['messages'][0]['content'],'Claude title');self.assertEqual(result['messages'][1]['role'],'assistant')
   first=read(root,'claude','abc-123',limit=1,offset=1)['messages'][0]
   second=read(root,'claude','abc-123',limit=1,offset=1,content_offset=first['next_content_offset'])['messages'][0]
   self.assertEqual(first['content']+second['content'],'x'*8500);self.assertEqual(path.read_bytes(),original)
   path.write_bytes(b'x'*(8*1024*1024+1));self.assertEqual(sessions(root,kind='claude')['sessions'],[])
   with self.assertRaises(ValueError):read(root,'claude','../escape')
 def test_hermes_native_archive_is_read_only(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);path=root/'data/hermes-home/state.db';path.parent.mkdir(parents=True)
   db=sqlite3.connect(path);db.executescript('CREATE TABLE sessions(id,title,last_activity_at); CREATE TABLE messages(id,session_id,role,content,timestamp);');db.execute('INSERT INTO sessions VALUES (?,?,?)',('h1','Hermes fixture',10));db.execute('INSERT INTO messages VALUES (?,?,?,?,?)',(1,'h1','user','Shared Hermes conversation',10));db.commit();db.close();original=path.read_bytes()
   self.assertEqual(sessions(root,kind='hermes')['sessions'][0]['session_id'],'h1')
   self.assertIn('Shared Hermes conversation',read(root,'hermes','h1')['messages'][0]['content'])
   self.assertEqual(path.read_bytes(),original)
 def test_reads_native_archives_without_writing(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);oc=root/'data/opencode-home/data/opencode/opencode.db';oc.parent.mkdir(parents=True);db=sqlite3.connect(oc);db.executescript('CREATE TABLE session_v2(id,title,time_updated); CREATE TABLE session_message(session_id,type,seq,data);');db.execute('INSERT INTO session_v2 VALUES (?,?,?)',('s1','Conversazione è',1));db.execute('INSERT INTO session_message VALUES (?,?,?,?)',('s1','user',1,json.dumps({'text':'hello'})));db.commit();db.close();original=oc.read_bytes()
   dsh=root/'data/dsh-home';meta=dsh/'storages/session_projcache/sessions/session-test.json';meta.parent.mkdir(parents=True);meta.write_text(json.dumps({'record':{'rows':{'title':{'val':'DeepSeek è'}}}},ensure_ascii=False),encoding='utf-8');log=dsh/'sessions/workspace/session-test/session.v4.jsonl';log.parent.mkdir(parents=True);log.write_text(json.dumps({'type':'user/message','data':{'text':'shared context'}}))
   tf=root/'data/trueforge-home/db.sqlite';tf.parent.mkdir(parents=True);db=sqlite3.connect(tf);db.executescript('CREATE TABLE session(session_id,title,last_activity_timestamp_ms); CREATE TABLE turn(session_id,input,created_at); CREATE TABLE session_event(session_id,event,created_at);');db.execute('INSERT INTO session VALUES (?,?,?)',('t1','TrueForge',2));db.execute('INSERT INTO turn VALUES (?,?,?)',('t1',json.dumps({'text':'test'}),1));db.commit();db.close()
   self.assertEqual(len(sessions(root)['sessions']),3);self.assertIn('hello',read(root,'opencode','s1')['messages'][0]['content']);self.assertIn('shared context',read(root,'dsh','session-test')['messages'][0]['content']);self.assertEqual(read(root,'trueforge','t1')['messages'][0]['role'],'user');self.assertEqual(oc.read_bytes(),original)
 def test_path_traversal_rejected(self):
  with self.assertRaises(ValueError):read(Path.cwd(),'dsh','../secret')
  with self.assertRaises(ValueError):sessions(Path.cwd(),kind='other')
 def test_long_message_can_be_read_in_successive_chunks(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);path=root/'data/opencode-home/data/opencode/opencode.db';path.parent.mkdir(parents=True);db=sqlite3.connect(path);db.executescript('CREATE TABLE session_v2(id,title,time_updated); CREATE TABLE session_message(session_id,type,seq,data);');db.execute('INSERT INTO session_v2 VALUES (?,?,?)',('long','Long',1));content={'text':'a'*8500};db.execute('INSERT INTO session_message VALUES (?,?,?,?)',('long','user',1,json.dumps(content)));db.commit();db.close()
   first=read(root,'opencode','long',limit=1)['messages'][0];self.assertTrue(first['truncated'])
   second=read(root,'opencode','long',limit=1,content_offset=first['next_content_offset'])['messages'][0]
   self.assertEqual(first['content']+second['content'],json.dumps(content,ensure_ascii=False));self.assertFalse(second['truncated'])


class DshConcatenatedFrames(unittest.TestCase):
 def test_read_all_original_zstd_frames(self):
  import subprocess,shutil
  node=shutil.which('node')
  if not node:self.skipTest('Node unavailable')
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);identity='session-frame-proof'
   directory=root/'data/dsh-home/sessions/workspace'/identity;directory.mkdir(parents=True)
   metadata=root/'data/dsh-home/storages/session_projcache/sessions';metadata.mkdir(parents=True)
   (metadata/(identity+'.json')).write_text(json.dumps({'record':{'rows':{}}}))
   path=directory/'session.v4.jsonl.zstd'
   rows=[{'type':'session','id':identity},{'type':'user/message','data':{'content':'hello'}},{'type':'assistant/message','data':{'message':{'content':[{'type':'text','text':'Hi'}]}}}]
   code="const fs=require('fs'),z=require('node:zlib');const rows=JSON.parse(process.argv[2]);fs.writeFileSync(process.argv[1],Buffer.concat(rows.map(r=>z.zstdCompressSync(Buffer.from(JSON.stringify(r)+'\\n')))));"
   subprocess.run([node,'-e',code,str(path),json.dumps(rows)],capture_output=True,check=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
   result=read(root,'dsh',identity)
   self.assertEqual([row['role'] for row in result['messages']],['user','assistant'])
   self.assertIn('Hi',result['messages'][1]['content'])

class ClaudeArchiveIsolationTests(unittest.TestCase):
 def test_invalid_archive_does_not_hide_valid_sessions(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);projects=root/'data/claude-home/projects/project';projects.mkdir(parents=True)
   (projects/'broken.jsonl').write_text('{broken',encoding='utf-8')
   (projects/'valid.jsonl').write_text(json.dumps({'type':'user','message':{'content':'Visible conversation'}}),encoding='utf-8')
   result=sessions(root,kind='claude')
   self.assertEqual([r['session_id'] for r in result['sessions']],['valid'])
   self.assertEqual(len(result['errors']),1)
 def test_unreadable_identity_and_non_message_events_are_ignored(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);projects=root/'data/claude-home/projects/project';projects.mkdir(parents=True)
   (projects/'bad name.jsonl').write_text(json.dumps({'type':'user','message':{'content':'Unselectable'}}),encoding='utf-8')
   (projects/'valid.jsonl').write_text('\n'.join(json.dumps(e) for e in [None,{'type':'user','message':'malformed'},{'type':'user','message':{'content':'Actual user'}}]),encoding='utf-8')
   self.assertEqual([r['session_id'] for r in sessions(root,kind='claude')['sessions']],['valid'])
   self.assertEqual(read(root,'claude','valid')['messages'][0]['content'],'Actual user')

if __name__=='__main__':unittest.main()
