import warnings, os, uuid, tempfile
warnings.filterwarnings('ignore')

# Manual smoke script, not a unittest module. Point the H-MEM engine at
# temp storage BEFORE importing the app, or its /ask flow would store
# fixture runs in the real data/memory.db (the old test-ordering flaw).
_TMP = tempfile.mkdtemp(prefix="receipts-pipeline-test-")
os.environ["RECEIPTS_MEMORY_DB"] = os.path.join(_TMP, "memory.db")
os.environ["RECEIPTS_AUDIT_LOG"] = os.path.join(_TMP, "logs", "memory-audit.jsonl")

class FakeTable:
    def __init__(self, store):
        self.store = store

    def insert(self, data):
        row = dict(data)
        row.setdefault('id', str(uuid.uuid4()))
        self.store.append(row)
        class R:
            data = [row]
        class Exe:
            def execute(self):
                return R()
        return Exe()

    def update(self, data):
        store = self.store
        class U:
            def eq(self, col, val):
                for r in store:
                    if str(r.get(col)) == str(val):
                        r.update(data)
                class R2:
                    def execute(self):
                        return self
                    data = []
                return R2()
        return U()

    def eq(self, col, val):
        store = self.store
        class R:
            data = [r for r in store if str(r.get(col)) == str(val)]
            def execute(self):
                return self
            def order(self, col, desc=False):
                self.data = sorted(self.data, key=lambda r: r.get(col, 0), reverse=desc)
                return self
        return R()

    def select(self, *a):
        store = self.store
        class S:
            def eq(self, col, val):
                class R:
                    data = [r for r in store if str(r.get(col)) == str(val)]
                return R()
            def order(self, col):
                class R:
                    data = sorted(store, key=lambda r: r.get(col, 0))
                return R()
            def limit(self, n):
                class R:
                    data = store[:n]
                return R()
            def execute(self):
                class R:
                    data = store
                return R()
        return S()

    def in_(self, col, vals):
        vset = set(str(v) for v in vals)
        store = self.store
        class R:
            data = [r for r in store if str(r.get(col)) in vset]
            def execute(self):
                return self
        return R()

class FakeSupabase:
    def __init__(self):
        self.tables = {}
    def table(self, name):
        return FakeTable(self.tables.setdefault(name, []))

import app as receipts_app
fake = FakeSupabase()
receipts_app.supabase = fake

async def fake_search(query, timeout_sec=12.0):
    return [
        {'title': 'Standing desks: health benefits review',
         'href': 'https://www.ncbi.nlm.nih.gov/pmc/articles/PMC1234567/',
         'body': 'A 2023 review found standing desks reduced sedentary time by 1.2 hours per workday but showed no significant effect on productivity measures.'},
        {'title': 'Cochrane review: sit-stand desks',
         'href': 'https://www.cochranelibrary.com/cdsr/doi/10.1002/full',
         'body': 'Sit-stand desks probably reduce sitting time at work in the short term; effects on productivity remain uncertain with low-certainty evidence.'},
        {'title': 'Mayo Clinic: standing desk ergonomics',
         'href': 'https://www.mayoclinic.org/healthy-lifestyle/adult-health/in-depth/desk-jobs/art-20048609',
         'body': 'Using a standing desk may help back pain but standing too long can cause leg and foot problems; alternate sitting and standing.'},
    ]

receipts_app.search_subquestion = fake_search

from fastapi.testclient import TestClient
client = TestClient(receipts_app.app)
print('HEALTH:', client.get('/health').json(), flush=True)
resp = client.post('/ask', json={'question': 'Do standing desks actually improve productivity?'})
print('ASK STATUS:', resp.status_code, flush=True)
if resp.status_code == 200:
    data = resp.json()
    print('RUN:', data['status'], '| claims:', len(data['claims']), '| trace:', len(data['trace_steps']), flush=True)
    for c in data['claims']:
        print('CLAIM', c['confidence'], ':', c['claim_text'][:80], '| cites:', len(c['citations']), flush=True)
    print('ANSWER:', (data['answer'] or '')[:150], flush=True)
    # also test GET run and override
    rid = data['id']
    g = client.get(f'/runs/{rid}')
    print('GET RUN:', g.status_code, 'claims:', len(g.json()['claims']), flush=True)
    cid = data['claims'][0]['id']
    o = client.post(f'/claims/{cid}/override', json={'note': 'test override note'})
    print('OVERRIDE:', o.status_code, o.json().get('status'), flush=True)
else:
    print(resp.text[:800])
