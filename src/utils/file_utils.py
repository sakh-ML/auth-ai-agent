import os


def read_file(path: str) -> str | None:

    if not isinstance(path, str):
        return None

    if not os.path.exists(path):
        print("Error: not a valid path")
        return None

    if os.path.isfile(path):
        with open(path) as file:
            return file.read()
    else:
        return None
