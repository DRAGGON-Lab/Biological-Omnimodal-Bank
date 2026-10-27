import os

import uvicorn

from bob.main import create_app


def main() -> None:
    uvicorn.run(create_app(), host=os.environ.get("BOB_HOST", "127.0.0.1"), port=int(os.environ.get("BOB_PORT", "8000")))


if __name__ == "__main__":
    main()
