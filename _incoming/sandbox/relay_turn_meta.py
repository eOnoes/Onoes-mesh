"""Durable presentation metadata; never a second model conversation store."""
import json
import time


def ensure(store):
    db = store.connect()
    try:
        db.execute("""CREATE TABLE IF NOT EXISTS relay_turn_meta (
            run_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, input TEXT NOT NULL,
            note TEXT NOT NULL, paper TEXT NOT NULL, reply_json TEXT NOT NULL,
            files_json TEXT NOT NULL, output TEXT NOT NULL DEFAULT '', created_at REAL NOT NULL
        ) STRICT""")
        db.commit()
    finally:
        db.close()


def save(store, run_id, session_id, input_text, note, paper=None, reply=None, files=None, output=''):
    ensure(store)
    if reply is not None:
        if not isinstance(reply, dict) or not isinstance(reply.get('id'), str):
            raise ValueError('Invalid reply link.')
        reply = {'id': reply['id'][:128], 'who': str(reply.get('who', 'Echo'))[:20],
                 'text': str(reply.get('text', ''))[:1000]}
    db = store.connect()
    try:
        db.execute("""INSERT OR IGNORE INTO relay_turn_meta
            (run_id,session_id,input,note,paper,reply_json,files_json,output,created_at)
            VALUES (?,?,?,?,?,?,?,?,?)""", (run_id,session_id,input_text,note or '',paper or '',
            json.dumps(reply),json.dumps(files or []),output or '',time.time()))
        db.commit()
    finally:
        db.close()


def set_output(store, run_id, output):
    ensure(store)
    db = store.connect()
    try:
        db.execute('UPDATE relay_turn_meta SET output=? WHERE run_id=?', (output or '',run_id))
        db.commit()
    finally:
        db.close()


def has_result(store, run_id):
    """True when this turn's final local result has been observed, including an empty string."""
    ensure(store)
    db = store.connect()
    try:
        row = db.execute('SELECT output FROM relay_turn_meta WHERE run_id=?', (run_id,)).fetchone()
        return row is not None
    finally:
        db.close()


def local_result(store, run_id):
    ensure(store)
    db = store.connect()
    try:
        row = db.execute('SELECT output FROM relay_turn_meta WHERE run_id=?', (run_id,)).fetchone()
        return row['output'] if row else None
    finally:
        db.close()


def decorate(store, session_id, turns):
    ensure(store)
    db = store.connect()
    try:
        rows = [dict(r) for r in db.execute('SELECT * FROM relay_turn_meta WHERE session_id=? ORDER BY created_at', (session_id,))]
    finally:
        db.close()
    used = set()
    for turn in turns:
        for row in rows:
            token = (row['run_id'], turn['who'])
            expected = row['input'] if turn['who'] == 'Eddie' else row['output']
            matches = turn['text'].strip() == expected.strip()
            if turn['who'] == 'Eddie' and json.loads(row['files_json']):
                matches = matches or turn['text'].strip() == (expected + '\n[screenshot]').strip()
            if token in used or not expected or not matches:
                continue
            used.add(token)
            turn['id'] = ('msg-u-' if turn['who'] == 'Eddie' else 'msg-a-') + row['run_id']
            if turn['who'] == 'Eddie':
                turn['text'] = row['note'] or ('Pasted prompt.' if row['paper'] else 'Photo.')
                turn['paper'] = row['paper'] or None
                turn['reply'] = json.loads(row['reply_json'])
                turn['files'] = json.loads(row['files_json'])
            break
    return turns
