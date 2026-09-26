import json
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from matrix.server import FileWatcher, Hub, RecommendationLog, make_handler, replay

FIXTURE = Path(__file__).parent / "fixtures" / "state_reward_shop_levelup.json"


class ServerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.rec_log = RecommendationLog(self.dir / "matrix_logs")
        self.hub = Hub({"source": "demo", "bodyparts": [{"id": "x"}], "mutations": []}, self.rec_log)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.hub))
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()

    def url(self, path):
        return f"http://127.0.0.1:{self.port}{path}"

    def get_json(self, path):
        with urllib.request.urlopen(self.url(path), timeout=5) as r:
            return json.loads(r.read())

    def test_post_state_then_recommend(self):
        body = FIXTURE.read_bytes()
        req = urllib.request.Request(
            self.url("/state"), data=body, method="POST", headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=5) as r:
            self.assertEqual(r.status, 204)
        rec = self.get_json("/recommend")
        self.assertTrue(rec["ok"])
        self.assertEqual(len(rec["groups"]), 3)
        snap = self.get_json("/state")
        self.assertEqual(snap["catalog_source"], "demo")
        self.assertEqual(snap["state"]["session"], "1790000000")

    def test_recommendation_log_written_once_per_ranking(self):
        state = json.loads(FIXTURE.read_text())
        self.hub.set_state(state)
        self.hub.set_state(state)
        lines = self.rec_log.path.read_text().splitlines()
        self.assertEqual(len(lines), 3)
        entry = json.loads(lines[0])
        self.assertEqual(entry["ev"], "recommendation")
        self.assertEqual(entry["session"], "1790000000")
        self.assertIn("ranking", entry)

    def test_static_and_traversal(self):
        with urllib.request.urlopen(self.url("/"), timeout=5) as r:
            self.assertIn(b"Pathogenic Matrix", r.read())
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(self.url("/../matrix/server.py"), timeout=5)
        self.assertEqual(ctx.exception.code, 404)

    def test_sse_pushes_update(self):
        got = []

        def listen():
            with urllib.request.urlopen(self.url("/events"), timeout=5) as r:
                for raw in r:
                    line = raw.decode().strip()
                    if line.startswith("data: "):
                        got.append(json.loads(line[6:]))
                        if len(got) == 2:
                            return

        t = threading.Thread(target=listen, daemon=True)
        t.start()
        for _ in range(50):
            if got:
                break
            threading.Event().wait(0.05)
        self.hub.set_state(json.loads(FIXTURE.read_text()))
        t.join(timeout=5)
        self.assertEqual(len(got), 2)
        self.assertIn("catalog", got[0])
        self.assertTrue(got[1]["rec"]["ok"])

    def test_file_watcher_picks_up_state_and_catalog(self):
        (self.dir / "matrix_catalog.json").write_text(json.dumps({"bodyparts": [{"id": "live"}], "mutations": []}))
        (self.dir / "matrix_state.json").write_text(FIXTURE.read_text())
        FileWatcher(self.hub, self.dir).poll_once()
        self.assertEqual(self.hub.catalog.source, "live")
        self.assertTrue(self.hub.rec["ok"])

    def test_replay_session_log(self):
        state = json.loads(FIXTURE.read_text())
        log = self.dir / "session_1.jsonl"
        log.write_text(
            "\n".join(
                [
                    json.dumps({"ev": "session_start", "ts": 1}),
                    json.dumps({"ev": "catalog", "ts": 1, "catalog": {"bodyparts": [{"id": "live"}], "mutations": []}}),
                    "not json",
                    json.dumps({"ev": "choice_presented", "ts": 2, "choice_id": "c", "state": state}),
                ]
            )
        )
        replay(self.hub, log, 0, threading.Event())
        self.assertEqual(self.hub.catalog.source, "live")
        self.assertEqual(self.hub.state["session"], "1790000000")


if __name__ == "__main__":
    unittest.main()
