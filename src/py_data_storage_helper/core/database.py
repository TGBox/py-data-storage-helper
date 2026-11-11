import os
import sqlite3
import json
import datetime
from typing import Dict, List, Optional, Tuple, Any

from ..constants import DB_FILENAME
from .utils import to_long_path
from .file_ops import copy_file_verified
from .drive_detector import DriveDetector


class DatabaseManager:
    """Thread-safe SQLite wrapper operating in high-performance Write-Ahead-Logging (WAL) mode."""

    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            data_dir = os.path.join(os.path.expanduser("~"), ".storage_manager")
            os.makedirs(data_dir, exist_ok=True)
            self.db_path = os.path.join(data_dir, DB_FILENAME)
        else:
            self.db_path = db_path
        self.init_database()

    def get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        conn.row_factory = sqlite3.Row
        return conn

    def init_database(self) -> None:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS volumes (
                id TEXT PRIMARY KEY,
                label TEXT,
                letter TEXT,
                total_space INTEGER,
                free_space INTEGER,
                file_system TEXT,
                is_ssd INTEGER DEFAULT 0,
                drive_type TEXT,
                smart_status TEXT DEFAULT 'OK',
                last_indexed TIMESTAMP
            );
            """)

            cursor.execute("""
            CREATE TABLE IF NOT EXISTS files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                volume_id TEXT,
                path TEXT NOT NULL,
                name TEXT NOT NULL,
                extension TEXT,
                size INTEGER NOT NULL,
                mtime REAL NOT NULL,
                ctime REAL NOT NULL,
                attributes INTEGER DEFAULT 0,
                category TEXT,
                FOREIGN KEY (volume_id) REFERENCES volumes(id) ON DELETE CASCADE
            );
            """)

            cursor.execute("""
            CREATE TABLE IF NOT EXISTS operation_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                operation_type TEXT NOT NULL,
                source_path TEXT NOT NULL,
                target_path TEXT,
                file_size INTEGER DEFAULT 0,
                checksum TEXT,
                reverted INTEGER DEFAULT 0
            );
            """)

            cursor.execute("CREATE INDEX IF NOT EXISTS idx_files_volume ON files(volume_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_files_size ON files(size);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_files_ext ON files(extension);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_files_cat ON files(category);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_files_vol_path ON files(volume_id, path COLLATE NOCASE);")
            conn.commit()

    def upsert_volume(self, vol_data: Dict[str, Any]) -> None:
        data = {
            "id": vol_data.get("id"),
            "label": vol_data.get("label", ""),
            "letter": vol_data.get("letter", ""),
            "total_space": vol_data.get("total_space", 0),
            "free_space": vol_data.get("free_space", 0),
            "file_system": vol_data.get("file_system", ""),
            "is_ssd": vol_data.get("is_ssd", 0),
            "drive_type": vol_data.get("drive_type", "Fixed Disk"),
            "smart_status": vol_data.get("smart_status", "OK"),
            "last_indexed": vol_data.get("last_indexed", None),
        }
        with self.get_connection() as conn:
            conn.execute("""
                INSERT INTO volumes (id, label, letter, total_space, free_space, file_system, is_ssd, drive_type, smart_status, last_indexed)
                VALUES (:id, :label, :letter, :total_space, :free_space, :file_system, :is_ssd, :drive_type, :smart_status, :last_indexed)
                ON CONFLICT(id) DO UPDATE SET
                    label=excluded.label,
                    letter=excluded.letter,
                    total_space=excluded.total_space,
                    free_space=excluded.free_space,
                    file_system=excluded.file_system,
                    is_ssd=excluded.is_ssd,
                    drive_type=excluded.drive_type,
                    smart_status=excluded.smart_status,
                    last_indexed=COALESCE(excluded.last_indexed, volumes.last_indexed);
            """, data)
            conn.commit()

    def get_volumes(self) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.execute("SELECT * FROM volumes ORDER BY letter ASC")
            return [dict(row) for row in cursor.fetchall()]

    def delete_volume_files(self, volume_id: str) -> None:
        with self.get_connection() as conn:
            conn.execute("DELETE FROM files WHERE volume_id = ?", (volume_id,))
            conn.commit()

    def insert_files_batch(self, file_records: List[Tuple]) -> None:
        if not file_records:
            return
        with self.get_connection() as conn:
            conn.executemany("""
                INSERT INTO files (volume_id, path, name, extension, size, mtime, ctime, attributes, category)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, file_records)
            conn.commit()

    def get_size_duplicate_candidates(self, volume_id: Optional[str] = None, min_size: int = 1024, category: Optional[str] = None) -> List[int]:
        with self.get_connection() as conn:
            query = "SELECT size FROM files WHERE size >= ?"
            params: List[Any] = [min_size]
            if volume_id:
                query += " AND volume_id = ?"
                params.append(volume_id)
            if category and category != "Alle Kategorien":
                query += " AND category = ?"
                params.append(category.lower())
            query += " GROUP BY size HAVING COUNT(*) > 1 ORDER BY size DESC"
            rows = conn.execute(query, params).fetchall()
            return [row["size"] for row in rows]

    def get_files_by_size(self, size: int, volume_id: Optional[str] = None) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            query = "SELECT f.*, v.letter as volume_letter FROM files f JOIN volumes v ON f.volume_id = v.id WHERE f.size = ?"
            params: List[Any] = [size]
            if volume_id:
                query += " AND f.volume_id = ?"
                params.append(volume_id)
            rows = conn.execute(query, params).fetchall()
            return [dict(row) for row in rows]

    def get_all_files_for_fuzzy(self, volume_id: Optional[str] = None, category: Optional[str] = None, limit: int = 3000) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            query = "SELECT f.*, v.letter as volume_letter FROM files f JOIN volumes v ON f.volume_id = v.id WHERE 1=1"
            params: List[Any] = []
            if volume_id:
                query += " AND f.volume_id = ?"
                params.append(volume_id)
            if category and category != "Alle Kategorien":
                query += " AND f.category = ?"
                params.append(category.lower())
            query += " ORDER BY f.size DESC LIMIT ?"
            params.append(limit)
            rows = conn.execute(query, params).fetchall()
            return [dict(row) for row in rows]

    def execute_physical_rollback(self, op_id: int) -> Tuple[bool, str]:
        with self.get_connection() as conn:
            row = conn.execute("SELECT * FROM operation_history WHERE id = ?", (op_id,)).fetchone()
            if not row:
                return False, "Operation nicht im Journal gefunden."
            if row["reverted"] == 1:
                return False, "Diese Operation wurde bereits rückgängig gemacht."

            op_type = row["operation_type"]
            src = row["source_path"]
            tgt = row["target_path"]

            try:
                if op_type == "MOVE":
                    if not tgt or not os.path.exists(to_long_path(tgt)):
                        return False, f"Zieldatei '{tgt}' existiert nicht mehr."
                    if os.path.exists(to_long_path(src)):
                        return False, f"Am ursprünglichen Ort '{src}' liegt bereits eine Datei."
                    res = copy_file_verified(tgt, src, conflict_strategy="SKIP", verify=True)
                    if res.status != "SUCCESS":
                        return False, f"Zurückkopieren fehlgeschlagen: {res.message}"
                    os.remove(to_long_path(tgt))
                elif op_type == "RENAME":
                    if not tgt or not os.path.exists(to_long_path(tgt)):
                        return False, f"Zieldatei '{tgt}' existiert nicht mehr."
                    target_dir = os.path.dirname(src)
                    if target_dir:
                        os.makedirs(to_long_path(target_dir), exist_ok=True)
                    os.rename(to_long_path(tgt), to_long_path(src))
                elif op_type == "DELETE":
                    return False, "Gelöschte Dateien müssen über den Windows-Papierkorb wiederhergestellt werden."
                else:
                    return False, f"Rollback für '{op_type}' wird nicht unterstützt."

                conn.execute("UPDATE operation_history SET reverted = 1 WHERE id = ?", (op_id,))
                conn.commit()
                try:
                    self.apply_transfers_to_index([("MOVE", tgt, src, 0, "")])
                except Exception:
                    pass  # Index ist nur ein Cache, die Datei liegt bereits wieder am alten Ort
                return True, f"Operation #{op_id} ({op_type}) erfolgreich rückgängig gemacht."
            except Exception as ex:
                return False, f"Dateisystem-Fehler beim Rollback: {ex}"

    def log_operation(self, op_type: str, source: str, target: Optional[str] = None, size: int = 0, checksum: Optional[str] = None) -> int:
        with self.get_connection() as conn:
            cursor = conn.execute("""
                INSERT INTO operation_history (operation_type, source_path, target_path, file_size, checksum)
                VALUES (?, ?, ?, ?, ?)
            """, (op_type, source, target, size, checksum))
            conn.commit()
            return cursor.lastrowid

    def delete_file_records(self, file_ids: List[int]) -> None:
        if not file_ids:
            return
        with self.get_connection() as conn:
            conn.executemany("DELETE FROM files WHERE id = ?", [(i,) for i in file_ids])
            conn.commit()

    @staticmethod
    def _locate_in_volumes(abs_path: str, drives: List[Dict[str, Any]]) -> Optional[Tuple[str, str]]:
        """Zerlegt einen absoluten Pfad in (volume_id, relativer Pfad) anhand der eingebundenen Laufwerke."""
        norm = os.path.normpath(abs_path)
        norm_cmp = os.path.normcase(norm)
        best: Optional[Tuple[str, str]] = None
        best_len = -1
        for d in drives:
            root = os.path.normpath(d.get("letter") or "")
            if not root:
                continue
            root_cmp = os.path.normcase(root)
            at_boundary = root_cmp.endswith(os.sep) or len(norm_cmp) == len(root_cmp) or norm_cmp[len(root_cmp):len(root_cmp) + 1] == os.sep
            if norm_cmp.startswith(root_cmp) and at_boundary and len(root_cmp) > best_len:
                best = (d["id"], norm[len(root):].lstrip("\\/"))
                best_len = len(root_cmp)
        return best

    def apply_transfers_to_index(self, journal: List[Tuple], drives: Optional[List[Dict[str, Any]]] = None) -> None:
        """Führt den Datei-Index nach: journal = (operation_type, source_abs, target_abs, size, checksum)."""
        if not journal:
            return
        if drives is None:
            drives = DriveDetector.get_mounted_drives()
        with self.get_connection() as conn:
            for op_type, src, tgt, *_ in journal:
                s = self._locate_in_volumes(src, drives)
                if not s:
                    continue
                t = self._locate_in_volumes(tgt, drives) if tgt else None
                try:
                    if t:
                        # ein evtl. überschriebenes Ziel aus dem Index nehmen
                        conn.execute("DELETE FROM files WHERE volume_id = ? AND path = ? COLLATE NOCASE", t)
                        name = os.path.basename(t[1])
                        ext = os.path.splitext(name)[1].lower()
                    if op_type == "MOVE" and t:
                        conn.execute(
                            "UPDATE files SET volume_id = ?, path = ?, name = ?, extension = ? "
                            "WHERE volume_id = ? AND path = ? COLLATE NOCASE",
                            (t[0], t[1], name, ext, s[0], s[1])
                        )
                    elif op_type == "MOVE":
                        conn.execute("DELETE FROM files WHERE volume_id = ? AND path = ? COLLATE NOCASE", s)
                    elif op_type == "COPY" and t:
                        conn.execute(
                            "INSERT INTO files (volume_id, path, name, extension, size, mtime, ctime, attributes, category) "
                            "SELECT ?, ?, ?, ?, size, mtime, ctime, attributes, category FROM files "
                            "WHERE volume_id = ? AND path = ? COLLATE NOCASE LIMIT 1",
                            (t[0], t[1], name, ext, s[0], s[1])
                        )
                except sqlite3.IntegrityError:
                    # Ziel-Volume ist der Datenbank unbekannt: Quelle bei MOVE trotzdem austragen
                    if op_type == "MOVE":
                        conn.execute("DELETE FROM files WHERE volume_id = ? AND path = ? COLLATE NOCASE", s)
            conn.commit()

    def log_operations_batch(self, records: List[Tuple]) -> None:
        """records: (operation_type, source_path, target_path, file_size, checksum)"""
        if not records:
            return
        with self.get_connection() as conn:
            conn.executemany("""
                INSERT INTO operation_history (operation_type, source_path, target_path, file_size, checksum)
                VALUES (?, ?, ?, ?, ?)
            """, records)
            conn.commit()

    def get_cluster_file_paths(self, volume_id: str, group_by: str, name: str) -> List[str]:
        """Relative Pfade aller Dateien eines Clusters: einer Kategorie oder der Dateien direkt im Laufwerks-Root."""
        with self.get_connection() as conn:
            if group_by == "category":
                rows = conn.execute(
                    "SELECT path FROM files WHERE volume_id = ? AND category = ? ORDER BY path", (volume_id, name)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT path FROM files WHERE volume_id = ? AND INSTR(path, '/') = 0 AND INSTR(path, '\\') = 0 ORDER BY path",
                    (volume_id,)
                ).fetchall()
            return [r["path"] for r in rows]

    def get_operation_logs(self, limit: int = 100) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.execute("""
                SELECT * FROM operation_history ORDER BY id DESC LIMIT ?
            """, (limit,))
            return [dict(row) for row in cursor.fetchall()]

    def get_volume_aggregates(self, volume_id: str, group_by: str = "category") -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            if group_by == "category":
                query = """
                    SELECT category as group_name, COUNT(*) as file_count, SUM(size) as total_size
                    FROM files
                    WHERE volume_id = ?
                    GROUP BY category
                    HAVING total_size > 0
                    ORDER BY total_size DESC
                """
                rows = conn.execute(query, (volume_id,)).fetchall()
            else:
                query = """
                    SELECT 
                        CASE 
                            WHEN INSTR(path, '/') > 0 THEN SUBSTR(path, 1, INSTR(path, '/') - 1)
                            WHEN INSTR(path, '\\') > 0 THEN SUBSTR(path, 1, INSTR(path, '\\') - 1)
                            ELSE '[Root Files]'
                        END as group_name,
                        COUNT(*) as file_count,
                        SUM(size) as total_size
                    FROM files
                    WHERE volume_id = ?
                    GROUP BY group_name
                    HAVING total_size > 0
                    ORDER BY total_size DESC
                    LIMIT 25
                """
                rows = conn.execute(query, (volume_id,)).fetchall()

            result = []
            for r in rows:
                result.append({
                    "cluster_id": f"{volume_id}_{r['group_name']}",
                    "volume_id": volume_id,
                    "group_by": "category" if group_by == "category" else "folder",
                    "group_name": r["group_name"],
                    "name": r["group_name"] or "Unbekannt",
                    "file_count": r["file_count"],
                    "total_size": r["total_size"] or 0
                })
            return result

    def get_treemap_node_children(self, volume_id: str, parent_path: str = "") -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            norm_parent = parent_path.strip("/\\")
            prefix = norm_parent + "\\" if norm_parent else ""
            prefix_len = len(prefix)

            query = "SELECT path, name, extension, size, category FROM files WHERE volume_id = ?"
            params: List[Any] = [volume_id]
            if norm_parent:
                query += " AND (path LIKE ? OR path LIKE ?)"
                params.append(f"{norm_parent}/%")
                params.append(f"{norm_parent}\\%")

            rows = conn.execute(query, params).fetchall()
            if not rows:
                return []

            dir_map: Dict[str, Dict[str, Any]] = {}
            file_list: List[Dict[str, Any]] = []

            for r in rows:
                rel = r["path"].replace("/", "\\")
                if norm_parent and rel.startswith(prefix):
                    remainder = rel[prefix_len:]
                elif not norm_parent:
                    remainder = rel
                else:
                    continue

                parts = remainder.split("\\")
                if len(parts) > 1:
                    sub_dir = parts[0]
                    if sub_dir not in dir_map:
                        full_sub_path = os.path.join(norm_parent, sub_dir) if norm_parent else sub_dir
                        dir_map[sub_dir] = {
                            "name": sub_dir,
                            "path": full_sub_path,
                            "is_dir": True,
                            "size": 0,
                            "file_count": 0,
                            "category": "folder"
                        }
                    dir_map[sub_dir]["size"] += r["size"]
                    dir_map[sub_dir]["file_count"] += 1
                else:
                    file_list.append({
                        "name": r["name"],
                        "path": r["path"],
                        "is_dir": False,
                        "size": r["size"],
                        "file_count": 1,
                        "category": r["category"] or DriveDetector.categorize_extension(r["extension"] or "")
                    })

            results = list(dir_map.values()) + file_list
            results.sort(key=lambda x: x["size"], reverse=True)
            return results

