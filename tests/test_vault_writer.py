"""Tests for vault write-back."""

import hashlib
import os

import pytest

from neurostack.memories import Memory
from neurostack.vault_writer import VaultWriter


def _make_memory(**kwargs):
    defaults = dict(
        memory_id=1,
        content="Test memory content for unit testing",
        tags=["test", "unit"],
        entity_type="decision",
        source_agent="test-agent",
        workspace=None,
        created_at="2026-03-16 09:00:00",
        expires_at=None,
        uuid="a3f9c2e1-4b7d-4321-abcd-1234567890ab",
    )
    defaults.update(kwargs)
    return Memory(**defaults)


def _vault_root(tmp_path):
    """Return a vault root with 3+ path components."""
    root = tmp_path / "test" / "vault"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _writer(tmp_path):
    """Create a VaultWriter with explicit writeback path inside tmp_path."""
    root = _vault_root(tmp_path)
    wb_path = tmp_path / "neurostack" / "memories"
    wb_path.mkdir(parents=True, exist_ok=True)
    return VaultWriter(root, writeback_path=str(wb_path)), root, wb_path


class TestVaultWriterWrite:
    def test_write_creates_file(self, tmp_path):
        writer, root, wb = _writer(tmp_path)
        mem = _make_memory()
        path = writer.write(mem)
        assert path is not None
        assert path.exists()

    def test_write_path_structure(self, tmp_path):
        writer, root, wb = _writer(tmp_path)
        mem = _make_memory(
            entity_type="decision",
            created_at="2026-03-16 09:00:00",
            memory_id=42,
        )
        path = writer.write(mem)
        assert path is not None
        # Expected: {wb}/decision/2026-03/{uuid}.md
        rel = path.relative_to(wb)
        parts = rel.parts
        assert parts[0] == "decision"
        assert parts[1] == "2026-03"
        assert parts[2] == "a3f9c2e1-4b7d-4321-abcd-1234567890ab.md"

    def test_write_frontmatter(self, tmp_path):
        writer, root, wb = _writer(tmp_path)
        mem = _make_memory(
            memory_id=7,
            tags=["alpha", "beta"],
            workspace="work/project",
            source_agent="claude",
        )
        path = writer.write(mem)
        assert path is not None
        text = path.read_text(encoding="utf-8")
        assert text.startswith("---\n")
        # All required frontmatter fields present
        for field in (
            "title:",
            "neurostack_id:",
            "entity_type:",
            "tags:",
            "workspace:",
            "source_agent:",
            "created_at:",
            "updated_at:",
            "neurostack_hash:",
        ):
            assert field in text, (
                f"Missing frontmatter field: {field}"
            )
        # Verify specific values
        assert "neurostack_id: a3f9c2e1-4b7d-4321-abcd" in text
        assert "entity_type: decision" in text
        assert "[alpha, beta]" in text
        assert '"work/project"' in text
        assert '"claude"' in text

    def test_write_content_body(self, tmp_path):
        writer, root, wb = _writer(tmp_path)
        content = "This is the actual memory body text."
        mem = _make_memory(content=content)
        path = writer.write(mem)
        assert path is not None
        text = path.read_text(encoding="utf-8")
        # Content appears after the closing ---
        parts = text.split("---")
        # parts[0] is empty, parts[1] is frontmatter, parts[2] is body
        body = parts[2].strip()
        assert body == content

    def test_write_content_hash(self, tmp_path):
        writer, root, wb = _writer(tmp_path)
        content = "Hash me please"
        mem = _make_memory(content=content)
        path = writer.write(mem)
        assert path is not None
        text = path.read_text(encoding="utf-8")
        expected_digest = hashlib.sha256(
            content.encode("utf-8"),
        ).hexdigest()
        expected_hash = f"sha256:{expected_digest}"
        assert expected_hash in text

    def test_write_returns_path(self, tmp_path):
        writer, root, wb = _writer(tmp_path)
        mem = _make_memory()
        result = writer.write(mem)
        from pathlib import Path
        assert isinstance(result, Path)

    @pytest.mark.skipif(
        os.getuid() == 0, reason="chmod restrictions don't apply to root",
    )
    def test_write_none_on_failure(self, tmp_path):
        writer, root, wb = _writer(tmp_path)
        mem = _make_memory()
        # Make the memories dir read-only so write fails
        os.chmod(wb, 0o444)
        try:
            result = writer.write(mem)
            assert result is None
        finally:
            # Restore permissions for cleanup
            os.chmod(wb, 0o755)

    def test_default_writes_outside_vault(self, tmp_path):
        """Default VaultWriter should NOT write inside vault_root."""
        root = _vault_root(tmp_path)
        writer = VaultWriter(root)
        # Default memories_dir should be ~/.local/share/neurostack/memories
        assert "neurostack" in str(writer.memories_dir)
        assert str(root) not in str(writer.memories_dir)


class TestVaultWriterDelete:
    def test_delete_removes_file(self, tmp_path):
        writer, root, wb = _writer(tmp_path)
        mem = _make_memory()
        path = writer.write(mem)
        assert path is not None
        assert path.exists()
        result = writer.delete(mem)
        assert result is True
        assert not path.exists()

    def test_delete_nonexistent(self, tmp_path):
        writer, root, wb = _writer(tmp_path)
        mem = _make_memory(memory_id=999)
        result = writer.delete(mem)
        assert result is False


class TestVaultWriterOverwrite:
    def test_overwrite_updates_file(self, tmp_path):
        writer, root, wb = _writer(tmp_path)
        mem = _make_memory(content="Original content")
        path = writer.write(mem)
        assert path is not None
        # Update content and overwrite
        mem_updated = _make_memory(content="Updated content")
        path2 = writer.overwrite(mem_updated)
        assert path2 is not None
        assert path2 == path
        text = path.read_text(encoding="utf-8")
        assert "Updated content" in text
        assert "Original content" not in text
        # Hash should reflect new content
        new_digest = hashlib.sha256(
            "Updated content".encode("utf-8"),
        ).hexdigest()
        assert f"sha256:{new_digest}" in text


class TestVaultWriterContainment:
    def test_containment_check(self, tmp_path):
        writer, root, wb = _writer(tmp_path)
        # Create a path outside the memories dir
        outside = tmp_path / "outside"
        outside.mkdir()
        bad_path = outside / "evil.md"
        assert writer._check_containment(bad_path) is False


class TestVaultRootValidation:
    def test_memories_dir_too_shallow(self):
        with pytest.raises(ValueError, match="too shallow"):
            VaultWriter(
                vault_root=__import__("pathlib").Path("/tmp"),
                writeback_path="/x",
            )

    def test_vault_root_valid(self, tmp_path):
        root = tmp_path / "a" / "b"
        root.mkdir(parents=True)
        wb = tmp_path / "wb" / "memories"
        wb.mkdir(parents=True)
        writer = VaultWriter(root, writeback_path=str(wb))
        assert writer.vault_root == root.resolve()


class TestMkdirCaching:
    def test_mkdir_caching(self, tmp_path):
        writer, root, wb = _writer(tmp_path)
        mem1 = _make_memory(
            memory_id=1,
            entity_type="decision",
            created_at="2026-03-16 09:00:00",
        )
        mem2 = _make_memory(
            memory_id=2,
            entity_type="decision",
            created_at="2026-03-16 10:00:00",
        )
        writer.write(mem1)
        writer.write(mem2)
        # Both share the same dir: decision/2026-03
        # The _created_dirs set should contain that dir exactly once
        decision_dirs = [
            d for d in writer._created_dirs
            if "decision" in d and "2026-03" in d
        ]
        assert len(decision_dirs) == 1
