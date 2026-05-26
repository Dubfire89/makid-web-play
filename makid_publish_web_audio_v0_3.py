#!/usr/bin/env python3
# MAKID WebAudioFile publisher
# Version: 0.3
#
# What this version does:
# - Reads your local MAKID.db
# - Extracts one clean web table
# - Looks up Google Drive file IDs from your local Google Drive paths
# - Reuses cached Drive file IDs for unchanged audio rows
# - Writes WebAudioFile.json
# - Creates or updates a private WebAudioFile.json in Google Drive
# - Stores Google OAuth tokens as private JSON, not pickle
#
# Required local file by default:
# ~/Library/Application Support/makid/google_credentials.json
#
# First run:
# - A browser window opens
# - You approve Google Drive read and file-write access
# - A private JSON token is saved locally for next time

import json
import os
import shutil
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

os.umask(0o077)

VERSION = "0.4"
PROJECT_FOLDER = Path(__file__).resolve().parent
ENV_CONFIG_FILES = [
    PROJECT_FOLDER / ".env.production",
    PROJECT_FOLDER / ".env.local",
]


def parse_env_file(path: Path) -> Dict[str, str]:
    values: Dict[str, str] = {}

    if not path.exists():
        return values

    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()

        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue

        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")

        if key:
            values[key] = value

    return values


ENV_FILE_VALUES: Dict[str, str] = {}

for env_file in ENV_CONFIG_FILES:
    ENV_FILE_VALUES.update(parse_env_file(env_file))


def config_value(name: str, default: Optional[str] = None) -> Optional[str]:
    value = os.environ.get(name)

    if value is not None:
        return value

    value = ENV_FILE_VALUES.get(name)

    if value is not None:
        return value

    return default


def path_from_config(name: str, default: Path) -> Path:
    return Path(config_value(name, str(default)) or str(default)).expanduser()


def optional_path_from_config(name: str) -> Optional[Path]:
    value = config_value(name)
    if not value:
        return None
    return Path(value).expanduser()


APP_SUPPORT_FOLDER = path_from_config(
    "MAKID_APP_SUPPORT_FOLDER",
    Path.home() / "Library" / "Application Support" / "makid",
)
SOURCE_DB = path_from_config("MAKID_SOURCE_DB", APP_SUPPORT_FOLDER / "MAKID.db")
OUTPUT_FOLDER = APP_SUPPORT_FOLDER / "web_export"
OUTPUT_JSON = OUTPUT_FOLDER / "WebAudioFile.json"

GOOGLE_CREDENTIALS_JSON = path_from_config(
    "MAKID_GOOGLE_CREDENTIALS_JSON",
    APP_SUPPORT_FOLDER / "google_credentials.json",
)
GOOGLE_TOKEN_JSON = path_from_config(
    "MAKID_GOOGLE_TOKEN_JSON",
    APP_SUPPORT_FOLDER / "google_drive_token.json",
)
LEGACY_GOOGLE_TOKEN_PICKLE = path_from_config(
    "MAKID_GOOGLE_TOKEN_PICKLE",
    APP_SUPPORT_FOLDER / "google_drive_token.pickle",
)

# Optional web app copy target. Keep unset for the private-JSON web app flow.
COPY_TO_WEB_APP_FOLDER = optional_path_from_config("MAKID_COPY_TO_WEB_APP_FOLDER")

LIBRARY_DRIVE_FILE_NAME = config_value("MAKID_LIBRARY_DRIVE_FILE_NAME", "WebAudioFile.json") or "WebAudioFile.json"
LIBRARY_DRIVE_FOLDER_ID = config_value("MAKID_LIBRARY_DRIVE_FOLDER_ID")
LIBRARY_DRIVE_PATH = config_value("MAKID_LIBRARY_DRIVE_PATH")

LOCAL_MY_DRIVE_PREFIX = str(
    path_from_config("MAKID_GOOGLE_DRIVE_ROOT", Path.home() / "My Drive")
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

SCOPES = [
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/drive.file",
]

PRIVATE_DIR_MODE = 0o700
PRIVATE_FILE_MODE = 0o600


def chmod_private(path: Path, mode: int) -> None:
    try:
        path.chmod(mode)
    except FileNotFoundError:
        return
    except PermissionError as error:
        raise PermissionError(f"Could not secure permissions for {path}: {error}") from error


def ensure_private_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    chmod_private(path, PRIVATE_DIR_MODE)


def ensure_private_file(path: Path) -> None:
    if path.exists():
        chmod_private(path, PRIVATE_FILE_MODE)


def write_private_text(path: Path, text: str) -> None:
    ensure_private_directory(path.parent)
    path.write_text(text, encoding="utf-8")
    chmod_private(path, PRIVATE_FILE_MODE)


def secure_local_paths() -> None:
    ensure_private_directory(APP_SUPPORT_FOLDER)
    ensure_private_directory(OUTPUT_FOLDER)
    ensure_private_file(GOOGLE_CREDENTIALS_JSON)
    ensure_private_file(GOOGLE_TOKEN_JSON)
    ensure_private_file(LEGACY_GOOGLE_TOKEN_PICKLE)


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
        import google.oauth2.credentials  # noqa: F401
    except Exception:
        missing.append("google-auth")

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


def is_truthy_config(name: str, default: str = "1") -> bool:
    value = (config_value(name, default) or "").strip().lower()
    return value not in {"0", "false", "no", "off"}


def clean_file_id(value: Optional[str]) -> Optional[str]:
    if not value:
        return None

    value = value.strip()

    if not value or value.startswith("your-"):
        return None

    return value


def library_drive_file_id() -> Optional[str]:
    return clean_file_id(config_value("MAKID_LIBRARY_FILE_ID") or config_value("VITE_LIBRARY_FILE_ID"))


def set_env_file_value(path: Path, key: str, value: str) -> None:
    lines: List[str] = []
    found = False

    if path.exists():
        lines = path.read_text(encoding="utf-8").splitlines()

    for index, line in enumerate(lines):
        stripped = line.strip()

        if stripped and not stripped.startswith("#") and "=" in stripped:
            current_key = stripped.split("=", 1)[0].strip()

            if current_key == key:
                lines[index] = f"{key}={value}"
                found = True

    if not found:
        lines.append(f"{key}={value}")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_library_file_id_to_env_files(file_id: str) -> List[Path]:
    updated: List[Path] = []

    for path in ENV_CONFIG_FILES:
        set_env_file_value(path, "VITE_LIBRARY_FILE_ID", file_id)
        updated.append(path)

    return updated


def previous_lookup_key(row: Dict[str, Any]) -> str:
    return f"{row.get('file_id') or ''}\t{row.get('drive_relative_path') or ''}"


def load_previous_rows_by_lookup_key() -> Dict[str, Dict[str, Any]]:
    if not OUTPUT_JSON.exists():
        return {}

    try:
        payload = json.loads(OUTPUT_JSON.read_text(encoding="utf-8"))
    except Exception:
        return {}

    rows = payload.get("rows")

    if not isinstance(rows, list):
        return {}

    result: Dict[str, Dict[str, Any]] = {}

    for row in rows:
        if isinstance(row, dict):
            key = previous_lookup_key(row)

            if key.strip():
                result[key] = row

    return result


def can_reuse_previous_drive_lookup(row: Dict[str, Any], previous_row: Optional[Dict[str, Any]]) -> bool:
    if not previous_row or not previous_row.get("drive_file_id"):
        return False

    if previous_row.get("drive_lookup_status") != "found":
        return False

    fields_that_must_match = [
        "file_id",
        "file_name",
        "file_ext",
        "drive_relative_path",
        "file_hash",
        "file_last_modified",
        "file_size_bytes",
    ]

    return all(row.get(field) == previous_row.get(field) for field in fields_that_must_match)


def apply_previous_drive_lookup(row: Dict[str, Any], previous_row: Dict[str, Any]) -> None:
    drive_fields = [
        "drive_file_id",
        "drive_lookup_status",
        "drive_name",
        "drive_mime_type",
        "drive_size_bytes",
        "drive_modified_time",
        "drive_md5_checksum",
    ]

    for field in drive_fields:
        row[field] = previous_row.get(field)

    row["drive_lookup_source"] = "cache"


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
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    creds = None

    if GOOGLE_TOKEN_JSON.exists():
        creds = Credentials.from_authorized_user_file(str(GOOGLE_TOKEN_JSON), SCOPES)
    elif LEGACY_GOOGLE_TOKEN_PICKLE.exists():
        print("")
        print("Found legacy Google token pickle.")
        print("For security, pickle tokens are no longer loaded.")
        print("Opening a new Google approval window and replacing it with a private JSON token...")

    if creds and hasattr(creds, "has_scopes") and not creds.has_scopes(SCOPES):
        print("")
        print("Saved Google token is missing the Drive upload permission.")
        print("Opening a new Google approval window...")
        creds = None

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        write_private_text(GOOGLE_TOKEN_JSON, creds.to_json() + "\n")

    if not creds or not creds.valid:
        if not GOOGLE_CREDENTIALS_JSON.exists():
            raise FileNotFoundError(f"Google credentials file not found: {GOOGLE_CREDENTIALS_JSON}")

        ensure_private_file(GOOGLE_CREDENTIALS_JSON)
        flow = InstalledAppFlow.from_client_secrets_file(str(GOOGLE_CREDENTIALS_JSON), SCOPES)
        creds = flow.run_local_server(port=0)
        write_private_text(GOOGLE_TOKEN_JSON, creds.to_json() + "\n")

    if LEGACY_GOOGLE_TOKEN_PICKLE.exists():
        LEGACY_GOOGLE_TOKEN_PICKLE.unlink()
        print(f"Removed legacy Google token pickle: {LEGACY_GOOGLE_TOKEN_PICKLE}")

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


def fill_drive_file_ids(rows: List[Dict[str, Any]], service) -> None:
    print("")
    print("Connecting to Google Drive...")

    resolver = DrivePathResolver(service)
    previous_rows = load_previous_rows_by_lookup_key()
    reuse_cached_lookups = is_truthy_config("MAKID_REUSE_DRIVE_LOOKUPS", "1")

    total = len(rows)
    found = 0
    missing = 0
    cached = 0
    looked_up = 0

    print("Looking up Google Drive file IDs...")
    print("")

    for index, row in enumerate(rows, start=1):
        previous_row = previous_rows.get(previous_lookup_key(row))

        if reuse_cached_lookups and can_reuse_previous_drive_lookup(row, previous_row):
            apply_previous_drive_lookup(row, previous_row)
            found += 1
            cached += 1
            print(f"[{index}/{total}] cached: {row.get('file_name')}")
            continue

        relative_path = row.get("drive_relative_path")

        drive_file_id, status, metadata = resolver.resolve_drive_relative_path(relative_path)

        row["drive_file_id"] = drive_file_id
        row["drive_lookup_status"] = status
        row["drive_lookup_source"] = "api"

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

        looked_up += 1
        print(f"[{index}/{total}] {status}: {row.get('file_name')}")

    print("")
    print(
        f"Drive lookup complete. Found: {found}. Missing: {missing}. "
        f"Cached: {cached}. API lookups: {looked_up}."
    )


def write_json(rows: List[Dict[str, Any]]) -> None:
    payload = {
        "export_version": VERSION,
        "source_db": SOURCE_DB.name,
        "row_count": len(rows),
        "rows": rows,
    }

    write_private_text(OUTPUT_JSON, json.dumps(payload, indent=2, ensure_ascii=False) + "\n")


def copy_to_web_app_folder() -> Optional[Path]:
    if COPY_TO_WEB_APP_FOLDER is None:
        return None

    COPY_TO_WEB_APP_FOLDER.mkdir(parents=True, exist_ok=True)
    destination = COPY_TO_WEB_APP_FOLDER / OUTPUT_JSON.name
    shutil.copy2(OUTPUT_JSON, destination)
    return destination


def split_drive_path(path: Optional[str]) -> Tuple[List[str], str]:
    if not path:
        return [], LIBRARY_DRIVE_FILE_NAME

    parts = [part.strip() for part in path.strip("/").split("/") if part.strip()]

    if not parts:
        return [], LIBRARY_DRIVE_FILE_NAME

    return parts[:-1], parts[-1]


def find_drive_child_folder(service, parent_id: str, folder_name: str) -> Optional[Dict[str, Any]]:
    escaped_name = google_query_escape(folder_name)
    query = (
        f"name = '{escaped_name}' "
        f"and mimeType = 'application/vnd.google-apps.folder' "
        f"and '{parent_id}' in parents "
        f"and trashed = false"
    )

    response = service.files().list(
        q=query,
        spaces="drive",
        fields="files(id, name)",
        pageSize=10,
        supportsAllDrives=True,
        includeItemsFromAllDrives=True,
    ).execute()

    files = response.get("files", [])
    return files[0] if files else None


def ensure_drive_folder_path(service, folder_parts: List[str]) -> str:
    parent_id = "root"

    for folder_name in folder_parts:
        existing_folder = find_drive_child_folder(service, parent_id, folder_name)

        if existing_folder:
            parent_id = existing_folder["id"]
            continue

        metadata = {
            "name": folder_name,
            "mimeType": "application/vnd.google-apps.folder",
            "parents": [parent_id],
        }

        created_folder = service.files().create(
            body=metadata,
            fields="id, name",
            supportsAllDrives=True,
        ).execute()

        parent_id = created_folder["id"]

    return parent_id


def find_drive_file_in_folder(service, parent_id: str, file_name: str) -> Optional[Dict[str, Any]]:
    escaped_name = google_query_escape(file_name)
    query = (
        f"name = '{escaped_name}' "
        f"and '{parent_id}' in parents "
        f"and trashed = false"
    )

    response = service.files().list(
        q=query,
        spaces="drive",
        fields="files(id, name, webViewLink, modifiedTime)",
        pageSize=10,
        supportsAllDrives=True,
        includeItemsFromAllDrives=True,
    ).execute()

    files = response.get("files", [])
    return files[0] if files else None


def library_drive_target(service) -> Tuple[str, str]:
    folder_parts, file_name = split_drive_path(LIBRARY_DRIVE_PATH)

    if folder_parts:
        return ensure_drive_folder_path(service, folder_parts), file_name

    folder_id = clean_file_id(LIBRARY_DRIVE_FOLDER_ID)

    if folder_id:
        return folder_id, file_name

    return "root", file_name


def update_existing_library_json_file(service, file_id: str, media) -> Dict[str, Any]:
    body: Dict[str, Any] = {}
    add_parents = None
    remove_parents = None

    if LIBRARY_DRIVE_PATH or clean_file_id(LIBRARY_DRIVE_FOLDER_ID):
        parent_id, file_name = library_drive_target(service)
        current_file = service.files().get(
            fileId=file_id,
            fields="id, name, parents",
            supportsAllDrives=True,
        ).execute()

        body["name"] = file_name

        current_parents = current_file.get("parents", [])

        if parent_id not in current_parents:
            add_parents = parent_id
            remove_parents = ",".join(current_parents) if current_parents else None

    response = service.files().update(
        fileId=file_id,
        body=body or None,
        media_body=media,
        addParents=add_parents,
        removeParents=remove_parents,
        fields="id, name, webViewLink, modifiedTime",
        supportsAllDrives=True,
    ).execute()

    return response


def upload_library_json_to_drive(service) -> Optional[Dict[str, Any]]:
    if not is_truthy_config("MAKID_UPLOAD_LIBRARY_JSON", "1"):
        return None

    ensure_google_libraries()

    from googleapiclient.errors import HttpError
    from googleapiclient.http import MediaFileUpload

    media = MediaFileUpload(
        str(OUTPUT_JSON),
        mimetype="application/json",
        resumable=False,
    )

    existing_file_id = library_drive_file_id()

    print("")
    print("Publishing private library JSON to Google Drive...")

    if existing_file_id:
        try:
            response = update_existing_library_json_file(service, existing_file_id, media)
        except HttpError as error:
            status = getattr(getattr(error, "resp", None), "status", None)

            if status in {403, 404}:
                raise RuntimeError(
                    "Could not update the configured private library JSON file. "
                    "If that Drive file was created manually, delete VITE_LIBRARY_FILE_ID "
                    "from .env.local and .env.production, then run this publisher again "
                    "so it can create and manage the private JSON file itself."
                ) from error

            raise

        write_library_file_id_to_env_files(response["id"])
        return response

    parent_id, file_name = library_drive_target(service)
    existing_file_at_path = find_drive_file_in_folder(service, parent_id, file_name)

    if existing_file_at_path:
        try:
            response = service.files().update(
                fileId=existing_file_at_path["id"],
                media_body=media,
                fields="id, name, webViewLink, modifiedTime",
                supportsAllDrives=True,
            ).execute()
        except HttpError as error:
            status = getattr(getattr(error, "resp", None), "status", None)

            if status in {403, 404}:
                raise RuntimeError(
                    "Found an existing private library JSON at the configured Drive path, "
                    "but this OAuth app cannot update it. Move or rename that file, then "
                    "run this publisher again so it can create and manage its own file."
                ) from error

            raise

        write_library_file_id_to_env_files(response["id"])
        return response

    metadata: Dict[str, Any] = {
        "name": file_name,
        "mimeType": "application/json",
        "parents": [parent_id],
    }

    response = service.files().create(
        body=metadata,
        media_body=media,
        fields="id, name, webViewLink, modifiedTime",
        supportsAllDrives=True,
    ).execute()

    write_library_file_id_to_env_files(response["id"])
    return response


def main() -> None:
    print(f"MAKID WebAudioFile publisher v{VERSION}")
    print(f"Source database: {SOURCE_DB}")
    print(f"Google credentials: {GOOGLE_CREDENTIALS_JSON}")
    print(f"Google token JSON: {GOOGLE_TOKEN_JSON}")

    secure_local_paths()

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

    service = get_drive_service()

    fill_drive_file_ids(rows, service)
    write_json(rows)

    copied_to = copy_to_web_app_folder()
    uploaded_file = upload_library_json_to_drive(service)

    print("")
    print("Export complete.")
    print(f"Written JSON: {OUTPUT_JSON}")

    if copied_to:
        print(f"Copied to web app folder: {copied_to}")
    else:
        print("Web app copy: skipped")

    if uploaded_file:
        print(f"Google Drive JSON: {uploaded_file.get('name')}")
        print(f"Google Drive file ID: {uploaded_file.get('id')}")
        print(f"Google Drive link: {uploaded_file.get('webViewLink')}")
        print("Updated VITE_LIBRARY_FILE_ID in .env.local and .env.production")
    else:
        print("Google Drive JSON upload: skipped")

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
