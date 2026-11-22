import hashlib
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest

from serve.hydra_graph_memory import GraphMemory, _rank_candidates


class GraphMemoryTests(unittest.TestCase):
    def test_result_limit_does_not_pad_with_weak_generic_matches(self):
        rows = [{'content': 'HYDRA Graph: 10000 nodi, 20000 archi.'},
                {'content': 'GPU process RSS massimi hardware.'},
                {'content': 'HYDRA Graph activation configuration.'},
                {'content': 'HYDRA Graph settings.'}]
        ranked = _rank_candidates(rows, 'Quanti archi massimi HYDRA Graph?', filter_weak=True)
        self.assertEqual(ranked, [rows[0]])

    def test_multiple_distinct_evidence_topics_remain_available(self):
        rows = [{'content': 'Native cache details.'},
                {'content': 'FIFO scheduling details.'},
                {'content': 'Other details.'}]
        self.assertEqual(_rank_candidates(rows, 'native cache FIFO scheduling', filter_weak=True), rows[:2])

    def test_distinctive_evidence_outweighs_repeated_generic_terms(self):
        rows = [{'content': 'HYDRA Graph documentation. ' * 20},
                {'content': 'HYDRA Graph native context.'},
                {'content': 'Profondita massima: 3; fonte verificata.'}]
        ranked = _rank_candidates(rows, 'Secondo la documentazione HYDRA Graph, profondit\u00e0 massima?')
        self.assertIs(ranked[0], rows[2])
        self.assertEqual({id(row) for row in ranked}, {id(row) for row in rows})

    def test_ranking_preserves_ties_empty_queries_and_deadlines(self):
        rows = [{'content': 'Same context.'}, {'content': 'Same context.'}]
        self.assertEqual(_rank_candidates(rows, 'context'), rows)
        self.assertEqual(_rank_candidates(rows, 'the and con'), rows)
        self.assertEqual(_rank_candidates([], 'context'), [])
        with self.assertRaises(TimeoutError):
            _rank_candidates(rows, 'context', deadline=time.monotonic()-1)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'source.txt'
        self.source.write_text('HYDRA preserves native prefix cache and FIFO scheduling.', encoding='utf-8')
        self.db = self.root / 'graph.sqlite'
        self.graph = GraphMemory.create(self.db, roots=[self.root])

    def ingest(self, scope='project-a', source=None):
        return self.graph.ingest(scope, source or self.source)

    def retrieve(self, scope='project-a', sources=None, **kw):
        return self.graph.retrieve(scope, 'native prefix cache', allowed_sources=sources or [str(self.source)], **kw)

    def test_provenance_dedup_and_incremental_update(self):
        node = self.ingest()
        self.assertEqual(node, self.ingest())
        rows = self.retrieve()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['id'], node)
        self.assertEqual(rows[0]['evidence'], 'source')
        self.assertEqual(rows[0]['source_sha256'], hashlib.sha256(self.source.read_bytes()).hexdigest())
        self.source.write_text('Updated native prefix cache facts.', encoding='utf-8')
        newer = self.ingest()
        self.assertNotEqual(node, newer)
        self.assertEqual([r['id'] for r in self.retrieve()], [newer])

    def test_scope_allowlist_missing_and_stale_sources(self):
        self.ingest()
        self.assertEqual(self.retrieve('project-b'), [])
        self.assertEqual(self.graph.retrieve('project-a', 'cache', allowed_sources=[]), [])
        self.source.write_text('Changed content', encoding='utf-8')
        self.assertEqual(self.retrieve(), [])
        self.source.unlink()
        self.assertEqual(self.retrieve(), [])

    def test_cycles_limits_missing_nodes_and_cross_scope_edges(self):
        a = self.ingest()
        other = self.root / 'other.txt'
        other.write_text('Related scheduling details.', encoding='utf-8')
        b = self.ingest(source=other)
        self.graph.relate('project-a', a, b, 'references')
        self.graph.relate('project-a', b, a, 'references')
        rows = self.retrieve(sources=[str(self.source), str(other)], max_nodes=2, depth=2)
        self.assertEqual(len(rows), 2)
        self.assertEqual(len(self.retrieve(max_nodes=1)), 1)
        with self.assertRaises(ValueError): self.graph.relate('project-a', a, 'missing', 'references')
        c = self.ingest('project-b', other)
        with self.assertRaises(ValueError): self.graph.relate('project-a', a, c, 'references')
        with self.assertRaises(ValueError): self.graph.relate('project-a', a, b, 'invented')

    def test_readonly_schema_deadline_and_source_boundary(self):
        self.ingest()
        reader = GraphMemory.open(self.db, roots=[self.root])
        self.assertEqual(len(reader.retrieve('project-a', 'cache', allowed_sources=[str(self.source)])), 1)
        with self.assertRaises(PermissionError): reader.ingest('project-a', self.source)
        with self.assertRaises(TimeoutError): self.retrieve(deadline=time.monotonic()-1)
        with self.assertRaises(ValueError): GraphMemory.create(self.db, roots=[self.root])
        foreign = self.root/'foreign.sqlite'
        with closing(sqlite3.connect(foreign)) as db, db: db.execute('create table user_data(value)')
        before = foreign.read_bytes()
        with self.assertRaises(ValueError): GraphMemory.open(foreign, roots=[self.root])
        self.assertEqual(foreign.read_bytes(), before)
        with self.assertRaises(ValueError): self.graph.ingest('project-a', self.root.parent/'outside.txt')

    def test_interrupted_update_rolls_back_and_preserves_original(self):
        self.ingest()
        original = self.source.read_bytes()
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute("CREATE TRIGGER deny_insert BEFORE INSERT ON nodes BEGIN SELECT RAISE(ABORT, 'fixture disk failure'); END")
        self.source.write_text('new prefix cache', encoding='utf-8')
        with self.assertRaises(sqlite3.DatabaseError): self.ingest()
        self.source.write_bytes(original)
        self.assertEqual(len(self.retrieve()), 1)

    def test_expired_nodes_and_denied_source_are_not_evidence(self):
        from unittest.mock import patch
        self.ingest()
        with patch.object(self.graph,'_read_source',side_effect=PermissionError('fixture')):
            self.assertEqual(self.retrieve(),[])
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute('UPDATE nodes SET updated=0')
        self.assertEqual(self.retrieve(),[])
        self.ingest()  # Explicit re-ingestion verifies the unchanged source now.
        self.assertEqual(len(self.retrieve()),1)

    def test_inferred_edges_not_traversed_and_full_scan_not_needed(self):
        from unittest.mock import patch
        a=self.ingest();other=self.root/'unrelated.txt'
        other.write_text('Photographic lighting details',encoding='utf-8')
        b=self.ingest(source=other)
        self.graph.relate('project-a',a,b,'references',evidence='hypothesis')
        with patch.object(self.graph,'_read_source',wraps=self.graph._read_source) as read:
            rows=self.retrieve(sources=[str(self.source),str(other)])
        self.assertEqual([row['id'] for row in rows],[a])
        self.assertEqual(read.call_count,1)

    def test_remote_paths_rejected_before_access(self):
        with self.assertRaises(ValueError):
            GraphMemory.open(r'\\untrusted-host\share\graph.sqlite',roots=[self.root])
        with self.assertRaises(ValueError):
            GraphMemory.create(self.root/'remote.sqlite',roots=[r'\\untrusted-host\share'])

    def test_sections_are_exact_source_spans_and_incremental(self):
        text='# Native cache\n\nNative prefix cache belongs to the engine.\n\n# Optical system\n\nPhotographic illumination is unrelated.\n'
        self.source.write_text(text,encoding='utf-8')
        text=self.source.read_bytes().decode('utf-8')
        ids=self.graph.ingest_sections('project-a',self.source,target_chars=256)
        self.assertEqual(len(ids),2)
        rows=self.retrieve(max_nodes=1,depth=0)
        self.assertEqual(len(rows),1)
        self.assertNotIn('Photographic',rows[0]['content'])
        span=rows[0]['source_span']
        self.assertEqual(rows[0]['content'],text[span['start_char']:span['end_char']])
        self.assertEqual(ids,self.graph.ingest_sections('project-a',self.source,target_chars=256))
        self.source.write_text(text.replace('engine','native backend'),encoding='utf-8')
        newer=self.graph.ingest_sections('project-a',self.source,target_chars=256)
        self.assertFalse(set(ids)&set(newer))
        self.assertEqual(len(self.retrieve(max_nodes=2)),1)

    def test_section_archive_tampering_and_atomic_failure(self):
        self.source.write_text('# Cache\n\nNative prefix cache is inherited.\n\n# Other\n\nOther document data.',encoding='utf-8')
        self.graph.ingest_sections('project-a',self.source,target_chars=256)
        with closing(sqlite3.connect(self.db)) as db,db:
            db.execute("UPDATE nodes SET content='fake native prefix cache' WHERE content LIKE '%prefix%'")
        self.assertEqual(self.retrieve(),[])
        with self.assertRaises(ValueError):self.graph.ingest('project-a',self.source,metadata={'_hydra_span':{}})

    def test_long_query_keeps_late_distinctive_terms(self):
        self.ingest()
        other=self.root/'optics.txt';other.write_text('Zoology bibliography.',encoding='utf-8')
        other_id=self.ingest(source=other)
        query='about above after again against along among another around because before being below between could during every having zoology'
        rows=self.graph.retrieve('project-a',query,allowed_sources=[str(self.source),str(other)],max_nodes=1)
        self.assertEqual([row['id'] for row in rows],[other_id])

    def test_sections_share_one_verified_source_snapshot_per_retrieval(self):
        from unittest.mock import patch
        self.source.write_text('# Cache\n\nNative prefix cache.\n\n# Scheduling\n\nNative FIFO scheduling.',encoding='utf-8')
        self.graph.ingest_sections('project-a',self.source,target_chars=256)
        with patch.object(self.graph,'_read_source',wraps=self.graph._read_source) as read:
            # Exercise two relevant sections, rather than depending on padding
            # a cache-only query with a weak scheduling match.
            rows=self.graph.retrieve('project-a','native prefix cache FIFO scheduling',
                                     allowed_sources=[str(self.source)],max_nodes=2)
        self.assertEqual(len(rows),2)
        self.assertEqual(read.call_count,1)
        self.source.write_text('Changed native cache.',encoding='utf-8')
        self.assertEqual(self.retrieve(max_nodes=2),[])

    def test_invalid_source_is_read_once_per_retrieval(self):
        from unittest.mock import patch
        self.source.write_text('# Cache\n\nNative prefix cache.\n\n# Scheduling\n\nNative FIFO scheduling.',encoding='utf-8')
        self.graph.ingest_sections('project-a',self.source,target_chars=256)
        with patch.object(self.graph,'_read_source',side_effect=OSError('unavailable')) as read:
            self.assertEqual(self.retrieve(max_nodes=2),[])
        self.assertEqual(read.call_count,1)


