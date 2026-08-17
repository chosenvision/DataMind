import json
import os
import sys
import tempfile
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datamind.agent import DataAnalystAgent  # noqa: E402
from datamind.config import UserConfig  # noqa: E402

_TEXT_SUFFIXES = {".csv", ".tsv", ".json"}


def _suffix_for(filename: str) -> str:
    ext = os.path.splitext(filename or "")[1].lower()
    return ext if ext in _TEXT_SUFFIXES else ".csv"


class handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        try:
            length = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, json.JSONDecodeError):
            self._send_json(400, {"error": "Invalid JSON body"})
            return

        content = payload.get("content")
        if not content:
            self._send_json(400, {"error": "Missing 'content' (dataset text)"})
            return

        if not os.environ.get("GEMINI_API_KEY"):
            self._send_json(500, {"error": "Server is not configured with GEMINI_API_KEY"})
            return

        try:
            config = UserConfig(
                preferred_tool=payload.get("tool") or "Python",
                analysis_depth=payload.get("depth") or "Standard Analysis",
                dashboard_objective=payload.get("objective") or None,
                business_context=payload.get("context") or None,
                business_questions=payload.get("questions") or None,
                primary_goal=payload.get("goal") or None,
                target_audience=payload.get("audience") or None,
                brand_colors=payload.get("brandColors") or None,
                preferred_style=payload.get("style") or None,
            )
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
            return

        tmp_path = None
        try:
            suffix = _suffix_for(payload.get("filename"))
            with tempfile.NamedTemporaryFile(mode="w", suffix=suffix, delete=False) as tmp:
                tmp.write(content)
                tmp_path = tmp.name

            agent = DataAnalystAgent()
            result = agent.analyze(tmp_path, config=config, question=payload.get("question") or None)
            self._send_json(200, {"result": result})
        except Exception as exc:  # noqa: BLE001 - API boundary: report failures instead of crashing
            self._send_json(502, {"error": f"Analysis failed: {exc}"})
        finally:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
