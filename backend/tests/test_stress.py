"""压力测试 — 并发查询 + 性能基准"""

import time
import statistics
import concurrent.futures

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from backend.app.main import app
    return TestClient(app)


@pytest.fixture
def headers(client):
    r = client.post("/api/auth/login", json={"username":"admin","password":"admin123"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


class TestConcurrency:
    """并发查询压力测试"""

    def _query(self, client, headers, q):
        start = time.perf_counter()
        r = client.post("/api/chat", json={"q": q}, headers=headers)
        elapsed = (time.perf_counter() - start) * 1000
        return {"status": r.status_code, "type": r.json().get("type"), "elapsed_ms": elapsed}

    def test_concurrent_queries(self, client, headers):
        """10并发查询"""
        queries = [
            "年度累计中标总额", "存量客户总数", "应收账款总余额",
            "各地市中标额", "本期中标项目数", "商机签约转化率",
            "年度累计中标总额", "存量客户总数", "应收账款总余额",
            "各地市中标额",
        ]
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
            futures = [pool.submit(self._query, client, headers, q) for q in queries]
            results = [f.result() for f in futures]

        success = [r for r in results if r["status"] == 200]
        elapsed = [r["elapsed_ms"] for r in success]

        print(f"\n  Concurrent: {len(success)}/{len(queries)} success")
        print(f"  Latency: min={min(elapsed):.0f}ms, avg={statistics.mean(elapsed):.0f}ms, max={max(elapsed):.0f}ms")

        assert len(success) >= len(queries) * 0.9  # 90%+ success
        assert statistics.mean(elapsed) < 5000     # avg < 5s

    def test_sequential_queries(self, client, headers):
        """20次顺序查询, 测试缓存效果"""
        queries = ["年度累计中标总额"] * 20
        times_ms = []
        for q in queries:
            start = time.perf_counter()
            r = client.post("/api/chat", json={"q": q}, headers=headers)
            times_ms.append((time.perf_counter() - start) * 1000)
            assert r.status_code == 200

        avg_first_5 = statistics.mean(times_ms[:5])
        avg_last_5 = statistics.mean(times_ms[-5:])
        print(f"\n  First 5 avg: {avg_first_5:.0f}ms, Last 5 avg: {avg_last_5:.0f}ms")
        print(f"  Cache effect: {((avg_first_5 - avg_last_5) / avg_first_5 * 100):.0f}% faster")

    def test_dashboard_load(self, client, headers):
        """仪表盘加载速度"""
        start = time.perf_counter()
        r = client.get("/api/dashboard", headers=headers)
        elapsed = (time.perf_counter() - start) * 1000
        assert r.status_code == 200
        print(f"\n  Dashboard load: {elapsed:.0f}ms")
        assert elapsed < 3000  # < 3s

    def test_status_endpoint(self, client):
        """状态端点 (无认证, 最快路径)"""
        start = time.perf_counter()
        r = client.get("/api/status")
        elapsed = (time.perf_counter() - start) * 1000
        assert r.status_code == 200
        print(f"  Status endpoint: {elapsed:.0f}ms")
        assert elapsed < 100  # < 100ms

    def test_concurrent_different_users(self, client):
        """3个不同角色并发查询"""
        users = [
            ("admin", "admin123"),
            ("leader", "leader123"),
            ("employee", "emp123"),
        ]
        tokens = []
        for u, p in users:
            r = client.post("/api/auth/login", json={"username": u, "password": p})
            if r.status_code == 200:
                tokens.append((u, r.json()["access_token"]))

        def query_user(token):
            h = {"Authorization": f"Bearer {token}"}
            r = client.post("/api/chat", json={"q": "年度累计中标总额"}, headers=h)
            return r.status_code, r.json().get("type")

        with concurrent.futures.ThreadPoolExecutor(max_workers=len(tokens)) as pool:
            futures = [pool.submit(query_user, t) for _, t in tokens]
            results = [f.result() for f in futures]

        for (u, _), (status, typ) in zip(tokens, results):
            print(f"  {u}: {status} {typ}")
            assert status == 200
