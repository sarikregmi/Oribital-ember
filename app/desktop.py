"""Standalone desktop shell for Orbital Ember.

Run with ``python -m app.desktop`` after installing the ``desktop`` extra.
The window owns a local API server, so users do not need a browser or a second
terminal process to use the application.
"""

import json
import sys
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import uvicorn
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .main import app as api_app


# The loopback port is private to this desktop process and is easy to change.
API_URL = "http://127.0.0.1:8765"


class LocalApiServer:
    """Run FastAPI in a daemon thread while the Qt window is open."""

    def __init__(self) -> None:
        # A uvicorn Server lets the window request a clean shutdown later.
        self.server = uvicorn.Server(uvicorn.Config(api_app, host="127.0.0.1", port=8765, log_level="warning"))
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def start(self) -> None:
        # Starting in the background keeps the GUI event loop responsive.
        self.thread.start()
        for _ in range(40):
            try:
                request_json("/health")
                return
            except (HTTPError, URLError, ConnectionError):
                time.sleep(0.05)
        raise RuntimeError("The local API did not start on port 8765")

    def stop(self) -> None:
        # uvicorn checks this flag between requests and exits without killing data.
        self.server.should_exit = True
        self.thread.join(timeout=2)


def request_json(path: str, method: str = "GET") -> dict:
    """Call the local API and decode one JSON response for the desktop shell."""
    request = Request(f"{API_URL}{path}", method=method, headers={"Accept": "application/json"})
    with urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


class MainWindow(QMainWindow):
    """The first usable desktop view: search, inspect, and explain."""

    def __init__(self, api_server: LocalApiServer) -> None:
        super().__init__()
        self.api_server = api_server
        self.records: list[dict] = []
        self.setWindowTitle("Orbital Ember | NASA Fire Safety")
        self.resize(1100, 720)
        self._build_ui()
        self._search()

    def _build_ui(self) -> None:
        # The header gives the user one obvious starting action.
        central = QWidget()
        root = QVBoxLayout(central)
        heading = QLabel("Orbital Ember")
        heading.setFont(QFont("Sans Serif", 22, QFont.Weight.Bold))
        subtitle = QLabel("NASA microgravity combustion research for safer habitats")
        subtitle.setStyleSheet("color: #637083; margin-bottom: 10px;")
        root.addWidget(heading)
        root.addWidget(subtitle)

        # Search controls are deliberately plain so a frontend developer can replace them later.
        controls = QHBoxLayout()
        self.query = QTextEdit()
        self.query.setPlaceholderText("Search: suppression, smoke, oxygen, habitat...")
        self.query.setFixedHeight(42)
        self.query.setAcceptRichText(False)
        self.domain = QComboBox()
        self.domain.addItems(["All domains", "flammability", "detection", "suppression", "fundamental"])
        self.search_button = QPushButton("Search")
        self.search_button.clicked.connect(self._search)
        controls.addWidget(self.query, 1)
        controls.addWidget(self.domain)
        controls.addWidget(self.search_button)
        root.addLayout(controls)

        # The split view supports quick scanning on the left and detail review on the right.
        content = QHBoxLayout()
        self.results = QListWidget()
        self.results.currentItemChanged.connect(self._show_selected)
        self.details = QTextEdit()
        self.details.setReadOnly(True)
        content.addWidget(self.results, 1)
        content.addWidget(self.details, 2)
        root.addLayout(content, 1)

        # Explanation is an explicit action so local AI never runs unexpectedly.
        self.explain_button = QPushButton("Explain fire-safety relevance")
        self.explain_button.clicked.connect(self._explain_selected)
        root.addWidget(self.explain_button)
        self.setCentralWidget(central)

    def _search(self) -> None:
        # Query parameters are encoded manually because this client only sends simple terms.
        query = self.query.toPlainText().strip().replace(" ", "%20")
        domain = self.domain.currentText()
        path = f"/api/v1/investigations?q={query}"
        if domain != "All domains":
            path += f"&domain={domain}"
        try:
            payload = request_json(path)
        except (HTTPError, URLError, TimeoutError) as error:
            self._show_error(f"Search failed: {error}")
            return
        self.records = payload["results"]
        self.results.clear()
        for record in self.records:
            item = QListWidgetItem(f"{record['id']}  |  {record['name']}")
            item.setData(Qt.ItemDataRole.UserRole, record["id"])
            self.results.addItem(item)
        if self.records:
            self.results.setCurrentRow(0)
        else:
            self.details.setPlainText("No investigations matched this search.")

    def _show_selected(self, item: QListWidgetItem | None, _previous: QListWidgetItem | None) -> None:
        # Detail text is built from API fields rather than duplicated catalog data.
        if item is None:
            return
        record = next(record for record in self.records if record["id"] == item.data(Qt.ItemDataRole.UserRole))
        self.details.setPlainText(
            f"{record['name']}\n\n"
            f"{record['description']}\n\n"
            f"Domain: {record['domain']}\n"
            f"Gravity: {', '.join(record['gravity'])}\n"
            f"Fuels: {', '.join(record['fuels'])}\n"
            f"Conditions: {', '.join(record['conditions'])}\n"
            f"Measurements: {', '.join(record['measurements'])}\n\n"
            f"Source: {record['source_url']}"
        )

    def _explain_selected(self) -> None:
        # The explanation endpoint decides whether local Ollama or the safe fallback is used.
        item = self.results.currentItem()
        if item is None:
            return
        investigation_id = item.data(Qt.ItemDataRole.UserRole)
        try:
            explanation = request_json(f"/api/v1/investigations/{investigation_id}/explain", method="POST")
        except (HTTPError, URLError, TimeoutError) as error:
            self._show_error(f"Explanation failed: {error}")
            return
        self.details.setPlainText(
            f"{explanation['summary']}\n\n"
            f"Fire-safety relevance:\n- "
            f"\n- ".join(explanation["fire_safety_implications"])
            + "\n\nEvidence:\n- "
            + "\n- ".join(explanation["evidence"])
            + f"\n\nAI mode: {explanation['ai_mode']}\n\nLimitations:\n- "
            + "\n- ".join(explanation["limitations"])
        )

    def _show_error(self, message: str) -> None:
        # Centralizing errors gives the desktop shell one consistent failure experience.
        QMessageBox.warning(self, "Orbital Ember", message)

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt requires this method name.
        # Stop the embedded API before the process exits.
        self.api_server.stop()
        event.accept()


def main() -> int:
    # QApplication owns the native event loop and desktop resources.
    application = QApplication(sys.argv)
    api_server = LocalApiServer()
    api_server.start()
    window = MainWindow(api_server)
    window.show()
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
