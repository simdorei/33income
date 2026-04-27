from income33.agent.client import ControlTowerClient


def test_control_tower_client_uses_http_timeout_env(monkeypatch):
    monkeypatch.setenv("INCOME33_HTTP_TIMEOUT_SECONDS", "23")
    client = ControlTowerClient(base_url="http://127.0.0.1:8330")
    assert client.timeout == 23


def test_control_tower_client_invalid_http_timeout_env_falls_back_default(monkeypatch):
    monkeypatch.setenv("INCOME33_HTTP_TIMEOUT_SECONDS", "not-an-int")
    client = ControlTowerClient(base_url="http://127.0.0.1:8330")
    assert client.timeout == 10
