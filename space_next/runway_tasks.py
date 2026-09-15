"""Bounded Runway task operations. Auth is supplied only by the runtime proxy."""
import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

BASE = "https://api.dev.runwayml.com/v1"


def api_call(url, payload=None):
    command = ["curl", "--fail-with-body", "-sS", "--max-time", "90",
               url, "-H", "X-Runway-Version: 2024-11-06"]
    if payload is not None:
        command += ["-H", "Content-Type: application/json", "--data-binary", json.dumps(payload)]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(f"curl exited {result.returncode}: {result.stderr}; {result.stdout}")
    return json.loads(result.stdout)


def save(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=["create", "status", "download"])
    parser.add_argument("scene_dir", type=Path)
    args = parser.parse_args()
    folder = args.scene_dir.resolve()
    folder.mkdir(parents=True, exist_ok=True)
    if args.operation == "create":
        request = json.loads((folder / "request.json").read_text())
        assert request["model"] == "seedance2_5"
        assert request["ratio"] == "1080:1920"
        assert request.get("audio") is False
        assert 4 <= request["duration"] <= 15
        assert len(request["promptText"].encode("utf-16-le")) // 2 <= 15000
        marker = folder / "creation-attempt.json"
        if marker.exists():
            raise SystemExit("Creation already attempted; reconcile before any new request.")
        save(marker, {"at": datetime.now(timezone.utc).isoformat(), "request": request})
        response = api_call(BASE + "/text_to_video", request)
        save(folder / "creation-response.json", {"body": response})
        print(json.dumps({"id": response["id"]}))
    elif args.operation == "status":
        creation_path = folder / "creation-response.json"
        if creation_path.exists():
            task_id = json.loads(creation_path.read_text())["body"]["id"]
        else:
            task_id = json.loads((folder / "creation-curl-response.json").read_text())["id"]
        data = api_call(BASE + "/tasks/" + task_id)
        save(folder / "task-status.json", data)
        print(json.dumps(data))
    else:
        # Run without custom credentials. Output CDN is not the API host.
        status = json.loads((folder / "task-status.json").read_text())
        assert status["status"] == "SUCCEEDED"
        output = folder / "clip.mp4"
        if output.exists():
            raise SystemExit("Clip already exists; refusing a duplicate download.")
        subprocess.run(["curl", "--fail-with-body", "-sS", "--max-time", "120",
                        status["output"][0], "--output", str(output)], check=True)
        receipt = {
            "task_id": status["id"],
            "file": output.name,
            "bytes": output.stat().st_size,
            "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
            "downloaded_at": datetime.now(timezone.utc).isoformat(),
            "source_url": status["output"][0],
        }
        save(folder / "download-receipt.json", receipt)
        print(json.dumps({k: v for k, v in receipt.items() if k != "source_url"}))


if __name__ == "__main__":
    main()
