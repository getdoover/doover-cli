import os
from pathlib import Path

def get_app_directory(root: Path = None) -> Path:
    root_fp = root or Path()
    while not (root_fp / "doover_config.json").exists():
        if root_fp == Path("/"):
            raise FileNotFoundError("doover_config.json not found. Please run this command from the application directory.")

        res = list(root_fp.rglob("doover_config.json"))
        if len(res) > 1:
            raise ValueError("Multiple doover_config.json files found. Please navigate to the correct application directory.")
        elif len(res) == 0:
            root_fp = root_fp.parent
        else:
            root_fp = res[0].parent
            break

    return root_fp


def get_uv_path() -> Path:
    uv_path = Path.home() / ".local" / "bin"/ "uv"
    if not uv_path.exists():
        raise RuntimeError("uv not found in your PATH. Please install it and try again.")
    return uv_path

def call_with_uv(*args, uv_run: bool = True):
    uv_path = get_uv_path()
    if uv_run:
        args = ["uv", "run"] + list(args)
    os.execl(str(uv_path.absolute()), *args)
