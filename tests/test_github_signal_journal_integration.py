import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import finam_executor as executor


def main():
    required = ("GITHUB_TOKEN", "GITHUB_REPOSITORY", "FINAM_STATE_BRANCH")
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        raise RuntimeError("Missing GitHub Actions context: " + ", ".join(missing))

    # Exercise only GitHub Contents API persistence. No Finam credentials,
    # authentication, positions, orders, or Telegram calls are used.
    executor.DRY_RUN = False
    signal_id = "journal-integration-validation-20261117"
    state = executor.load_signal_state()

    if signal_id in state:
        raise RuntimeError(
            "Validation signal already exists; refusing to overwrite prior evidence."
        )

    try:
        executor.reserve_signal(state, signal_id, "VALIDATION_ONLY", "LONG")
    except Exception:
        import requests
        import base64
        url = (
            f"https://api.github.com/repos/{os.environ['GITHUB_REPOSITORY']}"
            f"/contents/{executor.SIGNAL_STATE_FILE}"
        )
        headers = {
            "Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28"
        }
        probe = requests.get(
            url, headers=headers,
            params={"ref": os.environ["FINAM_STATE_BRANCH"]}, timeout=20
        )
        print("Journal GET diagnostic:", probe.status_code, probe.text[:300])
        encoded = base64.b64encode(b'{"diagnostic": true}').decode("ascii")
        put_probe = requests.put(
            url, headers=headers,
            json={
                "message": "test: diagnose signal journal write permission",
                "content": encoded,
                "branch": os.environ["GITHUB_REF_NAME"]
            },
            timeout=20
        )
        print("Journal PUT diagnostic:", put_probe.status_code, put_probe.text[:300])
        raise
    reread = executor.load_signal_state()
    assert reread[signal_id]["status"] == "SUBMISSION_ATTEMPTED"

    executor.update_signal_state(
        reread, signal_id, "VALIDATION_COMPLETE",
        validation="github_contents_api_read_write"
    )
    final_state = executor.load_signal_state()
    assert final_state[signal_id]["status"] == "VALIDATION_COMPLETE"
    assert final_state[signal_id]["validation"] == "github_contents_api_read_write"

    print("GitHub Contents API journal read/write validation: PASS")
    print("No broker API was called; no order was submitted.")


if __name__ == "__main__":
    main()
