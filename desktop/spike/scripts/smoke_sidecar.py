"""Start the sidecar in temporary folders, call the routes that read its bundled data (and
probe the ``multitrack`` fixture), print the answers as JSON, then stop it as the shell does."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

from desktop.spike.scripts import sidecar


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--unfrozen", action="store_true", help="run `uv run reframe-server`")
    args = parser.parse_args(argv)
    command = sidecar.unfrozen_command() if args.unfrozen else sidecar.frozen_command()
    with tempfile.TemporaryDirectory(prefix="reframe-spike-") as tmp:
        car = sidecar.start(command, Path(tmp))
        try:
            answers = sidecar.smoke(car)
            answers["ready after (s)"] = round(car.ready_after, 3)
            print(json.dumps(answers, indent=2))
            car.client.post("/api/system/shutdown")
            code = car.process.wait(10)
            if any(str(answer).startswith("ERROR") for answer in answers.values()):
                errors = [
                    line
                    for line in car.log.read_text(errors="replace").splitlines()
                    if not line.startswith(("INFO:", "  File ", "    "))
                ]
                sys.stderr.write("\n".join(errors) + "\n")
        except BaseException:
            car.process.kill()
            car.process.wait()
            sys.stderr.write(car.log.read_text(errors="replace")[-6000:])
            raise
        finally:
            car.close()
        print(f"exit code {code}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
