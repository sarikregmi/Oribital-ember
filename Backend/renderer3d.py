"""Small dependency-free 3D spacecraft projection for the Pygame viewer."""
from __future__ import annotations

import math
from typing import Any


class SpacecraftRenderer:
    def __init__(self) -> None:
        self.yaw = -0.45
        self.pitch = 0.25

    def rotate(self, yaw_delta: float, pitch_delta: float) -> None:
        self.yaw += yaw_delta
        self.pitch = max(-1.2, min(1.2, self.pitch + pitch_delta))

    def _vertices(self, vehicle: dict[str, Any]) -> list[tuple[float, float, float]]:
        geometry = vehicle.get("geometry", {})
        length = float(geometry.get("length_m", 3.0) or 3.0)
        radius = float(geometry.get("diameter_m", 1.5) or 1.5) / 2.0
        segments = 16
        vertices = []
        for x in (-length / 2.0, length / 2.0):
            for index in range(segments):
                angle = 2.0 * math.pi * index / segments
                vertices.append((x, radius * math.cos(angle), radius * math.sin(angle)))
        nose_index = len(vertices)
        vertices.append((length / 2.0 + radius * 0.8, 0.0, 0.0))
        return vertices

    def _project(self, point: tuple[float, float, float], center: tuple[int, int], scale: float) -> tuple[int, int, float]:
        x, y, z = point
        cy, sy = math.cos(self.yaw), math.sin(self.yaw)
        cp, sp = math.cos(self.pitch), math.sin(self.pitch)
        x, z = x * cy - z * sy, x * sy + z * cy
        y, z = y * cp - z * sp, y * sp + z * cp
        depth = z + 6.0
        perspective = scale / max(depth, 0.5)
        return int(center[0] + x * perspective), int(center[1] - y * perspective), depth

    def draw(self, surface: Any, vehicle: dict[str, Any], result: dict[str, Any], pygame: Any, bounds: tuple[int, int, int, int]) -> None:
        left, top, width, height = bounds
        pygame.draw.rect(surface, (10, 17, 25), bounds)
        center = (left + width // 2, top + height // 2)
        vertices = self._vertices(vehicle)
        projected = [self._project(point, center, min(width, height) * 0.75) for point in vertices]
        segments = 16
        edges = []
        for ring in (0, 1):
            offset = ring * segments
            edges.extend((offset + index, offset + (index + 1) % segments) for index in range(segments))
        edges.extend((index, segments + index) for index in range(segments))
        nose = len(vertices) - 1
        edges.extend((segments + index, nose) for index in range(segments))
        for start, end in edges:
            pygame.draw.line(surface, (130, 171, 187), projected[start][:2], projected[end][:2], 1)
        markers = result.get("findings", [])
        for index, finding in enumerate(markers[:6]):
            angle = index * 1.7
            marker = (0.0, 0.55 * math.cos(angle), 0.55 * math.sin(angle))
            point = self._project(marker, center, min(width, height) * 0.75)
            color = (244, 157, 67) if finding.get("severity") != "information gap" else (118, 190, 201)
            pygame.draw.circle(surface, color, point[:2], 6)
        pygame.draw.rect(surface, (56, 75, 91), bounds, 1)
