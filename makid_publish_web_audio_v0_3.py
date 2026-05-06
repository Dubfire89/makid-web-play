#!/usr/bin/env python3
# MAKID WebAudioFile publisher
# Version: 0.3
#
# What this version does:
# - Reads your local MAKID.db
# - Extracts one clean web table
# - Looks up Google Drive file IDs from your local Google Drive paths
# - Writes WebAudioFile.json
#
# Required local file by default:
# ~/Library/Application Support/makid/google_credentials.json
#
# First run:
# - A browser window opens
# - You approve Google Drive read access
# - A token is saved locally for next time

import json
import os
import pickle
import shutil
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote


VERSION = "0.3"


def path_from_env(name: str, default: Path) -> Path:
    return Path(os.environ.get(name, str(default))).expanduser()


def optional_path_from_env(name: str) -> Optional[Path]:
    value = os.environ.get(name)
    if not value:
        return None
    return Path(value).expanduser()


APP_SUPPORT_FOLDER = path_from_env(
    "MAKID_APP_SUPPORT_FOLDER",
    Path.home() / "Library" / "Application Support" / "makid",
)
SOURCE_DB = path_from_env("MAKID_SOURCE_DB", APP_SUPPORT_FOLDER / "MAKID.db")
OUTPUT_FOLDER = APP_SUPPORT_FOLDER / "web_export"
OUTPUT_JSON = OUTPUT_FOLDER / "WebAudioFile.json"

GOOGLE_CREDENTIALS_JSON = path_from_env(
    "MAKID_GOOGLE_CREDENTIALS_JSON",
    APP_SUPPORT_FOLDER / "google_credentials.json",
)
GOOGLE_TOKEN_PICKLE = path_from_env(
    "MAKID_GOOGLE_TOKEN_PICKLE",
    APP_SUPPORT_FOLDER / "google_drive_token.pickle",
)

# Optional web app copy target. Keep unset for the private-JSON web app flow.
COPY_TO_WEB_APP_FOLDER = optional_path_from_env("MAKID_COPY_TO_WEB_APP_FOLDER")

LOCAL_MY_DRIVE_PREFIX = str(
    path_from_env("MAKID_GOOGLE_DRIVE_ROOT", Path.home() / "My Drive")
).rstrip("/") + "/"

AUDIO_EXTENSIONS = {
    ".wav",
    ".wave",
    ".aif",
    ".aiff",
    ".mp3",
    ".flac",
    ".m4a",
}

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]


def ensure_google_libraries() -> None:
    missing = []

    try:
        import google.auth.transport.requests  # noqa: F401
    except Exception:
        missing.append("google-auth")

    try:
        import google_auth_oauthlib.flow  # noqa: F401
    except Exception:
        missing.append("google-auth-oauthlib")

    try:
        import googleapiclient.discovery  # noqa: F401
    except Exception:
        missing.append("google-api-python-client")

    if missing:
        print("")
        print("Missing Google Drive Python libraries.")
        print("")
        print("Run this command once:")
        print("")
        print('/usr/bin/python3 -m pip install --upgrade google-api-python-client google-auth-httplib2 google-auth-oauthlib')
        print("")
        raise SystemExit(1)


def one_line(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def split_csv(value: Any) -> List[str]:
    if value is None:
        return []
    text = str(value).strip()
    if not text:
        return []
    return [part.strip() for part in text.split(",") if part.strip()]


def drive_relative_path(local_path: Optional[str]) -> Optional[str]:
    if not local_path:
        return None

    local_path = local_path.strip()

    if local_path.startswith(LOCAL_MY_DRIVE_PREFIX):
        return local_path[len(LOCAL_MY_DRIVE_PREFIX):]

    return None


def parent_folder_from_project_path(project_path: Optional[str]) -> Optional[str]:
    if not project_path:
        return None

    p = project_path.strip().rstrip("/")
    parent = os.path.basename(os.path.dirname(p))
    return parent or None


def project_folder_path_from_file_path(file_path: Optional[str]) -> Optional[str]:
    if not file_path:
        return None
    return os.path.dirname(file_path.strip())


def google_query_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("'", "\\'")


def fetch_rows(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    conn.row_factory = sqlite3.Row

    sql = """
    WITH
    ProjectGenreAgg AS (
        SELECT
            pg.projectId AS project_id,
            GROUP_CONCAT(g.name, ', ') AS genre
        FROM ProjectGenres pg
        JOIN Genre g ON g.id = pg.genreId
        GROUP BY pg.projectId
    ),
    ProjectCollectionAgg AS (
        SELECT
            pc.projectId AS project_id,
            GROUP_CONCAT(c.name, ', ') AS collection
        FROM ProjectCollection pc
        JOIN Collection c ON c.id = pc.collectionId
        GROUP BY pc.projectId
    ),
    ProjectTagAgg AS (
        SELECT
            pt.projectId AS project_id,
            GROUP_CONCAT(t.name, ', ') AS tags
        FROM ProjectTags pt
        JOIN Tag t ON t.id = pt.tagId
        GROUP BY pt.projectId
    )
    SELECT
        p.id AS project_id,
        p.name AS project_name,
        p.path AS project_path,
        p.archived AS project_archived,
        p.missing AS project_missing,
        p.progress AS progress,
        p.tier AS tier,

        pga.genre AS genre,
        pca.collection AS collection,
        pta.tags AS tags,

        tr.tempo AS tempo,

        f.id AS file_id,
        f.name AS file_name,
        f.ext AS file_ext,
        f.path AS local_path,
        f.size AS file_size_bytes,
        f.createdAt AS file_created_at,
        f.lastModified AS file_last_modified,
        f.hash AS file_hash

    FROM ProjectFiles pf
    JOIN Project p ON p.id = pf.projectId
    JOIN File f ON f.id = pf.fileId
    LEFT JOIN ProjectGenreAgg pga ON pga.project_id = p.id
    LEFT JOIN ProjectCollectionAgg pca ON pca.project_id = p.id
    LEFT JOIN ProjectTagAgg pta ON pta.project_id = p.id
    LEFT JOIN Track tr ON tr.id = p.primaryTrackId

    WHERE LOWER(f.ext) IN (
        '.wav',
        '.wave',
        '.aif',
        '.aiff',
        '.mp3',
        '.flac',
        '.m4a'
    )

    ORDER BY
        p.name COLLATE NOCASE,
        f.createdAt,
        f.name COLLATE NOCASE
    """

    rows = conn.execute(sql).fetchall()
    result: List[Dict[str, Any]] = []

    for row in rows:
        local_path = one_line(row["local_path"])
        project_path = one_line(row["project_path"])

        item = {
            "project_id": row["project_id"],
            "project_name": one_line(row["project_name"]),
            "project_path": project_path,
            "parent_folder": parent_folder_from_project_path(project_path),
            "project_folder_path": project_folder_path_from_file_path(local_path),
            "project_archived": bool(row["project_archived"]),
            "project_missing": bool(row["project_missing"]),

            "genre": split_csv(row["genre"]),
            "tempo": row["tempo"],
            "collection": split_csv(row["collection"]),
            "progress": one_line(row["progress"]),
            "tier": one_line(row["tier"]),
            "tags": split_csv(row["tags"]),

            "file_id": row["file_id"],
            "file_name": one_line(row["file_name"]),
            "file_ext": one_line(row["file_ext"]),
            "local_path": local_path,
            "drive_relative_path": drive_relative_path(local_path),
            "drive_file_id": None,
            "drive_lookup_status": "not_started",

            "file_size_bytes": row["file_size_bytes"],
            "file_created_at": one_line(row["file_created_at"]),
            "file_last_modified": one_line(row["file_last_modified"]),
            "file_hash": one_line(row["file_hash"]),
        }

        result.append(item)

    return result


def get_drive_service():
    ensure_google_libraries()

    from google.auth.transport.requests import Request
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    creds = None

    if GOOGLE_TOKEN_PICKLE.exists():
        with GOOGLE_TOKEN_PICKLE.open("rb") as token_file:
            creds = pickle.load(token_file)

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())

    if not creds or not creds.valid:
        if not GOOGLE_CREDENTIALS_JSON.exists():
            raise FileNotFoundError(f"Google credentials file not found: {GOOGLE_CREDENTIALS_JSON}")

        flow = InstalledAppFlow.from_client_secrets_file(str(GOOGLE_CREDENTIALS_JSON), SCOPES)
        creds = flow.run_local_server(port=0)

        with GOOGLE_TOKEN_PICKLE.open("wb") as token_file:
            pickle.dump(creds, token_file)

    return build("drive", "v3", credentials=creds)


class DrivePathResolver:
    def __init__(self, service):
        self.service = service
        self.folder_cache: Dict[Tuple[str, str], Optional[str]] = {}
        self.file_cache: Dict[Tuple[str, str], Optional[Dict[str, Any]]] = {}

    def find_child_folder_id(self, parent_id: str, folder_name: str) -> Optional[str]:
        key = (parent_id, folder_name)
        if key in self.folder_cache:
            return self.folder_cache[key]

        escaped_name = google_query_escape(folder_name)
        query = (
            f"name = '{escaped_name}' "
            f"and mimeType = 'application/vnd.google-apps.folder' "
            f"and '{parent_id}' in parents "
            f"and trashed = false"
        )

        response = self.service.files().list(
            q=query,
            spaces="drive",
            fields="files(id, name)",
            pageSize=10,
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        ).execute()

        files = response.get("files", [])
        folder_id = files[0]["id"] if files else None

        self.folder_cache[key] = folder_id
        return folder_id

    def find_child_file(self, parent_id: str, file_name: str) -> Optional[Dict[str, Any]]:
        key = (parent_id, file_name)
        if key in self.file_cache:
            return self.file_cache[key]

        escaped_name = google_query_escape(file_name)
        query = (
            f"name = '{escaped_name}' "
            f"and '{parent_id}' in parents "
            f"and trashed = false"
        )

        response = self.service.files().list(
            q=query,
            spaces="drive",
            fields="files(id, name, mimeType, size, modifiedTime, md5Checksum)",
            pageSize=10,
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        ).execute()

        files = response.get("files", [])
        match = files[0] if files else None

        self.file_cache[key] = match
        return match

    def resolve_drive_relative_path(self, relative_path: Optional[str]) -> Tuple[Optional[str], str, Optional[Dict[str, Any]]]:
        if not relative_path:
            return None, "no_drive_relative_path", None

        parts = [part for part in relative_path.split("/") if part]

        if len(parts) < 2:
            return None, "path_too_short", None

        folder_parts = parts[:-1]
        file_name = parts[-1]

        parent_id = "root"

        for folder_name in folder_parts:
            folder_id = self.find_child_folder_id(parent_id, folder_name)
            if not folder_id:
                return None, f"folder_not_found: {folder_name}", None
            parent_id = folder_id

        file_match = self.find_child_file(parent_id, file_name)

        if not file_match:
            return None, "file_not_found", None

        return file_match["id"], "found", file_match


def fill_drive_file_ids(rows: List[Dict[str, Any]]) -> None:
    print("")
    print("Connecting to Google Drive...")

    service = get_drive_service()
    resolver = DrivePathResolver(service)

    total = len(rows)
    found = 0
    missing = 0

    print("Looking up Google Drive file IDs...")
    print("")

    for index, row in enumerate(rows, start=1):
        relative_path = row.get("drive_relative_path")

        drive_file_id, status, metadata = resolver.resolve_drive_relative_path(relative_path)

        row["drive_file_id"] = drive_file_id
        row["drive_lookup_status"] = status

        if metadata:
            row["drive_name"] = metadata.get("name")
            row["drive_mime_type"] = metadata.get("mimeType")
            row["drive_size_bytes"] = metadata.get("size")
            row["drive_modified_time"] = metadata.get("modifiedTime")
            row["drive_md5_checksum"] = metadata.get("md5Checksum")
        else:
            row["drive_name"] = None
            row["drive_mime_type"] = None
            row["drive_size_bytes"] = None
            row["drive_modified_time"] = None
            row["drive_md5_checksum"] = None

        if drive_file_id:
            found += 1
        else:
            missing += 1

        print(f"[{index}/{total}] {status}: {row.get('file_name')}")

    print("")
    print(f"Drive lookup complete. Found: {found}. Missing: {missing}.")


def write_json(rows: List[Dict[str, Any]]) -> None:
    OUTPUT_FOLDER.mkdir(parents=True, exist_ok=True)

    payload = {
        "export_version": VERSION,
        "source_db": str(SOURCE_DB),
        "row_count": len(rows),
        "rows": rows,
    }

    OUTPUT_JSON.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def copy_to_web_app_folder() -> Optional[Path]:
    if COPY_TO_WEB_APP_FOLDER is None:
        return None

    COPY_TO_WEB_APP_FOLDER.mkdir(parents=True, exist_ok=True)
    destination = COPY_TO_WEB_APP_FOLDER / OUTPUT_JSON.name
    shutil.copy2(OUTPUT_JSON, destination)
    return destination


def main() -> None:
    print(f"MAKID WebAudioFile publisher v{VERSION}")
    print(f"Source database: {SOURCE_DB}")
    print(f"Google credentials: {GOOGLE_CREDENTIALS_JSON}")

    if not SOURCE_DB.exists():
        raise FileNotFoundError(f"Source database not found: {SOURCE_DB}")

    if not GOOGLE_CREDENTIALS_JSON.exists():
        raise FileNotFoundError(f"Google credentials file not found: {GOOGLE_CREDENTIALS_JSON}")

    conn = sqlite3.connect(SOURCE_DB)

    try:
        rows = fetch_rows(conn)
    finally:
        conn.close()

    rows_with_drive_path = sum(1 for row in rows if row.get("drive_relative_path"))
    rows_without_drive_path = len(rows) - rows_with_drive_path

    print("")
    print(f"Rows extracted: {len(rows)}")
    print(f"Rows with Drive-relative path: {rows_with_drive_path}")
    print(f"Rows without Drive-relative path: {rows_without_drive_path}")

    fill_drive_file_ids(rows)
    write_json(rows)

    copied_to = copy_to_web_app_folder()

    print("")
    print("Export complete.")
    print(f"Written JSON: {OUTPUT_JSON}")

    if copied_to:
        print(f"Copied to web app folder: {copied_to}")
    else:
        print("Web app copy: skipped")

    print("")
    print("Done.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("")
        print("Stopped by user.")
        sys.exit(130)
    except Exception as error:
        print("")
        print("ERROR:")
        print(error)
        sys.exit(1)
