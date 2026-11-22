"""Explicit local corpus memory; never indexes conversations or alters sources.

Each operation owns its SQLite connection. Inference opens an existing archive
read-only. Scope and source allowlists come from trusted deployment policy.
"""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import time
import unicodedata

SCHEMA_VERSION = 1
MAX_SOURCE_BYTES = 65536
MAX_DATABASE_BYTES = 32 * 1024 * 1024
RELATIONS = frozenset(('references', 'contains', 'depends_on', 'supports', 'contradicts'))

# Presentation/function words do not describe the evidence being requested.
_QUERY_NOISE = frozenset(('the and for with from what which how many according '
                         'documentation local answer reply respond return only integer number '
                         'secondo documentazione locale rispondi soltanto solo numero intero '
                         'senza quale quali quanti quante qual del della dello delle degli '
                         'dei per ogni una uno con come che sono '
                         'massimo massima massimi massime minimo minima minimi minime').split())


def _rank_candidates(rows, query, *, deadline=None, filter_weak=False):
    """Rerank only FTS candidates; rare matched terms outrank repeated boilerplate.

    Accent folding follows the default FTS5 unicode61 matching convention.
    Stable ties preserve the original BM25 order. No source or scope expansion.
    """
    def terms(text):
        folded = ''.join(c for c in unicodedata.normalize('NFKD', text.casefold())
                         if not unicodedata.combining(c))
        return set(re.findall(r'\w{3,}', folded))

    wanted = terms(query) - _QUERY_NOISE
    matches = []
    frequency = {}
    for row in rows:
        _deadline(deadline)
        found = wanted & terms(row['content'])
        matches.append(found)
        for word in found:
            frequency[word] = frequency.get(word, 0) + 1
    scored = [(sum(1 / frequency[word] ** 2 for word in found), row)
              for row, found in zip(rows, matches)]
    if filter_weak and scored:
        # max_nodes is a ceiling, not a demand to pad a precise match with
        # generic boilerplate. Relative coverage keeps equally relevant topics.
        # Explicit source edges can still supply related nodes during traversal.
        strongest = max(score for score, _ in scored)
        if strongest > 0:
            scored = [(score, row) for score, row in scored if score >= strongest / 4]
    _deadline(deadline)
    return [row for _, row in sorted(scored, key=lambda item: -item[0])]


def _deadline(deadline):
    if deadline is not None and time.monotonic() >= deadline:
        raise TimeoutError('Graph preparation deadline')


def _local_path(value, *, strict=False):
    path=Path(value)
    # Reject UNC/device paths before resolve/stat can contact a network host.
    if str(path).startswith(('\\\\','//')):
        raise ValueError('Remote or device paths are not supported')
    if os.name=='nt':
        import ctypes
        anchor=path.anchor or Path.cwd().anchor
        if ctypes.windll.kernel32.GetDriveTypeW(str(anchor))==4:
            raise ValueError('Mapped network drives are not supported')
    resolved=path.resolve(strict=strict)
    if str(resolved).startswith(('\\\\','//')):
        raise ValueError('Remote source target is not supported')
    return resolved


class GraphMemory:
    def __init__(self, path, roots, *, writable=False):
        self.path = _local_path(path)
        self.roots = tuple(_local_path(root,strict=True) for root in roots)
        if not self.roots or any(not root.is_dir() for root in self.roots):
            raise ValueError('Explicit existing source roots required')
        self.writable = writable

    @classmethod
    def create(cls, path, *, roots):
        graph = cls(path, roots, writable=True)
        # Exclusive creation prevents adoption or migration of an unrelated DB.
        try:
            with graph.path.open('xb'):
                pass
        except FileExistsError as exc:
            raise ValueError('Archive already exists; use open_writer explicitly') from exc
        with closing(graph._connect()) as db, db:
            db.executescript('''
                CREATE TABLE metadata(version INTEGER NOT NULL);
                INSERT INTO metadata VALUES (1);
                CREATE TABLE nodes(
                    id TEXT PRIMARY KEY, scope TEXT NOT NULL, source TEXT NOT NULL,
                    source_sha256 TEXT NOT NULL, content TEXT NOT NULL,
                    updated REAL NOT NULL, current INTEGER NOT NULL,
                    kind TEXT NOT NULL, evidence TEXT NOT NULL, metadata TEXT NOT NULL);
                CREATE INDEX nodes_scope_source ON nodes(scope,source,current);
                CREATE VIRTUAL TABLE node_search USING fts5(id UNINDEXED, content);
                CREATE TABLE edges(
                    scope TEXT NOT NULL, src TEXT NOT NULL, dst TEXT NOT NULL,
                    relation TEXT NOT NULL, evidence TEXT NOT NULL, updated REAL NOT NULL,
                    PRIMARY KEY(scope,src,dst,relation));
                CREATE INDEX edges_scope_src ON edges(scope,src);
            ''')
        return graph

    @classmethod
    def open(cls, path, *, roots):
        graph = cls(path, roots)
        graph._validate()
        return graph

    @classmethod
    def open_writer(cls, path, *, roots):
        graph = cls.open(path, roots=roots)
        graph.writable = True
        return graph

    def _connect(self):
        if self.path.stat().st_size > MAX_DATABASE_BYTES:
            raise ValueError('Graph archive exceeds bounded size')
        mode = 'rw' if self.writable else 'ro'
        db = sqlite3.connect(self.path.as_uri() + '?mode=' + mode, uri=True, timeout=.02)
        db.row_factory = sqlite3.Row
        return db

    def _validate(self):
        with closing(self._connect()) as db:
            try:
                versions = db.execute('SELECT version FROM metadata').fetchall()
                if len(versions) != 1 or versions[0][0] != SCHEMA_VERSION:
                    raise ValueError('Unsupported graph schema')
                db.execute('SELECT id,scope,source,source_sha256,content,updated,current,kind,evidence,metadata FROM nodes LIMIT 0')
                db.execute('SELECT scope,src,dst,relation,evidence,updated FROM edges LIMIT 0')
                db.execute('SELECT id,content FROM node_search LIMIT 0')
            except sqlite3.DatabaseError as exc:
                raise ValueError('Invalid graph archive') from exc

    def _source(self, source):
        path = _local_path(source)
        if not any(path.is_relative_to(root) for root in self.roots):
            raise ValueError('Source outside authorized roots')
        return path

    def _read_source(self, path):
        if not path.is_file() or path.stat().st_size > MAX_SOURCE_BYTES:
            raise ValueError('Source missing or exceeds size budget')
        with path.open('rb') as stream:
            raw = stream.read(MAX_SOURCE_BYTES + 1)
        if len(raw) > MAX_SOURCE_BYTES:
            raise ValueError('Source exceeds size budget')
        return raw

    def ingest(self, scope, source, *, kind='document', metadata=None):
        if not self.writable:
            raise PermissionError('Inference archive is read-only')
        self._scope(scope)
        if kind not in ('document', 'fact', 'concept', 'module', 'component', 'result'):
            raise ValueError('Unknown node kind')
        path = self._source(source)
        raw = self._read_source(path)
        content = raw.decode('utf-8-sig', errors='strict')
        digest = hashlib.sha256(raw).hexdigest()
        node_id = hashlib.sha256(json.dumps([scope,str(path),digest]).encode()).hexdigest()
        encoded = json.dumps(metadata or {}, allow_nan=False)
        if metadata and '_hydra_span' in metadata:
            raise ValueError('Source span metadata is reserved for verified indexing')
        if len(encoded) > 4096:
            raise ValueError('Metadata exceeds budget')
        with closing(self._connect()) as db, db:
            if db.execute('SELECT count(*) FROM nodes').fetchone()[0] >= 10000 and db.execute('SELECT 1 FROM nodes WHERE id=?',(node_id,)).fetchone() is None:
                raise ValueError('Node capacity reached; preserve archive for operator review')
            db.execute('UPDATE nodes SET current=0 WHERE scope=? AND source=?', (scope,str(path)))
            db.execute('INSERT INTO nodes VALUES (?,?,?,?,?,?,1,?,?,?) ON CONFLICT(id) DO UPDATE SET current=1,updated=excluded.updated',
                       (node_id,scope,str(path),digest,content,time.time(),kind,'source',encoded))
            if db.execute('SELECT 1 FROM node_search WHERE id=?',(node_id,)).fetchone() is None:
                db.execute('INSERT INTO node_search(id,content) VALUES (?,?)',(node_id,content))
        return node_id

    def ingest_sections(self, scope, source, *, target_chars=2000, expected_sha256=None):
        """Index exact Markdown sections/paragraphs, with source character spans.

        target_chars is a grouping target, never permission to truncate a
        paragraph. A long paragraph stays whole and the compiler budget decides.
        No migration: spans use the existing version-1 metadata column.
        """
        if not self.writable:
            raise PermissionError('Inference archive is read-only')
        self._scope(scope)
        if type(target_chars) is not int or not 256<=target_chars<=8192:
            raise ValueError('Section target must be 256..8192 characters')
        path=self._source(source)
        raw=self._read_source(path)
        text=raw.decode('utf-8-sig',errors='strict')
        digest=hashlib.sha256(raw).hexdigest()
        if expected_sha256 is not None and digest!=expected_sha256:
            raise ValueError('SELECTED_SOURCE_DIGEST_CHANGED; no different bytes indexed')
        headings=[m.start() for m in re.finditer(r'(?m)^#{1,6}\s+.+$',text)]
        bounds=sorted({0,len(text),*headings})
        spans=[]
        for start,end in zip(bounds,bounds[1:]):
            paragraph_ends=[start+m.end() for m in re.finditer(r'\r?\n[ \t]*\r?\n',text[start:end])]+[end]
            cursor=start
            previous=start
            for stop in paragraph_ends:
                if stop-cursor>target_chars and previous>cursor:
                    spans.append((cursor,previous));cursor=previous
                previous=stop
            if cursor<end and text[cursor:end].strip():spans.append((cursor,end))
        if not spans or len(spans)>256:
            raise ValueError('Require 1..256 nonempty source sections')
        rows=[]
        for start,end in spans:
            node=hashlib.sha256(json.dumps([scope,str(path),digest,start,end]).encode()).hexdigest()
            metadata=json.dumps({'_hydra_span':{'start_char':start,'end_char':end}})
            rows.append((node,scope,str(path),digest,text[start:end],time.time(),'document','source',metadata))
        with closing(self._connect()) as db,db:
            new_count=sum(db.execute('SELECT 1 FROM nodes WHERE id=?',(row[0],)).fetchone() is None for row in rows)
            if db.execute('SELECT count(*) FROM nodes').fetchone()[0]+new_count>10000:
                raise ValueError('Node capacity reached; source update not applied')
            db.execute('UPDATE nodes SET current=0 WHERE scope=? AND source=?',(scope,str(path)))
            for row in rows:
                db.execute('INSERT INTO nodes VALUES (?,?,?,?,?,?,1,?,?,?) ON CONFLICT(id) DO UPDATE SET current=1,updated=excluded.updated',row)
                if db.execute('SELECT 1 FROM node_search WHERE id=?',(row[0],)).fetchone() is None:
                    db.execute('INSERT INTO node_search(id,content) VALUES (?,?)',(row[0],row[4]))
        return [row[0] for row in rows]

    @staticmethod
    def _scope(scope):
        if not isinstance(scope,str) or not 1 <= len(scope) <= 200:
            raise ValueError('Explicit bounded scope required')

    def relate(self, scope, src, dst, relation, *, evidence='source'):
        if not self.writable:
            raise PermissionError('Inference archive is read-only')
        self._scope(scope)
        if relation not in RELATIONS or evidence not in ('source','inference','hypothesis'):
            raise ValueError('Explicit typed relation and evidence required')
        with closing(self._connect()) as db, db:
            for node in (src,dst):
                if db.execute('SELECT 1 FROM nodes WHERE id=? AND scope=? AND current=1',(node,scope)).fetchone() is None:
                    raise ValueError('Missing, stale or cross-scope node')
            if db.execute('SELECT count(*) FROM edges').fetchone()[0] >= 20000:
                raise ValueError('Edge capacity reached')
            db.execute('INSERT INTO edges VALUES (?,?,?,?,?,?) ON CONFLICT(scope,src,dst,relation) DO UPDATE SET evidence=excluded.evidence,updated=excluded.updated',
                       (scope,src,dst,relation,evidence,time.time()))

    def retrieve(self, scope, query, *, allowed_sources, max_nodes=4, depth=1,
                 max_candidates=128, deadline=None, max_age_s=30*86400, ranked_node_ids=None):
        self._scope(scope)
        if type(max_age_s) not in (int,float) or not 1 <= max_age_s <= 365*86400:
            raise ValueError('Bounded source age required')
        for value,low,high in ((max_nodes,1,16),(depth,0,3),(max_candidates,1,256)):
            if type(value) is not int or not low <= value <= high:
                raise ValueError('Traversal limit out of range')
        _deadline(deadline)
        if not isinstance(query,str) or len(query) > 16384:
            raise ValueError('Bounded text query required')
        if len(allowed_sources) > 128:
            raise ValueError('Source allowlist exceeds budget')
        sources = sorted({str(self._source(s)) for s in allowed_sources})
        if ranked_node_ids is not None:
            if (not isinstance(ranked_node_ids,list) or len(ranked_node_ids)>16
                    or len(set(ranked_node_ids))!=len(ranked_node_ids)
                    or any(not isinstance(v,str) or re.fullmatch(r'[0-9a-f]{64}',v) is None for v in ranked_node_ids)):
                raise ValueError('Bounded ranked node identities required')
            if not ranked_node_ids:return []
        if not sources:
            return []
        # Preserve query order; alphabetic truncation discarded distinctive API
        # names near the end of otherwise short questions.
        words = list(dict.fromkeys(re.findall(r'\w{3,}',query.casefold())))[:32]
        if not words:
            return []
        marks = ','.join('?' for _ in sources)
        # SQLite's installed FTS5 index narrows candidates before reading source
        # files. No directory walk or full-corpus source scan during inference.
        sql = f'''SELECT n.* FROM node_search JOIN nodes n ON n.id=node_search.id
                  WHERE node_search MATCH ? AND n.scope=? AND n.current=1
                  AND n.source IN ({marks}) AND n.updated>=?
                  ORDER BY bm25(node_search),n.id LIMIT ?'''
        with closing(self._connect()) as db:
            db.set_progress_handler(lambda: int(deadline is not None and time.monotonic() >= deadline), 100)
            match=' OR '.join('"'+word+'"' for word in words)
            if ranked_node_ids is None:
                candidates = db.execute(sql,(match,scope,*sources,time.time()-max_age_s,max_candidates)).fetchall()
                candidates = _rank_candidates(candidates, query, deadline=deadline, filter_weak=True)
            else:
                # Dense/hybrid ranking supplies identities, never trusted bytes.
                # Re-read current archive and validate scope/allowlist/hash/span
                # through the same verification below before compiling context.
                ids=','.join('?' for _ in ranked_node_ids)
                candidates=db.execute(f'SELECT * FROM nodes WHERE id IN ({ids}) AND scope=? AND current=1 AND source IN ({marks}) AND updated>=?',(*ranked_node_ids,scope,*sources,time.time()-max_age_s)).fetchall()
                candidates=sorted(candidates,key=lambda row:ranked_node_ids.index(row['id']))
            # Request-local snapshots only: sections of one document share its
            # verified bytes; subsequent requests must read and hash it again.
            source_snapshots = {}
            def verify(row):
                _deadline(deadline)
                try:
                    source = row['source']
                    if source not in source_snapshots:
                        source_snapshots[source] = None
                        raw = self._read_source(self._source(source))
                        source_snapshots[source] = (hashlib.sha256(raw).hexdigest(),raw.decode('utf-8-sig'))
                    snapshot = source_snapshots[source]
                    if snapshot is None or snapshot[0] != row['source_sha256']:
                        return None
                    # Validate archived content too: a changed archive is not a source.
                    text=snapshot[1]
                    metadata=json.loads(row['metadata'])
                    span=metadata.get('_hydra_span')
                    if span is not None:
                        if (not isinstance(span,dict) or set(span)!={'start_char','end_char'}
                                or any(type(v) is not int for v in span.values())
                                or not 0<=span['start_char']<span['end_char']<=len(text)):
                            return None
                        text=text[span['start_char']:span['end_char']]
                    if text != row['content'] or row['evidence'] != 'source':
                        return None
                except (OSError,ValueError):
                    return None
                return dict(row,source_span=span)
            result = {}
            for row in candidates:
                verified=verify(row)
                if verified:
                    result[row['id']]=verified
                if len(result)>=max_nodes:
                    break
            frontier = list(result)
            for _ in range(depth):
                following = []
                for node in frontier:
                    _deadline(deadline)
                    for edge in db.execute('SELECT dst,relation FROM edges WHERE scope=? AND src=? AND evidence=? ORDER BY dst LIMIT 256',(scope,node,'source')):
                        if edge['relation'] in RELATIONS and edge['dst'] not in result and len(result)<max_nodes:
                            neighbor=db.execute(f'SELECT * FROM nodes WHERE id=? AND scope=? AND current=1 AND source IN ({marks}) AND updated>=?',
                                                (edge['dst'],scope,*sources,time.time()-max_age_s)).fetchone()
                            verified=verify(neighbor) if neighbor else None
                            if verified:
                                result[edge['dst']]=verified
                                following.append(edge['dst'])
                frontier = following
            _deadline(deadline)
            return list(result.values())
