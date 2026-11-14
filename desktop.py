"""Run the shared HTML interface as a local standalone application."""

import argparse
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


def open_html_window() -> bool:
    """Render the exact app/static HTML interface in a native webview window."""
    try:
        import webview
    except ImportError:
        return False

    # pywebview embeds the same URL a developer can open in a normal browser.
    try:
        webview.create_window(
            "Orbital Ember",
            URL,
            width=1280,
            height=820,
            min_size=(760, 560),
        )
        webview.start()
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

    server = threading.Thread(target=start_server, daemon=True)
    server.start()
    if not wait_for_server():
        print(f"Orbital Ember could not start its API at {URL}. Is port {PORT} already in use?")
        return

    if arguments.web:
        print(f"Orbital Ember web interface is running at {URL}")
        try:
            server.join()
        except KeyboardInterrupt:
            print("\nOrbital Ember stopped")
        return

    if not open_html_window():
        print("The standalone HTML window needs pywebview.")
        print("Install it with: python -m pip install -e '.[desktop]'")
        print(f"The shared web interface is available at {URL} using: python desktop.py --web")


if __name__ == "__main__":
    run()

"""Start Orbital Ember as a native local Python application."""

import argparse
import shutil
import subprocess
import threading
import time
from urllib.parse import quote_plus

import httpx
import uvicorn


# Keep the local port predictable so the frontend can use a relative API URL.
HOST = "127.0.0.1"
PORT = 8000
URL = f"http://{HOST}:{PORT}"


def start_server() -> None:
    """Run FastAPI in the current thread until the application closes."""
    uvicorn.run("app.main:app", host=HOST, port=PORT, log_level="warning")


def wait_for_server(timeout: float = 10.0) -> bool:
    """Wait until Uvicorn accepts requests before opening any native dialog."""
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


def open_tk_window() -> None:
    """Use a standard-library native popup when PySide6 is unavailable."""
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    time.sleep(1)
    root = tk.Tk()
    root.title("Orbital Ember")
    root.geometry("980x680")

    # These variables make the small native window easy to extend later.
    search_text = tk.StringVar(value="")
    question_text = tk.StringVar(value="What does this investigation mean for spacecraft fire safety?")
    nasa_enabled = tk.BooleanVar(value=False)
    web_enabled = tk.BooleanVar(value=False)
    selected_id = tk.StringVar(value="")
    investigations: list[dict] = []

    # The left side is a compact catalog browser; the right side is the inspector.
    root.columnconfigure(0, weight=1)
    root.columnconfigure(1, weight=2)
    root.rowconfigure(1, weight=1)
    ttk.Label(root, text="Orbital Ember - NASA fire safety").grid(row=0, column=0, columnspan=2, sticky="w", padx=16, pady=12)
    controls = ttk.Frame(root)
    controls.grid(row=0, column=1, sticky="e", padx=16, pady=8)
    ttk.Entry(controls, textvariable=search_text, width=28).grid(row=0, column=0, padx=4)
    ttk.Checkbutton(controls, text="NASA", variable=nasa_enabled).grid(row=0, column=1)
    ttk.Checkbutton(controls, text="Web", variable=web_enabled).grid(row=0, column=2)
    ttk.Label(root, text="Ask AI").grid(row=2, column=0, sticky="w", padx=16, pady=(0, 4))
    ttk.Entry(root, textvariable=question_text, width=70).grid(row=2, column=1, sticky="ew", padx=16, pady=(0, 4))

    result_list = tk.Listbox(root, exportselection=False)
    result_list.grid(row=1, column=0, sticky="nsew", padx=(16, 8), pady=(0, 16))
    detail = tk.Text(root, wrap="word", height=20)
    detail.grid(row=1, column=1, sticky="nsew", padx=(8, 16), pady=(0, 16))

    def api_get(path: str) -> dict:
        response = httpx.get(f"{URL}{path}", timeout=10)
        response.raise_for_status()
        return response.json()

    def load_results(*_: object) -> None:
        """Refresh the list from the local API, never from the web directly."""
        nonlocal investigations
        query = search_text.get().strip()
        data = api_get(f"/api/v1/investigations?q={quote_plus(query)}")
        investigations = data["results"]
        result_list.delete(0, tk.END)
        for item in investigations:
            result_list.insert(tk.END, f"{item['id']}  {item['name']}")

    def selected() -> dict | None:
        """Return the record highlighted in the list."""
        selection = result_list.curselection()
        return investigations[selection[0]] if selection else None

    def explain(file_path: str | None = None) -> None:
        """Request a detailed explanation with optional NASA/web context or file text."""
        item = selected()
        if not item:
            return
        options = {
            "question": question_text.get().strip(),
            "include_nasa_search": nasa_enabled.get(),
            "include_web_search": web_enabled.get(),
        }
        if file_path:
            with open(file_path, "rb") as source_file:
                response = httpx.post(
                    f"{URL}/api/v1/investigations/{item['id']}/explain-file",
                    params=options,
                    files={"file": source_file},
                    timeout=30,
                )
        else:
            response = httpx.post(f"{URL}/api/v1/investigations/{item['id']}/explain", json=options, timeout=30)
        response.raise_for_status()
        data = response.json()
        detail.delete("1.0", tk.END)
        detail.insert(tk.END, f"{data['summary']}\n\n")
        detail.insert(tk.END, "Analysis\n" + "\n".join(f"- {line}" for line in data["detailed_analysis"]) + "\n\n")
        detail.insert(tk.END, "Recommendations\n" + "\n".join(f"- {line}" for line in data["recommendations"]) + "\n\n")
        detail.insert(tk.END, f"AI mode: {data['ai_mode']}\nSources: {len(data['sources'])}")

    def show_selected(_: object = None) -> None:
        """Show metadata immediately, before the slower AI explanation is requested."""
        item = selected()
        if item:
            selected_id.set(item["id"])
            detail.delete("1.0", tk.END)
            detail.insert(tk.END, f"{item['name']}\n\n{item['description']}\n\nConditions: {', '.join(item['conditions'])}")

    def read_file() -> None:
        """Let the user choose a local text file for investigation-aware analysis."""
        path = filedialog.askopenfilename(filetypes=[("Text data", "*.txt *.md *.csv *.json"), ("All files", "*")])
        if path:
            explain(path)

    result_list.bind("<<ListboxSelect>>", show_selected)
    search_text.trace_add("write", load_results)
    buttons = ttk.Frame(root)
    buttons.grid(row=3, column=1, sticky="e", padx=16, pady=(0, 14))
    ttk.Button(buttons, text="Explain", command=explain).pack(side="left", padx=4)
    ttk.Button(buttons, text="Read file", command=read_file).pack(side="left", padx=4)
    try:
        load_results()
    except Exception as error:
        messagebox.showerror("Orbital Ember", f"The local API did not start: {error}")
    root.mainloop()


def open_webview_window() -> bool:
    """Open the bundled HTML UI inside a native pywebview window when available."""
    try:
        import webview
    except ImportError:
        return False
    webview.create_window("Orbital Ember", URL, width=1280, height=820, min_size=(760, 560))
    webview.start()
    return True


def format_explanation(data: dict) -> str:
    """Turn the structured AI response into readable native dialog text."""
    analysis = "\n".join(f"- {line}" for line in data["detailed_analysis"])
    recommendations = "\n".join(f"- {line}" for line in data["recommendations"])
    sources = "\n".join(f"- {source['title']} ({source['source_type']})" for source in data["sources"])
    return (
        f"{data['summary']}\n\nAnalysis\n{analysis}\n\n"
        f"Recommendations\n{recommendations}\n\n"
        f"AI mode: {data['ai_mode']}\nSources\n{sources}"
    )


def open_zenity_window() -> None:
    """Use installed Linux dialogs when Python GUI modules are unavailable."""
    # Zenity is a native GTK dialog, not a browser, and is common on Linux desktops.
    if not shutil.which("zenity"):
        print("No native GUI toolkit found. Install PySide6 or python3-tk, then retry.")
        return

    while True:
        try:
            response = httpx.get(f"{URL}/api/v1/investigations", timeout=10)
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPError as error:
            subprocess.run(["zenity", "--error", "--title=Orbital Ember", "--text=" + f"Local API unavailable: {error}"], check=False)
            return
        command = [
            "zenity", "--list", "--title=Orbital Ember", "--text=Select a NASA investigation",
            "--column=ID", "--column=Investigation", "--width=900", "--height=500",
        ]
        for item in data["results"]:
            command.extend([item["id"], item["name"]])
        selected = subprocess.run(command, text=True, capture_output=True).stdout.strip()
        if not selected:
            return

        # Ask separately so the user can keep bandwidth-saving defaults independently.
        nasa = subprocess.run(["zenity", "--question", "--text=Search NASA for supporting sources?"], check=False).returncode == 0
        web = subprocess.run(["zenity", "--question", "--text=Search the web for supporting sources?"], check=False).returncode == 0
        question_result = subprocess.run(
            ["zenity", "--entry", "--title=Ask the local AI", "--text=What should the AI explain?",
             "--entry-text=What does this investigation mean for spacecraft fire safety?"],
            text=True,
            capture_output=True,
        )
        question = question_result.stdout.strip()
        if not question:
            question = "Explain this investigation for spacecraft fire safety."
        read_file = subprocess.run(
            ["zenity", "--question", "--text=Add a local file to this explanation?"],
            check=False,
        ).returncode == 0
        file_path = ""
        if read_file:
            file_result = subprocess.run(
                ["zenity", "--file-selection", "--title=Choose a local file"],
                text=True,
                capture_output=True,
            )
            file_path = file_result.stdout.strip() if file_result.returncode == 0 else ""
        options = {"question": question, "include_nasa_search": nasa, "include_web_search": web}
        if file_path:
            with open(file_path, "rb") as source_file:
                response = httpx.post(f"{URL}/api/v1/investigations/{selected}/explain-file", params=options, files={"file": source_file}, timeout=30)
        else:
            response = httpx.post(f"{URL}/api/v1/investigations/{selected}/explain", json=options, timeout=30)
        response.raise_for_status()
        subprocess.run(["zenity", "--info", "--title=Orbital Ember explanation", "--text=" + format_explanation(response.json()), "--width=900", "--height=600"], check=False)


def run() -> None:
    """Run the HTML UI natively, or expose it as a local web app when requested."""
    parser = argparse.ArgumentParser(description="Run the Orbital Ember local app")
    parser.add_argument(
        "--web",
        action="store_true",
        help="run the local web interface without opening a desktop window",
    )
    arguments = parser.parse_args()

    server = threading.Thread(target=start_server, daemon=True)
    server.start()
    if not wait_for_server():
        print(f"Orbital Ember could not start its local API at {URL}. Is port {PORT} already in use?")
        return

    if arguments.web:
        print(f"Orbital Ember web interface is running at {URL}")
        try:
            server.join()
        except KeyboardInterrupt:
            print("\nOrbital Ember stopped")
        return

    # Prefer the same HTML/CSS/JS interface in a native webview.
    if open_webview_window():
        return

    try:
        from PySide6.QtCore import QUrl
        from PySide6.QtWidgets import QApplication
        from PySide6.QtWebEngineWidgets import QWebEngineView
    except ImportError:
        try:
            open_tk_window()
            return
        except ImportError:
            open_zenity_window()
            return

    # PySide6 is optional because the core app should stay light to install.
    app = QApplication([])
    window = QWebEngineView()
    window.setWindowTitle("Orbital Ember")
    window.resize(1280, 820)
    window.load(QUrl(URL))
    window.show()
    app.exec()


if __name__ == "__main__":
    run()
