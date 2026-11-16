"""Source abstraction: the ETL reads workbooks through this, never through Drive directly.

`InMemorySource` backs tests and the mock-data generator, so mock data flows through exactly
the same parsing / loading code as real Drive data. A Drive-backed source is added separately.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable, Protocol


@dataclass(frozen=True)
class FileMeta:
    drive_file_id: str
    name: str  # workbook title, e.g. 'APC_TD Bank Platform_Q1 2026'
    year: int | None
    quarter: int | None
    modified_time: datetime


class SheetSource(Protocol):
    def list_files(self) -> Iterable[FileMeta]: ...
    def list_tabs(self, file: FileMeta) -> list[str]: ...
    def read_tab(self, file: FileMeta, tab: str) -> list[list[Any]]: ...
    # Reads several tabs of one workbook together (one API round trip on Drive). Only tabs the sync
    # decided to read are passed, so credential / pivot tabs are never requested.
    def read_tabs(self, file: FileMeta, tabs: list[str]) -> dict[str, list[list[Any]]]: ...


@dataclass
class InMemoryWorkbook:
    meta: FileMeta
    tabs: dict[str, list[list[Any]]]


@dataclass
class InMemorySource:
    workbooks: list[InMemoryWorkbook] = field(default_factory=list)
    reads: list[tuple[str, str]] = field(default_factory=list)  # (file name, tab) actually fetched

    def list_files(self) -> Iterable[FileMeta]:
        return [w.meta for w in self.workbooks]

    def _wb(self, file: FileMeta) -> InMemoryWorkbook:
        return next(w for w in self.workbooks if w.meta.drive_file_id == file.drive_file_id)

    def list_tabs(self, file: FileMeta) -> list[str]:
        return list(self._wb(file).tabs)

    def read_tab(self, file: FileMeta, tab: str) -> list[list[Any]]:
        self.reads.append((file.name, tab))
        return self._wb(file).tabs[tab]

    def read_tabs(self, file: FileMeta, tabs: list[str]) -> dict[str, list[list[Any]]]:
        return {t: self.read_tab(file, t) for t in tabs}
