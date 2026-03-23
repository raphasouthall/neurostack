"""Shared fixtures for NeuroStack tests."""

import json
import sqlite3
import textwrap
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def tmp_vault(tmp_path):
    """Create a temporary vault with sample notes."""
    vault = tmp_path / "vault"
    vault.mkdir()

    # Note 1: research note with frontmatter and wiki-links
    (vault / "research").mkdir()
    (vault / "research" / "predictive-coding.md").write_text(textwrap.dedent("""\
        ---
        date: 2026-01-15
        tags: [neuroscience, prediction]
        type: permanent
        status: active
        actionable: true
        ---

        # Predictive Coding

        The brain generates predictions about incoming sensory data.
        When predictions fail, **prediction errors** propagate upward.

        ## Key Principles

        - Hierarchical prediction chains
        - Error-driven learning
        - Bayesian inference in neural circuits

        ## Related

        See [[memory-consolidation]] for how predictions are refined during sleep.
        Also related to [[excitability-windows]].
    """))

    # Note 2: linked note
    (vault / "research" / "memory-consolidation.md").write_text(textwrap.dedent("""\
        ---
        date: 2026-01-20
        tags: [neuroscience, memory]
        type: permanent
        status: active
        actionable: false
        ---

        # Memory Consolidation

        Memory consolidation occurs during sleep through hippocampal replay.

        ## Mechanisms

        - Hippocampal sharp-wave ripples
        - Cortical slow oscillations
        - Spindle-ripple coupling

        This process stabilises [[predictive-coding]] networks.
    """))

    # Note 3: a long note that will be chunked
    long_content = "Some content here.\n" * 200
    (vault / "research" / "long-note.md").write_text(textwrap.dedent(f"""\
        ---
        date: 2026-02-01
        tags: [test]
        type: permanent
        status: reference
        ---

        # Long Note

        {long_content}

        ## Section Two

        More content in section two.

        ## Section Three

        Final section content.
    """))

    # Index file
    (vault / "research" / "index.md").write_text(textwrap.dedent("""\
        # Research Index

        - [[predictive-coding]] — Predictive coding theory
        - [[memory-consolidation]] — Memory consolidation mechanisms
        - [[long-note]] — A long test note
    """))

    return vault


@pytest.fixture
def in_memory_db():
    """Create an in-memory SQLite database with the NeuroStack schema."""
    from neurostack.schema import SCHEMA_SQL, SCHEMA_VERSION

    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA_SQL)
    conn.execute(
        "INSERT OR REPLACE INTO schema_version VALUES (?)", (SCHEMA_VERSION,)
    )
    conn.commit()
    return conn


@pytest.fixture
def populated_db(in_memory_db, tmp_vault):
    """In-memory DB populated with sample notes and chunks."""
    conn = in_memory_db
    now = "2026-01-15T00:00:00+00:00"

    from neurostack.chunker import parse_note

    for md_file in sorted(tmp_vault.rglob("*.md")):
        if md_file.name == "index.md":
            continue
        parsed = parse_note(md_file, tmp_vault)
        fm_json = json.dumps(parsed.frontmatter, default=str)
        conn.execute(
            "INSERT OR REPLACE INTO notes "
            "(path, title, frontmatter, content_hash, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (parsed.path, parsed.title, fm_json, parsed.content_hash, now),
        )
        for chunk in parsed.chunks:
            conn.execute(
                "INSERT INTO chunks "
                "(note_path, heading_path, content, content_hash, position) "
                "VALUES (?, ?, ?, ?, ?)",
                (parsed.path, chunk.heading_path, chunk.content, "test",
                 chunk.position),
            )

    conn.commit()
    return conn


# ---------------------------------------------------------------------------
# Firebase / Firestore test fixtures
# ---------------------------------------------------------------------------

MOCK_FIREBASE_DECODED_TOKEN = {
    "uid": "firebase-user-123",
    "email": "test@example.com",
    "firebase": {
        "sign_in_provider": "google.com",
    },
}


@pytest.fixture
def mock_firebase_admin():
    """Patch firebase_admin.auth.verify_id_token to return a mock decoded token.

    Also patches firebase_admin.initialize_app to avoid real init.
    """
    with (
        patch("firebase_admin.auth.verify_id_token", return_value=MOCK_FIREBASE_DECODED_TOKEN),
        patch("firebase_admin.initialize_app", return_value=MagicMock()),
    ):
        # Reset the singleton so it re-initializes with mock
        import neurostack.cloud.firebase_init as fi
        old_app = fi._app
        fi._app = None
        yield MOCK_FIREBASE_DECODED_TOKEN
        fi._app = old_app


class MockFirestoreDoc:
    """Mock Firestore document snapshot."""

    def __init__(self, data: dict | None, doc_id: str = "doc", parent=None):
        self._data = data
        self.exists = data is not None
        self.id = doc_id
        self.reference = MagicMock()
        self.reference.id = doc_id
        if parent:
            self.reference.parent = MagicMock()
            self.reference.parent.parent = parent

    def to_dict(self):
        return self._data


class MockFirestoreCollection:
    """In-memory mock of a Firestore collection/subcollection.

    Supports document CRUD, auto-generated IDs, subcollections,
    and async streaming.
    """

    _auto_id_counter = 0

    def __init__(
        self, data: dict | None = None, *,
        parent_data: dict | None = None, sub_key: str | None = None,
    ):
        self._data = data or {}  # {doc_id: {field: value}}
        # Track parent so subcollection writes propagate
        self._parent_data = parent_data
        self._sub_key = sub_key

    def _sync_to_parent(self):
        """Write subcollection data back to parent's _sub_X key."""
        if self._parent_data is not None and self._sub_key is not None:
            self._parent_data[self._sub_key] = self._data

    def document(self, doc_id=None):
        if doc_id is None:
            MockFirestoreCollection._auto_id_counter += 1
            doc_id = f"auto-{MockFirestoreCollection._auto_id_counter}"

        col = self  # capture for closures
        doc_ref = MagicMock()
        doc_ref.id = doc_id

        async def _get():
            if doc_id in col._data:
                return MockFirestoreDoc(col._data[doc_id], doc_id=doc_id)
            return MockFirestoreDoc(None, doc_id=doc_id)

        async def _set(data, merge=False):
            if merge and doc_id in col._data:
                col._data[doc_id].update(data)
            else:
                col._data[doc_id] = dict(data)
            col._sync_to_parent()

        async def _update(data):
            if doc_id in col._data:
                col._data[doc_id].update(data)
            else:
                col._data[doc_id] = dict(data)
            col._sync_to_parent()

        async def _delete():
            col._data.pop(doc_id, None)
            col._sync_to_parent()

        doc_ref.get = _get
        doc_ref.set = _set
        doc_ref.update = _update
        doc_ref.delete = _delete
        doc_ref.collection = lambda name: self._get_subcollection(doc_id, name)
        return doc_ref

    def _get_subcollection(self, doc_id, name):
        """Return a subcollection backed by the parent doc's _sub_X dict."""
        if doc_id not in self._data:
            self._data[doc_id] = {}
        parent_doc = self._data[doc_id]
        sub_key = f"_sub_{name}"
        if sub_key not in parent_doc:
            parent_doc[sub_key] = {}
        return MockFirestoreCollection(
            parent_doc[sub_key],
            parent_data=parent_doc,
            sub_key=sub_key,
        )

    def stream(self):
        return self._stream()

    async def _stream(self):
        """Yield all documents in the collection."""
        for doc_id, data in list(self._data.items()):
            if not doc_id.startswith("_sub_"):
                yield MockFirestoreDoc(data, doc_id=doc_id)

    def collection(self, name):
        return MockFirestoreCollection()


class MockFirestoreClient:
    """In-memory mock of google.cloud.firestore_v1.AsyncClient."""

    def __init__(self):
        self._collections = {}  # {name: MockFirestoreCollection}

    def collection(self, name):
        if name not in self._collections:
            self._collections[name] = MockFirestoreCollection()
        return self._collections[name]

    def collection_group(self, name):
        """Mock collection group query."""
        return MockCollectionGroupQuery(self, name)


class MockCollectionGroupQuery:
    """Mock collection group query for api_keys."""

    def __init__(self, client: MockFirestoreClient, collection_name: str):
        self._client = client
        self._collection_name = collection_name
        self._filters = []

    def where(self, field, op, value):
        self._filters.append((field, op, value))
        return self

    def stream(self):
        return self._stream()

    async def _stream(self):
        """Yield matching docs from all subcollections."""
        users_col = self._client._collections.get("users")
        if not users_col:
            return

        for uid, user_data in users_col._data.items():
            sub_key = f"_sub_{self._collection_name}"
            if sub_key not in user_data:
                continue
            sub_data = user_data[sub_key]
            for key_id, key_data in sub_data.items():
                if self._matches(key_data):
                    parent_ref = MagicMock()
                    parent_ref.id = uid
                    parent_mock = MagicMock()
                    parent_mock.parent = parent_ref
                    yield MockFirestoreDoc(
                        key_data,
                        doc_id=key_id,
                        parent=parent_ref,
                    )

    def _matches(self, data: dict) -> bool:
        for field, op, value in self._filters:
            if op == "==":
                if data.get(field) != value:
                    return False
        return True


@pytest.fixture
def mock_firestore():
    """Provide an in-memory MockFirestoreClient and patch the user_store module."""
    client = MockFirestoreClient()

    # Patch the singleton in user_store
    with patch("neurostack.cloud.user_store._db", client):
        # Also patch _get_db to return our mock
        with patch("neurostack.cloud.user_store._get_db", return_value=client):
            yield client
