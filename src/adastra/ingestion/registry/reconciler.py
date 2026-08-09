"""Reconciliación índice ↔ disco. Invariantes I1, I2, I3.

La ecuación de cierre es sobre el DISCO, no sobre el índice:

    retrievable + metadata + evaluation + noise = 1848

Una reconciliación que sólo cierre en 1826 deja 13 archivos sin invariante — y esos 13
son precisamente los catálogos que aportan procedencia y el gold set.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from adastra.core.models import CorpusEntry

from .. import config
from .index_loader import IndexRecord
from .scanner import ScannedFile


@dataclass
class Reconciliation:
    entries: list[CorpusEntry]

    index_count: int = 0
    disk_total: int = 0
    disk_useful: int = 0
    noise_count: int = 0

    missing_from_disk: list[str] = field(default_factory=list)
    extras_on_disk: list[str] = field(default_factory=list)
    unexpected_extras: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "index_count": self.index_count,
            "disk_total": self.disk_total,
            "disk_useful": self.disk_useful,
            "noise_count": self.noise_count,
            "extras_count": len(self.extras_on_disk),
            "missing_from_disk": self.missing_from_disk,
            "extras_on_disk": sorted(self.extras_on_disk),
            "unexpected_extras": sorted(self.unexpected_extras),
            "invariant_I2": {
                "expression": "index + extras + noise == disk_total",
                "values": [self.index_count, len(self.extras_on_disk), self.noise_count],
                "sum": self.index_count + len(self.extras_on_disk) + self.noise_count,
                "disk_total": self.disk_total,
                "holds": (
                    self.index_count + len(self.extras_on_disk) + self.noise_count
                )
                == self.disk_total,
            },
        }


def reconcile(
    index_records: list[IndexRecord],
    scanned: list[ScannedFile],
) -> Reconciliation:
    by_path = {r.relative_path: r for r in index_records}
    scanned_paths = {s.relative_path for s in scanned}

    entries: list[CorpusEntry] = []
    noise = 0
    extras: list[str] = []

    for sf in scanned:
        if sf.filename in config.NOISE_FILENAMES:
            noise += 1
            entries.append(
                CorpusEntry(
                    relative_path=sf.relative_path,
                    filename=sf.filename,
                    extension=sf.extension,
                    size_bytes=sf.size_bytes,
                    sha256=sf.sha256,
                    role="noise",
                    role_reason="macos_filesystem_artifact",
                    status="intentional_skip",
                    status_reason="noise",
                )
            )
            continue

        rec = by_path.get(sf.relative_path)
        if rec is None:
            extras.append(sf.relative_path)

        entries.append(
            CorpusEntry(
                doc_id=rec.doc_id if rec else None,
                phenomenon=rec.phenomenon if rec else None,
                observatory=rec.observatory if rec else None,
                observatory_code=rec.observatory_code if rec else None,
                declared_type=rec.declared_type if rec else None,
                relative_path=sf.relative_path,
                filename=sf.filename,
                extension=sf.extension,
                size_bytes=sf.size_bytes,
                sha256=sf.sha256,
            )
        )

    missing = sorted(set(by_path) - scanned_paths)
    unexpected = sorted(set(extras) - config.EXPECTED_EXTRAS)

    return Reconciliation(
        entries=entries,
        index_count=len(index_records),
        disk_total=len(scanned),
        disk_useful=len(scanned) - noise,
        noise_count=noise,
        missing_from_disk=missing,
        extras_on_disk=extras,
        unexpected_extras=unexpected,
    )


def assert_reconciliation(rec: Reconciliation, strict: bool = True) -> list[str]:
    """Comprueba I2/I3. Devuelve la lista de problemas; en `strict` los eleva a error."""
    problems: list[str] = []

    if rec.missing_from_disk:
        problems.append(
            f"I3: {len(rec.missing_from_disk)} archivos del índice no están en disco "
            f"(esperado 0): {rec.missing_from_disk[:5]}"
        )
    if rec.index_count != config.EXPECTED_INDEX_ENTRIES:
        problems.append(
            f"Índice: {rec.index_count} registros, esperados "
            f"{config.EXPECTED_INDEX_ENTRIES}"
        )
    if rec.disk_total != config.EXPECTED_TOTAL_FILES:
        problems.append(
            f"Disco: {rec.disk_total} archivos, esperados {config.EXPECTED_TOTAL_FILES}"
        )
    if rec.noise_count != config.EXPECTED_DS_STORE:
        problems.append(
            f"Ruido: {rec.noise_count} archivos, esperados {config.EXPECTED_DS_STORE}"
        )
    if rec.unexpected_extras:
        # Un extra no listado es un error, no una curiosidad.
        problems.append(
            f"Extras no declarados en config.EXPECTED_EXTRAS: {rec.unexpected_extras}"
        )
    inv = rec.as_dict()["invariant_I2"]
    if not inv["holds"]:
        problems.append(f"I2 no se cumple: {inv}")

    if problems and strict:
        raise AssertionError("Reconciliación fallida:\n  - " + "\n  - ".join(problems))
    return problems
