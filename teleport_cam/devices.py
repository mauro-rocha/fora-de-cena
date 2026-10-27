from __future__ import annotations
from dataclasses import dataclass
import cv2
from .platform_support import enumeration_api

@dataclass(frozen=True)
class CameraDevice:
    index: int
    name: str
    path: str
    backend: int

    @property
    def label(self) -> str:
        return f'{self.name} · {self.index}'

    @property
    def virtual(self) -> bool:
        return any(word in self.name.lower() for word in ('obs','virtual','unity','quest'))


def list_cameras() -> list[CameraDevice]:
    # Enumerating metadata does not open the webcam or read frames.
    # Imported lazily: on macOS it needs PyObjC (AVFoundation) and should fail as a list error, not at startup.
    from cv2_enumerate_cameras import enumerate_cameras
    return [CameraDevice(c.index,str(c.name),str(c.path or ''),c.backend)
            for c in enumerate_cameras(enumeration_api())]
