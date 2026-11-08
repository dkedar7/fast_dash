"""fastdash create scaffolds (#333: --backend fastapi for streaming apps)."""

import sys

import pytest

from fast_dash import cli


def _create(monkeypatch, tmp_path, *extra):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["fastdash", "create", "my-app", "--port", "8080", *extra])
    assert cli.main() == 0
    d = tmp_path / "my-app"
    return {f: (d / f).read_text() for f in ("Dockerfile", "requirements.txt", "app.py")}


def test_default_scaffold_is_flask_with_gunicorn(monkeypatch, tmp_path):
    files = _create(monkeypatch, tmp_path)
    assert "CMD gunicorn app:server --bind :${PORT:-8080}" in files["Dockerfile"]
    assert files["requirements.txt"].split() == ["fast-dash", "gunicorn"]
    assert "backend=" not in files["app.py"]


def test_fastapi_scaffold_serves_with_uvicorn(monkeypatch, tmp_path):
    files = _create(monkeypatch, tmp_path, "--backend", "fastapi")
    assert "CMD uvicorn app:server --host 0.0.0.0 --port ${PORT:-8080}" in files["Dockerfile"]
    assert files["requirements.txt"].split() == ["fast-dash[fastapi]"]
    assert 'FastDash(simple_text_to_text, port=8080, backend="fastapi")' in files["app.py"]
    compile(files["app.py"], "app.py", "exec")


def test_unknown_backend_is_rejected(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["fastdash", "create", "x", "--port", "1", "--backend", "quart"])
    with pytest.raises(SystemExit):
        cli.main()
