import json
import subprocess
import sys
from pathlib import Path

import recorder


ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT / "recorder_worker.py"


def test_worker_without_output_path_reports_protocol_error():
    result = subprocess.run(
        [sys.executable, str(WORKER)],
        capture_output=True,
        text=True,
        timeout=5,
    )

    assert result.returncode != 0
    event = json.loads(result.stdout)
    assert event[recorder.EVENT_KEY] == recorder.EVENT_ERROR
    assert event["message"] == "missing output path"
