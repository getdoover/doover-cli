import base64
import json
import pickle

from contextlib import suppress
from pathlib import Path
from typing import Annotated, Any

import typer

app = typer.Typer(no_args_is_help=True)


def row_to_dict(row: str) -> dict[str, Any]:
    payload = json.loads(pickle.loads(base64.b64decode(row)))["API_CHANNEL_PUBLISH"][0]
    return {
        "channel_name": payload["CHANNEL_NAME"],
        "payload": payload["MESSAGE"],
        "record_log": payload.get("RECORD_LOG", False),
        "override_aggregate": payload.get("OVERRIDE_AGGREGATE", False),
        "timestamp": payload["TIMESTAMP"],
    }


@app.command()
def dbm_to_json(
    dbm_file: Annotated[
        Path,
        typer.Argument(help="Path to the DBM backup / export file to convert to JSON."),
    ],
    json_file: Annotated[Path, typer.Argument(help="Path to the output JSON file.")],
):
    """Convert a DBM file to a JSON file."""
    import dbm

    try:
        with dbm.open(dbm_file, "r") as db:
            rows = [row_to_dict(r.decode()) for r in db.values()]

    except dbm.error as e:
        print(
            f"Error reading DBM file {dbm_file}: {e}.\n\n"
            f"Try first dumping the DBM file using `gdbm_dump dda_queue.dbm my_dump.dump` "
            f"and then use `doover dda-logs dbm-backup-to-json`."
        )
        raise typer.Exit(1)

    import json

    json_file.write_text(json.dumps(rows, indent=4))
    print(f"Converted {dbm_file} to {json_file}.")


@app.command()
def dbm_backup_to_json(
    dbm_file: Annotated[
        Path,
        typer.Argument(help="Path to the DBM backup / export file to convert to JSON."),
    ],
    json_file: Annotated[Path, typer.Argument(help="Path to the output JSON file.")],
):
    """Convert a DBM file to a JSON file."""
    data = dbm_file.read_text()

    rows = []
    msg = ""
    for line in data.splitlines():
        if line.startswith("#"):
            if msg:
                with suppress(
                    pickle.UnpicklingError, json.JSONDecodeError, TypeError, KeyError
                ):
                    rows.append(row_to_dict(msg))

            msg = ""
            continue

        msg += line

    json_file.write_text(json.dumps(rows, indent=4))
    print(f"Converted {dbm_file} to {json_file}.")
