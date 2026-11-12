"""Compare allowlisted usage identities and query running aha without syncing."""

import http.cookiejar
import json
import os
import sys
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

from importlib.util import module_from_spec, spec_from_file_location

spec = spec_from_file_location("diagnose", Path(__file__).with_name("inspect-local-readonly.py"))
diagnose = module_from_spec(spec)
spec.loader.exec_module(diagnose)
sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "src"))
from aha.domain import DETAIL_FIELDS, normalize_row, record_key, row_fingerprint


def main():
    app_dir = Path(os.environ["LOCALAPPDATA"]) / "aha"
    source_path = Path.home() / ".cc-switch" / "cc-switch.db"
    result = {}
    def basis(c):
        return dict(c.execute("SELECT key,value FROM settings")), c.execute(
            "SELECT count(*) FROM usage_records").fetchone()[0]
    with diagnose.reader(app_dir / "aha.sqlite3") as a, diagnose.reader(source_path) as c:
        before = basis(a)
        current = Counter()
        by_day = Counter()
        cursor = c.execute("SELECT " + ",".join(DETAIL_FIELDS) + " FROM proxy_request_logs "
                           "WHERE app_type='codex' AND data_source='codex_session'")
        for raw in cursor:
            row = normalize_row(dict(raw), "detail")
            existing = a.execute("SELECT content_hash FROM usage_records WHERE record_key=?",
                                 (record_key(row),)).fetchone()
            status = "new" if existing is None else "identical" if existing[0] == row_fingerprint(row) else "changed"
            current[status] += 1
            by_day[(row["created_at"] // 86400, status)] += 1
        cursor.close()
        result["comparison"] = dict(current)
    descriptor = json.loads((app_dir / "runtime.json").read_text(encoding="utf-8"))
    private_address = descriptor["bootstrap_url"]
    parsed = urllib.parse.urlsplit(private_address)
    assert parsed.hostname == "127.0.0.1" and parsed.scheme == "http"
    origin = f"http://127.0.0.1:{parsed.port}"
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    with opener.open(private_address, timeout=10) as response:
        response.read()
    with opener.open(origin + "/api/status", timeout=10) as response:
        status = json.load(response)
    result["running_version"] = status["version"]
    result["http_ledger"] = {k: status["ledger"].get(k) for k in ("counts", "coverage", "last_successful_sync_at")}
    result["http_queries"] = []
    for start, end in (("2026-06-17", "2026-11-12"), ("2026-11-12", "2026-11-12")):
        body = json.dumps({"start_date": start, "end_date": end, "project_id": "all",
                           "availability_mode": "available"}).encode()
        request = urllib.request.Request(origin + "/api/analysis", data=body, headers={
            "Content-Type": "application/json", "Origin": origin, "X-AHA-CSRF": status["csrf_token"]})
        with opener.open(request, timeout=20) as response:
            analysis = json.load(response)
        result["http_queries"].append({"start": start, "end": end,
                                       "summary": {k: analysis["summary"].get(k) for k in (
                                           "record_count", "detail_count", "rollup_record_count")},
                                       "summary_complete": analysis.get("summary_complete")})
    with diagnose.reader(app_dir / "aha.sqlite3") as a:
        result["aha_revisions_and_count_unchanged"] = before == basis(a)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
