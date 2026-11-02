import tempfile

from app import memory


def test_temp_files_go_to_disk(tmp_path, monkeypatch):
    monkeypatch.setattr(tempfile, "tempdir", None)
    monkeypatch.delenv("TMPDIR", raising=False)
    memory.disk_temp_dir(str(tmp_path))
    assert tempfile.gettempdir() == str(tmp_path)

    monkeypatch.setattr(tempfile, "tempdir", None)
    monkeypatch.setenv("TMPDIR", "/somewhere/else")
    memory.disk_temp_dir(str(tmp_path))  # an explicit TMPDIR wins
    assert tempfile.tempdir is None

    memory.disk_temp_dir(str(tmp_path / "missing"))
    assert tempfile.tempdir is None


def test_allocator_helpers_are_safe():
    memory.limit_arenas()
    memory.release_free_memory()
