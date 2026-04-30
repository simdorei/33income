from pathlib import Path

from income33.agent.browser_control import resolve_browser_debug_port
from income33.agent.login import open_login_browser, open_login_window, resolve_login_url, resolve_profile_dir


def test_resolve_login_url_prefers_payload(monkeypatch):
    monkeypatch.setenv("INCOME33_LOGIN_URL", "https://env.example/login")

    assert resolve_login_url({"login_url": "https://payload.example/login"}) == "https://payload.example/login"


def test_open_login_window_dry_run_uses_bot_profile(tmp_path, monkeypatch):
    monkeypatch.setenv("INCOME33_LOGIN_URL", "https://login.example")
    monkeypatch.setenv("INCOME33_PROFILE_ROOT", str(tmp_path / "profiles"))
    monkeypatch.setenv("INCOME33_LOGIN_DRY_RUN", "1")
    monkeypatch.setenv("INCOME33_BROWSER_DEBUG_PORT_BASE", "30100")

    result = open_login_window(bot_id="sender-01")

    assert result["opened"] is False
    assert result["dry_run"] is True
    assert result["url"] == "https://login.example"
    assert result["profile_dir"] == str(tmp_path / "profiles" / "sender-01")
    assert result["browser"] is None
    assert result["debug_port"] == 30101
    assert Path(result["profile_dir"]).is_dir()


def test_open_login_window_accepts_payload_overrides(tmp_path, monkeypatch):
    monkeypatch.delenv("INCOME33_LOGIN_DRY_RUN", raising=False)
    monkeypatch.setenv("INCOME33_LOGIN_BROWSER_DRY_RUN", "1")
    profile_dir = tmp_path / "custom-profile"

    result = open_login_window(
        bot_id="sender-01",
        payload={"login_url": "https://payload.example", "profile_dir": str(profile_dir)},
    )

    assert result["dry_run"] is True
    assert result["url"] == "https://payload.example"
    assert result["profile_dir"] == str(profile_dir)
    assert profile_dir.is_dir()


def test_open_login_browser_alias_matches_window(tmp_path, monkeypatch):
    monkeypatch.setenv("INCOME33_LOGIN_DRY_RUN", "1")
    monkeypatch.setenv("INCOME33_PROFILE_ROOT", str(tmp_path))

    assert open_login_browser(bot_id="sender-01")["dry_run"] is True


def test_resolve_profile_dir_default_root(tmp_path, monkeypatch):
    monkeypatch.setenv("INCOME33_PROFILE_ROOT", str(tmp_path / "profiles"))

    assert resolve_profile_dir("sender-02") == tmp_path / "profiles" / "sender-02"


def test_debug_port_mapping_with_sender_reporter(monkeypatch):
    monkeypatch.setenv("INCOME33_BROWSER_DEBUG_PORT_BASE", "29200")

    assert resolve_browser_debug_port("sender-09") == 29209
    assert resolve_browser_debug_port("reporter-09") == 29309
