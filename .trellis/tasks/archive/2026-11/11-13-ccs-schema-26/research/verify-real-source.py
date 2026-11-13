"""Read genuine CCS26 into an isolated disposable EXE ledger; report no usage values."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path
from uuid import uuid4


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--exe",required=True,type=Path)
    parser.add_argument("--source",required=True,type=Path)
    args=parser.parse_args()
    root=Path(os.environ["AHA_CCS26_ROOT"])
    source=Path(__file__).resolve().parents[4]
    research=Path(__file__).resolve().parent
    assert json.loads((root/"task-ownership.json").read_text())["task"]=="ccs-schema-26"
    assert args.source.is_file()
    with closing(sqlite3.connect(args.source.resolve().as_uri()+"?mode=ro",uri=True)) as conn:
        conn.execute("PRAGMA query_only=ON")
        version=conn.execute("PRAGMA user_version").fetchone()[0]
        assert version==26
    sys.path.insert(0,str(source/"scripts"))
    import verify_windows_artifact as artifact
    case=root/("real-source-projection-"+uuid4().hex[:8])
    env,profile=artifact.isolated_environment(case)
    descriptor=case/"store/runtime.json"
    executable=args.exe.resolve(strict=True)
    process=subprocess.Popen([str(executable),"--data-dir",str(descriptor.parent),"--no-browser"],
        cwd=profile,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    client=None
    try:
        launch=artifact.wait_descriptor(descriptor,process)
        client=artifact.Client(launch)
        job=client.sync({"path":str(args.source.resolve())})
        assert job["status"] in {"completed","needs_review"},job.get("code")
        assert job["result"]["source_schema_version"]==26
        before=client.json("GET","/api/ledger")
        failed=client.sync({"path":str(case/"missing-source.sqlite")})
        assert failed["status"]=="failed",failed.get("code",failed["status"])
        assert failed.get("code")=="source_binding_required",failed.get("code")
        after=client.json("GET","/api/ledger")
        assert after["counts"]==before["counts"]
        assert after["last_successful_sync_at"]==before["last_successful_sync_at"]
        artifact.check_shutdown(client,process,descriptor)
        report={"verified":True,"observed_source_version":version,"result_source_version":26,
            "sync_outcome":job["status"],"genuine_ccs_read_only":True,"isolated_disposable_aha":True,
            "genuine_aha_accessed":False,"usage_values_recorded":False,
            "unconfirmed_source_switch_rejected":True,
            "history_retained_after_failed_sync":True,"executable_sha256":artifact.digest(executable),
            "shutdown_descriptor_cleaned":not descriptor.exists()}
        (research/"real-source-verification.json").write_text(json.dumps(report,indent=2)+"\n")
        print(json.dumps(report),flush=True)
    finally:
        artifact.stop_process(process,client)


if __name__=="__main__":
    main()
