from __future__ import annotations

import os

import uvicorn


def main() -> int:
	host = os.getenv("API_HOST", "127.0.0.1").strip() or "127.0.0.1"
	port_raw = os.getenv("API_PORT", "8000").strip()
	try:
		port = int(port_raw)
	except ValueError:
		port = 8000

	uvicorn.run("glass_box_chat.main:app", host=host, port=port, reload=False)
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
