"""Storage. Agents talk to :class:`Repository`, never to a backend directly."""

from head_hunter.storage.json_repo import JsonRepository, StorageError
from head_hunter.storage.repository import Repository

__all__ = ["JsonRepository", "Repository", "StorageError"]
