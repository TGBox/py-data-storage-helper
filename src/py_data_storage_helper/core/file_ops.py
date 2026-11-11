"""Qt-freie Dateioperationen für Transfer und Rollback.

Kopiert Dateien über eine .stpart-Zwischendatei, prüft die Kopie per SHA-256 gegen die Quelle
und löst Plan-Operationen (Einzeldatei, Ordner, Dateiliste) in konkrete Quell-/Zielpaare auf.
"""

import os
import hashlib
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from .utils import to_long_path, strip_long_path_prefix, volume_root, is_junction_or_symlink

CHUNK_SIZE = 1024 * 1024
PART_SUFFIX = ".stpart"

CancelCb = Optional[Callable[[], bool]]


@dataclass
class FileResult:
    status: str  # SUCCESS | SKIPPED | FAILED | CANCELLED
    message: str = ""
    target: str = ""
    size: int = 0
    checksum: str = ""


@dataclass
class OpResult:
    status: str  # SUCCESS | SKIPPED | FAILED | CANCELLED
    message: str = ""
    bytes_done: int = 0
    checksum: str = ""
    # (operation_type, source, target, size, checksum) je tatsächlich übertragener Datei
    journal: List[Tuple[str, str, str, int, str]] = field(default_factory=list)


def _remove_quietly(path: Optional[str]) -> None:
    if path:
        try:
            os.remove(path)
        except OSError:
            pass


def _hash_file(long_path: str, cancel_cb: CancelCb = None) -> Optional[str]:
    """SHA-256 einer Datei, None bei Abbruch."""
    hasher = hashlib.sha256()
    with open(long_path, "rb") as f:
        while chunk := f.read(CHUNK_SIZE):
            if cancel_cb and cancel_cb():
                return None
            hasher.update(chunk)
    return hasher.hexdigest()


def _unique_version_path(long_tgt: str) -> str:
    base, ext = os.path.splitext(long_tgt)
    n = 1
    while os.path.exists(f"{base}_kopie_{n}{ext}"):
        n += 1
    return f"{base}_kopie_{n}{ext}"


def copy_file_verified(
    src: str,
    tgt: str,
    conflict_strategy: str = "VERSION",
    verify: bool = True,
    preserve_timestamps: bool = True,
    chunk_cb: Optional[Callable[[int], None]] = None,
    cancel_cb: CancelCb = None,
) -> FileResult:
    """Kopiert src nach tgt. Die Quelle wird nie verändert; das Ziel erscheint erst nach bestandener Prüfung."""
    long_src = to_long_path(src)
    long_tgt = to_long_path(tgt)
    part_path: Optional[str] = None
    try:
        if not os.path.isfile(long_src):
            return FileResult("FAILED", "Quelldatei nicht gefunden")
        if os.path.normcase(long_src) == os.path.normcase(long_tgt):
            return FileResult("FAILED", "Quelle und Ziel sind identisch")

        src_stat = os.stat(long_src)
        tgt_dir = os.path.dirname(long_tgt)
        if tgt_dir:
            os.makedirs(tgt_dir, exist_ok=True)

        if os.path.exists(long_tgt):
            if conflict_strategy == "SKIP":
                return FileResult("SKIPPED", "Datei existiert bereits am Ziel", size=src_stat.st_size)
            if conflict_strategy == "UPDATE":
                if src_stat.st_mtime <= os.stat(long_tgt).st_mtime:
                    return FileResult("SKIPPED", "Ziel ist gleich alt oder neuer", size=src_stat.st_size)
            elif conflict_strategy == "VERSION":
                long_tgt = _unique_version_path(long_tgt)
            # OVERWRITE und UPDATE (Quelle neuer): Ziel wird unten atomar ersetzt

        part_path = long_tgt + PART_SUFFIX
        hasher = hashlib.sha256() if verify else None
        copied = 0
        cancelled = False

        with open(long_src, "rb") as f_in, open(part_path, "wb") as f_out:
            while True:
                if cancel_cb and cancel_cb():
                    cancelled = True
                    break
                chunk = f_in.read(CHUNK_SIZE)
                if not chunk:
                    break
                f_out.write(chunk)
                if hasher:
                    hasher.update(chunk)
                copied += len(chunk)
                if chunk_cb:
                    chunk_cb(len(chunk))
            if not cancelled:
                f_out.flush()
                os.fsync(f_out.fileno())

        if cancelled:
            _remove_quietly(part_path)
            return FileResult("CANCELLED", "Abbruch durch Benutzer")

        if os.path.getsize(part_path) != copied or os.stat(long_src).st_size != copied:
            _remove_quietly(part_path)
            return FileResult("FAILED", "Größe weicht ab (Quelle während des Kopierens geändert?)")

        checksum = ""
        if hasher:
            checksum = hasher.hexdigest()
            tgt_hash = _hash_file(part_path, cancel_cb)
            if tgt_hash is None:
                _remove_quietly(part_path)
                return FileResult("CANCELLED", "Abbruch durch Benutzer")
            if tgt_hash != checksum:
                _remove_quietly(part_path)
                return FileResult("FAILED", "Prüfsumme der Kopie weicht von der Quelle ab")

        os.replace(part_path, long_tgt)
        part_path = None

        if preserve_timestamps:
            os.utime(long_tgt, (src_stat.st_atime, src_stat.st_mtime))

        return FileResult("SUCCESS", "Erfolgreich übertragen", strip_long_path_prefix(long_tgt), copied, checksum)
    except Exception as ex:
        _remove_quietly(part_path)
        return FileResult("FAILED", str(ex))


def resolve_op_pairs(op: Dict[str, Any]) -> Tuple[List[Tuple[str, str]], List[Tuple[str, str]], str]:
    """Löst eine Plan-Operation in (Dateipaare, Ordnerpaare, Fehlertext) auf.

    - op["files"] gesetzt: Liste relativer Pfade unterhalb von source_path, Struktur bleibt unter target_path erhalten
    - source_path ist ein Ordner: alle Dateien darunter (ohne Junctions/Symlinks)
    - sonst: Einzeldatei
    Ordnerpaare sind von innen nach außen sortiert (für das Aufräumen leerer Quellordner).
    """
    src_root = volume_root(op.get("source_volume") or "")
    tgt_root = volume_root(op.get("target_volume") or "")
    if not src_root or not tgt_root:
        return [], [], "Quell- oder Ziel-Laufwerk fehlt"

    src_base = os.path.join(src_root, op.get("source_path") or "")
    tgt_base = os.path.join(tgt_root, op.get("target_path") or "")

    files = op.get("files")
    if files:
        return [(os.path.join(src_base, rel), os.path.join(tgt_base, rel)) for rel in files], [], ""

    long_src = to_long_path(src_base)
    if os.path.isdir(long_src):
        norm_src = os.path.normcase(os.path.abspath(src_base)).rstrip("\\/") + os.sep
        norm_tgt = os.path.normcase(os.path.abspath(tgt_base)).rstrip("\\/") + os.sep
        if norm_tgt.startswith(norm_src):
            return [], [], "Ziel liegt innerhalb der Quelle"

        pairs: List[Tuple[str, str]] = []
        dir_pairs: List[Tuple[str, str]] = []
        for cur, dirnames, filenames in os.walk(long_src):
            dirnames[:] = [d for d in dirnames if not is_junction_or_symlink(os.path.join(cur, d))]
            rel = os.path.relpath(cur, long_src)
            rel = "" if rel == "." else rel
            dir_pairs.append((cur, os.path.join(tgt_base, rel)))
            for name in filenames:
                full = os.path.join(cur, name)
                if os.path.islink(full):
                    continue
                pairs.append((full, os.path.join(tgt_base, rel, name)))
        dir_pairs.reverse()
        return pairs, dir_pairs, ""

    if os.path.isfile(long_src):
        return [(src_base, tgt_base)], [], ""

    return [], [], f"Quelle nicht gefunden: {src_base}"


def run_operation(
    op: Dict[str, Any],
    conflict_strategy: str = "VERSION",
    verify: bool = True,
    preserve_timestamps: bool = True,
    progress_cb: Optional[Callable[[str, int, int], None]] = None,
    cancel_cb: CancelCb = None,
) -> OpResult:
    """Führt eine COPY/MOVE-Operation aus. Bei MOVE wird jede Quelldatei erst nach erfolgreicher Kopie gelöscht."""
    op_type = op.get("type", "MOVE")
    pairs, dir_pairs, error = resolve_op_pairs(op)
    if error:
        return OpResult("FAILED", error)

    sizes: List[int] = []
    for src, _ in pairs:
        try:
            sizes.append(os.path.getsize(to_long_path(src)))
        except OSError:
            sizes.append(0)
    total = sum(sizes)

    for _, tgt_dir in dir_pairs:
        try:
            os.makedirs(to_long_path(tgt_dir), exist_ok=True)
        except OSError:
            pass

    result = OpResult("SUCCESS")
    ok = skipped = failed = leftovers = 0
    first_error = ""
    base = 0

    for (src, tgt), size in zip(pairs, sizes):
        if cancel_cb and cancel_cb():
            result.status, result.message = "CANCELLED", "Abbruch durch Benutzer"
            return result

        name = os.path.basename(src)
        state = {"cur": 0}

        def on_chunk(n: int, _name: str = name, _state: Dict[str, int] = state, _base: int = base) -> None:
            _state["cur"] += n
            if progress_cb:
                progress_cb(_name, _base + _state["cur"], total)

        res = copy_file_verified(src, tgt, conflict_strategy, verify, preserve_timestamps, on_chunk, cancel_cb)
        base += size
        if progress_cb:
            progress_cb(name, base, total)

        if res.status == "CANCELLED":
            result.status, result.message = "CANCELLED", "Abbruch durch Benutzer"
            return result
        if res.status == "SUCCESS":
            ok += 1
            result.bytes_done += res.size
            result.checksum = res.checksum if len(pairs) == 1 else ""
            logged_type = op_type
            if op_type == "MOVE":
                try:
                    os.remove(to_long_path(src))
                except OSError:
                    leftovers += 1
                    logged_type = "COPY"  # Quelle liegt noch da
            result.journal.append((logged_type, strip_long_path_prefix(src), res.target, res.size, res.checksum))
        elif res.status == "SKIPPED":
            skipped += 1
        else:
            failed += 1
            first_error = first_error or f"{name}: {res.message}"

    if op_type == "MOVE":
        for src_dir, _ in dir_pairs:
            try:
                os.rmdir(src_dir)  # nur leere Ordner
            except OSError:
                pass

    if failed:
        result.status = "FAILED"
        result.message = f"{failed} von {len(pairs)} Dateien fehlgeschlagen – {first_error}"
    elif leftovers:
        result.status = "FAILED"
        result.message = f"Kopiert und geprüft, aber {leftovers} Quelldatei(en) konnten nicht gelöscht werden"
    elif ok == 0 and skipped:
        result.status = "SKIPPED"
        result.message = f"{skipped} Datei(en) übersprungen"
    else:
        result.message = f"{ok} Datei(en) übertragen" + (f", {skipped} übersprungen" if skipped else "")
    return result
