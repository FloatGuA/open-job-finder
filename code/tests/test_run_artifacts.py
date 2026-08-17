"""run 产物的读取端点。

照抄现有两个文件端点（/api/apply-failure/{name}、/api/pending-applications/screenshot/{name}）
的约定：bare filename + 固定 base dir + 拒绝路径穿越 + FileResponse。

**多一处**：那两个端点的 base dir 是常量，只有 {name} 来自用户；这里多一段 {run_id}
也参与定位目录。解法是不拼——用 find_run_file（glob + 比对 run_start 的字段，
从不把用户输入拼进路径）拿到 jsonl，再取同名目录。
"""
import json

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    import dashboard.server as server
    runs = tmp_path / "runs"
    (runs / "m1_art").mkdir(parents=True)
    (runs / "m1_art.jsonl").write_text(
        json.dumps({"event": "run_start", "run_id": "m1_art", "pipeline": "m1"}) + "\n",
        encoding="utf-8")
    (runs / "m1_art" / "find_jobs_snapshot.txt").write_text(
        'uid=2_0 RootWebArea "招聘"', encoding="utf-8")
    monkeypatch.setattr(server, "RUNS_DIR", runs)
    return TestClient(server.app)


class TestArtifactEndpoint:
    def test_serves_a_snapshot_as_plain_text(self, client):
        r = client.get("/api/runs/m1_art/artifacts/find_jobs_snapshot.txt")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/plain")
        assert "RootWebArea" in r.text

    def test_unknown_run_is_404(self, client):
        assert client.get("/api/runs/nope/artifacts/x.txt").status_code == 404

    def test_missing_file_is_404(self, client):
        assert client.get("/api/runs/m1_art/artifacts/absent.txt").status_code == 404

    @pytest.mark.parametrize("name", ["../m1_art.jsonl", "a/b.txt", "a\\b.txt"])
    def test_path_traversal_is_rejected(self, client, name):
        assert client.get(f"/api/runs/m1_art/artifacts/{name}").status_code in (400, 404)

    def test_unknown_extension_is_rejected(self, client):
        assert client.get("/api/runs/m1_art/artifacts/x.exe").status_code == 400


class TestDeleteRunTakesTheDirectory:
    def test_deleting_a_run_log_removes_its_artifacts_dir(self, tmp_path):
        """两处分别删就会留孤儿，而这些文件装的是真实公司/HR 的 PII
        （/api/ops/artifacts 的注释自己写着没有自动清理）。"""
        from services import artifact_cleanup

        runs = tmp_path / "runs"
        (runs / "m1_del").mkdir(parents=True)
        (runs / "m1_del.jsonl").write_text("{}\n", encoding="utf-8")
        (runs / "m1_del" / "snap.txt").write_text("x", encoding="utf-8")

        assert artifact_cleanup.delete_run_log(runs, "m1_del.jsonl") is True
        assert not (runs / "m1_del.jsonl").exists()
        assert not (runs / "m1_del").exists()
