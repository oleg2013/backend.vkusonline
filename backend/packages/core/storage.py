from __future__ import annotations

import os
import shutil
from abc import ABC, abstractmethod
from pathlib import Path

from packages.core.config import settings


class StorageBackend(ABC):
    @abstractmethod
    async def save(self, path: str, data: bytes) -> str:
        ...

    @abstractmethod
    async def read(self, path: str) -> bytes | None:
        ...

    @abstractmethod
    async def delete(self, path: str) -> bool:
        ...

    @abstractmethod
    async def exists(self, path: str) -> bool:
        ...


class LocalStorage(StorageBackend):
    def __init__(self, base_path: str):
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)

    def _full_path(self, path: str) -> Path:
        return self.base_path / path

    async def save(self, path: str, data: bytes) -> str:
        full = self._full_path(path)
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_bytes(data)
        return str(full)

    async def read(self, path: str) -> bytes | None:
        full = self._full_path(path)
        if full.exists():
            return full.read_bytes()
        return None

    async def delete(self, path: str) -> bool:
        full = self._full_path(path)
        if full.exists():
            full.unlink()
            return True
        return False

    async def exists(self, path: str) -> bool:
        return self._full_path(path).exists()


def get_storage() -> StorageBackend:
    if settings.storage_type == "local":
        return LocalStorage(settings.storage_local_path)
    raise ValueError(f"Unknown storage type: {settings.storage_type}")
