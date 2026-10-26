"""
Test unitari per lo script di bump automatico della versione (.dev_workflow/bump_version.py).
Autore: Paolo Basta (https://github.com/Il-Basta-Paolo/BardoAI)
"""

import sys
from pathlib import Path
import pytest

DEV_WORKFLOW_DIR = Path(__file__).resolve().parent.parent / ".dev_workflow"
sys.path.insert(0, str(DEV_WORKFLOW_DIR))

from bump_version import (  # noqa: E402
    parse_semver,
    compute_bumped_version,
    update_file_regex,
    apply_version_bump,
)


def test_parse_semver_valid():
    assert parse_semver("2.6.2") == (2, 6, 2)
    assert parse_semver("3.0.0") == (3, 0, 0)
    assert parse_semver("0.1.15") == (0, 1, 15)


def test_parse_semver_invalid():
    with pytest.raises(ValueError):
        parse_semver("2.6")
    with pytest.raises(ValueError):
        parse_semver("v2.6.2")
    with pytest.raises(ValueError):
        parse_semver("2.6.2.1")
    with pytest.raises(ValueError):
        parse_semver("invalid-semver")


def test_compute_bumped_version():
    assert compute_bumped_version("2.6.2", "patch") == "2.6.3"
    assert compute_bumped_version("2.6.2", "minor") == "2.7.0"
    assert compute_bumped_version("2.6.2", "major") == "3.0.0"

    with pytest.raises(ValueError):
        compute_bumped_version("2.6.2", "unknown_type")


def test_update_file_regex_dry_run(tmp_path):
    test_file = tmp_path / "sample.py"
    test_file.write_text('APP_VERSION = "2.6.2"', encoding="utf-8")

    # In dry-run il file non deve cambiare
    ok = update_file_regex(test_file, r'APP_VERSION\s*=\s*"[^"]+"', 'APP_VERSION = "2.7.0"', dry_run=True)
    assert ok is True
    assert test_file.read_text(encoding="utf-8") == 'APP_VERSION = "2.6.2"'

    # Senza dry-run viene modificato
    ok = update_file_regex(test_file, r'APP_VERSION\s*=\s*"[^"]+"', 'APP_VERSION = "2.7.0"', dry_run=False)
    assert ok is True
    assert test_file.read_text(encoding="utf-8") == 'APP_VERSION = "2.7.0"'


def test_apply_version_bump_temp_tree(tmp_path):
    # 1. Crea file mock
    (tmp_path / "config_defaults.py").write_text('APP_VERSION = "2.6.2"\n# Bardo AI v2.6.2', encoding="utf-8")
    (tmp_path / "desktop_app.py").write_text('__version__ = "2.6.2"\n# Bardo AI v2.6.2', encoding="utf-8")
    (tmp_path / "installer_gui.py").write_text('APP_VERSION = "2.6.2"', encoding="utf-8")
    (tmp_path / "version_bardo.txt").write_text(
        "filevers=(2, 6, 2, 0)\nprodvers=(2, 6, 2, 0)\nStringStruct('FileVersion', '2.6.2.0')\nStringStruct('ProductVersion', '2.6.2.0')",
        encoding="utf-8",
    )
    (tmp_path / "version_setup.txt").write_text(
        "filevers=(2, 6, 2, 0)\nprodvers=(2, 6, 2, 0)\nStringStruct('FileVersion', '2.6.2.0')\nStringStruct('ProductVersion', '2.6.2.0')",
        encoding="utf-8",
    )
    (tmp_path / "build_installer.py").write_text("BARDO AI v2.6.2\nBardo AI v2.6.2", encoding="utf-8")
    (tmp_path / "requirements.txt").write_text("# Bardo AI Dependencies (v2.6.2)", encoding="utf-8")
    (tmp_path / "README.md").write_text(
        '# Bardo AI (v2.6)\n[![Changelog](https://img.shields.io/badge/Changelog-v2.6.2-blue)](CHANGELOG.md)\nalt="Interfaccia Desktop di Bardo AI v2.6.2"\n## Novità dell\'ultima versione (v2.6.2)',
        encoding="utf-8",
    )
    (tmp_path / "CHANGELOG.md").write_text("# Changelog — Bardo AI\n\n## [2.6.2] — 2026-10-24\n", encoding="utf-8")

    results = apply_version_bump("2.7.0", tmp_path, dry_run=False)
    assert all(results.values()) is True

    # Verifiche puntuali
    assert 'APP_VERSION = "2.7.0"' in (tmp_path / "config_defaults.py").read_text(encoding="utf-8")
    assert 'APP_VERSION = "2.7.0"' in (tmp_path / "installer_gui.py").read_text(encoding="utf-8")
    assert 'filevers=(2, 7, 0, 0)' in (tmp_path / "version_bardo.txt").read_text(encoding="utf-8")
    assert "'ProductVersion', '2.7.0.0'" in (tmp_path / "version_bardo.txt").read_text(encoding="utf-8")
    assert "# Bardo AI (v2.7)" in (tmp_path / "README.md").read_text(encoding="utf-8")
    assert "badge/Changelog-v2.7.0-blue" in (tmp_path / "README.md").read_text(encoding="utf-8")
    assert "## Novità dell'ultima versione (v2.7.0)" in (tmp_path / "README.md").read_text(encoding="utf-8")
    assert "## [2.7.0] —" in (tmp_path / "CHANGELOG.md").read_text(encoding="utf-8")
