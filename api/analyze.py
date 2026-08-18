import base64
import binascii
import json
import os
import re
import sys
import tempfile
from http.server import BaseHTTPRequestHandler
from io import BytesIO

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datamind.agent import DataAnalystAgent  # noqa: E402
from datamind.config import UserConfig  # noqa: E402
from datamind.dashboard import build_workbook, compute_kpi_summary, load_dataframe  # noqa: E402

_TEXT_SUFFIXES = {".csv", ".tsv", ".json"}
_BINARY_SUFFIXES = {".xlsx", ".xls", ".xlsm"}
_KNOWN_SUFFIXES = _TEXT_SUFFIXES | _BINARY_SUFFIXES


def _suffix_for(filename: str) -> str:
    ext = os.path.splitext(filename or "")[1].lower()
    return ext if ext in _KNOWN_SUFFIXES else ".csv"


def _output_basename(filename: str | None) -> str:
    stem = os.path.splitext(filename or "dataset")[0]
    stem = re.sub(r"[^A-Za-z0-9_-]+", "_", stem).strip("_") or "dataset"
    return f"{stem}_dashboard.xlsx"


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
            self._send_json(400, {"error": "Missing 'content' (dataset content)"})
            return

        encoding = payload.get("encoding") or "utf-8"
        if encoding not in ("utf-8", "base64"):
            self._send_json(400, {"error": f"Unsupported encoding '{encoding}'"})
            return

        if encoding == "base64":
            try:
                file_bytes = base64.b64decode(content, validate=True)
            except (binascii.Error, ValueError):
                self._send_json(400, {"error": "Invalid base64 in 'content'"})
                return
        else:
            file_bytes = None

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

        suffix = _suffix_for(payload.get("filename"))
        tmp_path = None
        try:
            if file_bytes is not None:
                with tempfile.NamedTemporaryFile(mode="wb", suffix=suffix, delete=False) as tmp:
                    tmp.write(file_bytes)
                    tmp_path = tmp.name
            else:
                with tempfile.NamedTemporaryFile(mode="w", suffix=suffix, delete=False) as tmp:
                    tmp.write(content)
                    tmp_path = tmp.name

            agent = DataAnalystAgent()
            plan = agent.plan_dashboard(tmp_path, config=config, question=payload.get("question") or None)

            df = load_dataframe(tmp_path)
            workbook = build_workbook(df, plan)
            buffer = BytesIO()
            workbook.save(buffer)
            workbook_base64 = base64.b64encode(buffer.getvalue()).decode("ascii")

            summary = {
                "dataset_classification": plan.get("dataset_classification", ""),
                "executive_summary": plan.get("executive_summary", ""),
                "kpis": compute_kpi_summary(df, plan),
                "insights_text": plan.get("insights_text", []),
                "risks": plan.get("risks", []),
                "opportunities": plan.get("opportunities", []),
                "recommendations": plan.get("recommendations", []),
            }

            self._send_json(
                200,
                {
                    "summary": summary,
                    "workbook_base64": workbook_base64,
                    "workbook_filename": _output_basename(payload.get("filename")),
                },
            )
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
