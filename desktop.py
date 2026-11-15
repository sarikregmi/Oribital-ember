"""Run the shared HTML interface as a local standalone application."""

import argparse
import socket
import threading
import time

import httpx
import uvicorn


# The web UI and API share one local origin, so neither needs separate configuration.
HOST = "127.0.0.1"
PORT = 8000
URL = f"http://{HOST}:{PORT}"


def start_server() -> None:
    """Run the FastAPI server that serves both the frontend and JSON API."""
    uvicorn.run("app.main:app", host=HOST, port=PORT, log_level="warning")


def wait_for_server(timeout: float = 10.0) -> bool:
    """Wait for the shared HTML/API process before opening the native window."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            response = httpx.get(f"{URL}/health", timeout=0.5)
            if response.is_success:
                return True
        except httpx.HTTPError:
            pass
        time.sleep(0.1)
    return False


def find_free_port(start: int = 8000) -> int:
    """Find a local port without starting a process that can race another server."""
    candidate = start
    while candidate < start + 100:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if probe.connect_ex((HOST, candidate)) != 0:
                return candidate
        candidate += 1
    raise RuntimeError("No free local port found between 8000 and 8099")


def open_html_window() -> bool:
    """Render the exact app/static HTML interface in a native webview window."""
    try:
        import webview
    except ImportError:
        return False

    # Prefer Qt when installed because this host's GTK gi binding is incomplete.
    try:
        try:
            import PySide6  # noqa: F401
            gui_backend = "qt"
        except ImportError:
            gui_backend = None
        webview.create_window(
            "Orbital Ember",
            URL,
            width=1280,
            height=820,
            min_size=(760, 560),
        )
        webview.start(gui=gui_backend)
        return True
    except Exception as error:
        # GTK/Qt bindings are host dependencies; keep the server usable if one is broken.
        print(f"Native webview unavailable: {error}")
        return False


def run() -> None:
    """Start native HTML mode by default, or server-only mode with --web."""
    parser = argparse.ArgumentParser(description="Run the Orbital Ember HTML app")
    parser.add_argument(
        "--web",
        action="store_true",
        help="serve the shared HTML interface without opening a native window",
    )
    arguments = parser.parse_args()

    global PORT, URL

    # Reuse a healthy API; otherwise select a free port before starting Uvicorn.
    owns_server = not wait_for_server(timeout=0.5)
    server: threading.Thread | None = None
    if owns_server:
        PORT = find_free_port(PORT)
        URL = f"http://{HOST}:{PORT}"
        server = threading.Thread(target=start_server, daemon=True)
        server.start()
        if not wait_for_server():
            print(f"Orbital Ember could not start its API at {URL}. Is port {PORT} already in use?")
            return

    if arguments.web:
        print(f"Orbital Ember web interface is running at {URL}")
        if server is None:
            print("Using the existing API process on port 8000.")
            return
        try:
            server.join()
        except KeyboardInterrupt:
            print("\nOrbital Ember stopped")
        return

    if not open_html_window():
        print("The standalone HTML window needs pywebview with a working GTK or Qt backend.")
        print("Install project support with: python -m pip install -e '.[desktop]'")
        print(f"The shared web interface is available at {URL} using: python desktop.py --web")
        if server is not None:
            try:
                # Keep the shared HTML/API process alive after a native backend failure.
                server.join()
            except KeyboardInterrupt:
                print("\nOrbital Ember stopped")


if __name__ == "__main__":
    run()
