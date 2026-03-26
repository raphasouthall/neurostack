"""Tests for neurostack.cloud.timer — systemd user timer for periodic cloud sync."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from neurostack.cloud.timer import (
    SERVICE_NAME,
    install_timer,
    timer_status,
    uninstall_timer,
)


@pytest.fixture(autouse=True)
def _isolate(tmp_path):
    """Redirect systemd dir to tmp_path and stub subprocess + path lookup."""
    with (
        patch("neurostack.cloud.timer._systemd_user_dir", return_value=tmp_path),
        patch("neurostack.cloud.timer._find_neurostack_path", return_value="/usr/bin/neurostack"),
        patch("neurostack.cloud.timer.subprocess") as mock_sub,
    ):
        mock_sub.run = MagicMock()
        yield tmp_path, mock_sub


def test_install_timer_creates_service_file(_isolate):
    tmp_path, _ = _isolate
    result = install_timer(interval="10min")
    service_path = tmp_path / f"{SERVICE_NAME}.service"
    assert service_path.exists()
    content = service_path.read_text()
    assert "ExecStart=/usr/bin/neurostack cloud sync --quiet" in content
    assert result["service_path"] == str(service_path)


def test_install_timer_creates_timer_file(_isolate):
    tmp_path, _ = _isolate
    result = install_timer(interval="10min")
    timer_path = tmp_path / f"{SERVICE_NAME}.timer"
    assert timer_path.exists()
    content = timer_path.read_text()
    assert "OnBootSec=5min" in content
    assert result["timer_path"] == str(timer_path)


def test_timer_file_has_correct_interval(_isolate):
    tmp_path, _ = _isolate
    install_timer(interval="30min")
    timer_path = tmp_path / f"{SERVICE_NAME}.timer"
    content = timer_path.read_text()
    assert "OnUnitActiveSec=30min" in content


def test_uninstall_timer_removes_files(_isolate):
    tmp_path, _ = _isolate
    install_timer(interval="15min")
    service_path = tmp_path / f"{SERVICE_NAME}.service"
    timer_path = tmp_path / f"{SERVICE_NAME}.timer"
    assert service_path.exists()
    assert timer_path.exists()

    result = uninstall_timer()
    assert result["removed"] is True
    assert not service_path.exists()
    assert not timer_path.exists()
    assert len(result["paths"]) == 2


def test_timer_status_not_installed(_isolate):
    status = timer_status()
    assert status["installed"] is False
    assert status["active"] is False
    assert status["interval"] is None
    assert status["next_run"] is None


def test_timer_status_installed(_isolate):
    tmp_path, mock_sub = _isolate
    install_timer(interval="20min")

    # Make is-active return non-zero (inactive but installed)
    inactive_result = MagicMock()
    inactive_result.returncode = 1
    mock_sub.run.return_value = inactive_result

    status = timer_status()
    assert status["installed"] is True
    assert status["interval"] == "20min"
    assert status["active"] is False
