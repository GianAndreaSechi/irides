import pytest
from unittest.mock import patch
from core.db_connector.job_store import JobStore
from core.db_connector.models.scan_job import ScanScope, ScanStatus
from core.db_connector.exporting import ExportFormat, ExportOptions

try:
    import fakeredis  # type: ignore
except ImportError:
    fakeredis = None


class _InMemoryPipeline:
    def __init__(self, client: "_InMemoryRedis"):
        self._client = client
        self._ops = []

    def hset(self, name, key=None, value=None, mapping=None, **kwargs):
        self._ops.append(("hset", (name, key, value), {"mapping": mapping, **kwargs}))
        return self

    def lset(self, name, index, value):
        self._ops.append(("lset", (name, index, value), {}))
        return self

    def llen(self, name):
        self._ops.append(("llen", (name,), {}))
        return self

    def expire(self, key, ttl):
        self._ops.append(("expire", (key, ttl), {}))
        return self

    def zadd(self, key, mapping):
        self._ops.append(("zadd", (key, mapping), {}))
        return self

    def zremrangebyscore(self, key, min_score, max_score):
        self._ops.append(("zremrangebyscore", (key, min_score, max_score), {}))
        return self

    def xadd(self, key, fields):
        self._ops.append(("xadd", (key, fields), {}))
        return self

    def rpush(self, key, *values):
        self._ops.append(("rpush", (key, *values), {}))
        return self

    def execute(self):
        results = []
        for method, args, kwargs in self._ops:
            results.append(getattr(self._client, method)(*args, **kwargs))
        self._ops.clear()
        return results


class _InMemoryRedis:
    def __init__(self, decode_responses: bool = True):
        self.hashes = {}
        self.lists = {}
        self.zsets = {}
        self.streams = {}
        self.groups = {}
        self.pending = {}
        self._seq = 0

    def pipeline(self):
        return _InMemoryPipeline(self)

    def xgroup_create(self, name, groupname, id="0", mkstream=False):
        if mkstream and name not in self.streams:
            self.streams[name] = []
        self.groups.setdefault(name, set()).add(groupname)
        self.pending.setdefault((name, groupname), {})

    def hset(self, name, key=None, value=None, mapping=None):
        bucket = self.hashes.setdefault(name, {})
        if key is not None:
            bucket[str(key)] = str(value)
        if mapping:
            for k, v in mapping.items():
                bucket[str(k)] = str(v)
        return len(bucket)

    def hget(self, name, key):
        bucket = self.hashes.get(name, {})
        return bucket.get(str(key))

    def hgetall(self, name):
        return dict(self.hashes.get(name, {}))

    def expire(self, name, time):
        return True

    def zadd(self, name, mapping):
        zset = self.zsets.setdefault(name, {})
        for member, score in mapping.items():
            zset[str(member)] = float(score)
        return len(mapping)

    def zremrangebyscore(self, name, min_score, max_score):
        zset = self.zsets.get(name, {})
        low = float("-inf") if min_score == "-inf" else float(min_score)
        high = float("inf") if max_score == "+inf" else float(max_score)
        to_del = [m for m, s in zset.items() if low <= s <= high]
        for m in to_del:
            del zset[m]
        return len(to_del)

    def zrevrange(self, name, start, end):
        zset = self.zsets.get(name, {})
        ordered = [m for m, _ in sorted(zset.items(), key=lambda kv: kv[1], reverse=True)]
        if end == -1:
            return ordered[start:]
        return ordered[start : end + 1]

    def xadd(self, name, fields):
        self._seq += 1
        msg_id = f"{self._seq}-0"
        stream = self.streams.setdefault(name, [])
        stream.append((msg_id, {str(k): str(v) for k, v in fields.items()}))
        return msg_id

    def xrange(self, name, min="-", max="+", count=None):
        entries = list(self.streams.get(name, []))
        return entries[:count] if count is not None else entries

    def rpush(self, name, *values):
        lst = self.lists.setdefault(name, [])
        lst.extend(str(v) for v in values)
        return len(lst)

    def lrange(self, name, start, end):
        lst = self.lists.get(name, [])
        if end == -1:
            return list(lst[start:])
        return list(lst[start : end + 1])

    def lset(self, name, index, value):
        lst = self.lists.setdefault(name, [])
        lst[index] = str(value)
        return True

    def llen(self, name):
        return len(self.lists.get(name, []))

    def xpending_range(self, name, groupname, min="-", max="+", count=10):
        pend = self.pending.get((name, groupname), {})
        return list(pend.values())[:count]

    def xclaim(self, name, groupname, consumername, min_idle_time, message_ids, justid=False):
        pend = self.pending.get((name, groupname), {})
        stream_map = dict(self.streams.get(name, []))
        claimed = []
        for mid in message_ids:
            if mid in pend and pend[mid].get("time_since_delivered", 0) >= min_idle_time:
                pend[mid]["name"] = consumername
                pend[mid]["time_since_delivered"] = 0
                if justid:
                    claimed.append(mid)
                elif mid in stream_map:
                    claimed.append((mid, stream_map[mid]))
        return claimed

    def xack(self, name, groupname, *ids):
        pend = self.pending.get((name, groupname), {})
        removed = 0
        for mid in ids:
            if mid in pend:
                del pend[mid]
                removed += 1
        return removed

    def xdel(self, name, *ids):
        if name not in self.streams:
            return 0
        id_set = set(ids)
        before = len(self.streams[name])
        self.streams[name] = [(mid, data) for mid, data in self.streams[name] if mid not in id_set]
        return before - len(self.streams[name])


@pytest.fixture
def job_store():
    fake = (
        fakeredis.FakeRedis(decode_responses=True)
        if fakeredis is not None
        else _InMemoryRedis(decode_responses=True)
    )
    with patch("core.db_connector.job_store.redis.Redis", return_value=fake):
        store = JobStore(prefix="test")
    return store


SCOPE = ScanScope(config_name="cfg", instance_name="inst", schema_name="sch")
SCOPE_FULL = ScanScope(
    config_name="cfg",
    instance_name="inst",
    schema_name="sch",
    no_cache=True,
    generate_ai_docs=True,
    save_metadata=False,
    export_options=ExportOptions(formats=[ExportFormat.OKF], preformat=False),
)


class TestEnqueue:
    def test_returns_pending_job(self, job_store):
        job = job_store.enqueue(SCOPE)
        assert job.status == ScanStatus.PENDING
        assert job.job_id

    def test_job_retrievable_after_enqueue(self, job_store):
        job = job_store.enqueue(SCOPE)
        fetched = job_store.get_job(job.job_id)
        assert fetched is not None
        assert fetched.job_id == job.job_id
        assert fetched.status == ScanStatus.PENDING

    def test_scope_preserved(self, job_store):
        job = job_store.enqueue(SCOPE_FULL)
        fetched = job_store.get_job(job.job_id)
        assert fetched.scope.config_name == "cfg"
        assert fetched.scope.no_cache is True
        assert fetched.scope.generate_ai_docs is True
        assert fetched.scope.save_metadata is False
        assert fetched.scope.export_options.formats == [ExportFormat.OKF]
        assert fetched.scope.export_options.preformat is False

    def test_default_exports_preserved(self, job_store):
        job = job_store.enqueue(SCOPE)
        fetched = job_store.get_job(job.job_id)
        assert fetched.scope.export_options.formats == [ExportFormat.MARKDOWN, ExportFormat.OKF]
        assert fetched.scope.export_options.preformat is True

    def test_stream_contains_export_options(self, job_store):
        job_store.enqueue(SCOPE_FULL)
        messages = job_store.r.xrange(job_store._stream_key())
        fields = messages[-1][1]
        assert fields["export_formats"] == '["okf"]'
        assert fields["export_preformat"] == "false"

    def test_job_appears_in_list(self, job_store):
        job = job_store.enqueue(SCOPE)
        jobs = job_store.list_jobs()
        assert any(j.job_id == job.job_id for j in jobs)


class TestStatusTransitions:
    def test_mark_running(self, job_store):
        job = job_store.enqueue(SCOPE)
        job_store.mark_running(job.job_id)
        fetched = job_store.get_job(job.job_id)
        assert fetched.status == ScanStatus.RUNNING
        assert fetched.started_at is not None

    def test_mark_completed(self, job_store):
        job = job_store.enqueue(SCOPE)
        job_store.mark_completed(job.job_id, result_count=42)
        fetched = job_store.get_job(job.job_id)
        assert fetched.status == ScanStatus.COMPLETED
        assert fetched.result_count == 42
        assert fetched.completed_at is not None

    def test_mark_failed(self, job_store):
        job = job_store.enqueue(SCOPE)
        job_store.mark_failed(job.job_id, error="something went wrong")
        fetched = job_store.get_job(job.job_id)
        assert fetched.status == ScanStatus.FAILED
        assert fetched.error == "something went wrong"

    def test_mark_partial(self, job_store):
        job = job_store.enqueue(SCOPE)
        job_store.mark_partial(job.job_id, result_count=5, error="partial error")
        fetched = job_store.get_job(job.job_id)
        assert fetched.status == ScanStatus.PARTIAL
        assert fetched.result_count == 5
        assert "partial error" in fetched.error


class TestResults:
    def test_append_and_get_results(self, job_store):
        job = job_store.enqueue(SCOPE)
        job_store.append_result(job.job_id, {"table": "users", "columns": []})
        job_store.append_result(job.job_id, {"table": "orders", "columns": []})
        results = job_store.get_results(job.job_id)
        assert len(results) == 2
        assert results[0]["table"] == "users"
        assert results[1]["table"] == "orders"

    def test_empty_results_for_new_job(self, job_store):
        job = job_store.enqueue(SCOPE)
        assert job_store.get_results(job.job_id) == []

    def test_append_result_deduplicates_by_table_identity(self, job_store):
        job = job_store.enqueue(SCOPE)
        first = {
            "config_name": "cfg",
            "instance_name": "inst",
            "schema_name": "sch",
            "table_name": "users",
            "columns": [{"name": "id"}],
        }
        second = {
            "config_name": "cfg",
            "instance_name": "inst",
            "schema_name": "sch",
            "table_name": "users",
            "columns": [{"name": "id"}, {"name": "email"}],
        }
        job_store.append_result(job.job_id, first)
        job_store.append_result(job.job_id, second)
        results = job_store.get_results(job.job_id)
        assert len(results) == 1
        assert len(results[0]["columns"]) == 2

    def test_append_result_uses_hash_index_not_lrange(self, job_store):
        job = job_store.enqueue(SCOPE)
        row = {
            "config_name": "cfg",
            "instance_name": "inst",
            "schema_name": "sch",
            "table_name": "users",
            "columns": [{"name": "id"}],
        }
        with patch.object(job_store.r, "lrange", wraps=job_store.r.lrange) as spy_lrange:
            job_store.append_result(job.job_id, row)
            job_store.append_result(job.job_id, {**row, "columns": [{"name": "id"}, {"name": "email"}]})
            spy_lrange.assert_not_called()

    def test_heartbeat_resets_pel_idle_when_message_id_passed(self, job_store):
        from core.db_connector.job_store import CONSUMER_GROUP

        job = job_store.enqueue(SCOPE)
        stream_key = job_store._stream_key()
        messages = job_store.r.xrange(stream_key)
        msg_id = messages[-1][0]
        with patch.object(job_store.r, "xclaim") as mock_xclaim:
            job_store.heartbeat(job.job_id, consumer_name="worker-1", message_id=msg_id)
            mock_xclaim.assert_called_once_with(
                stream_key,
                CONSUMER_GROUP,
                "worker-1",
                min_idle_time=0,
                message_ids=[msg_id],
                justid=True,
            )


class TestListJobs:
    def test_returns_newest_first(self, job_store):
        j1 = job_store.enqueue(SCOPE)
        j2 = job_store.enqueue(SCOPE)
        jobs = job_store.list_jobs(limit=10)
        ids = [j.job_id for j in jobs]
        assert ids.index(j2.job_id) < ids.index(j1.job_id)

    def test_limit_respected(self, job_store):
        for _ in range(5):
            job_store.enqueue(SCOPE)
        jobs = job_store.list_jobs(limit=3)
        assert len(jobs) == 3

    def test_get_job_returns_none_for_unknown(self, job_store):
        assert job_store.get_job("nonexistent-id") is None


class TestNoneScope:
    def test_none_scope_fields_preserved(self, job_store):
        scope = ScanScope(config_name=None, instance_name=None, schema_name=None)
        job = job_store.enqueue(scope)
        fetched = job_store.get_job(job.job_id)
        assert fetched.scope.config_name is None
        assert fetched.scope.instance_name is None
        assert fetched.scope.schema_name is None
