"""PDP_KIND: one gate, any AuthZEN 1.0 decision engine. No network here."""

import json
from pathlib import Path

import pytest
import yaml

from canbank_assistant.config import Settings
from canbank_assistant.tools import TOOL_INTENTS
from intent_gate import PdpConfigError, pdp_from_env
from scripts.openfga_setup import demo_tuples

ROOT = Path(__file__).resolve().parents[1]


def test_default_is_the_local_standin_without_auth() -> None:
    cfg = pdp_from_env({})
    assert (cfg.kind, cfg.url, cfg.headers) == ("standin", "http://127.0.0.1:9002", {})


def test_client_key_without_kind_keeps_the_old_behaviour() -> None:
    cfg = pdp_from_env({"AUTHZEN_PDP_URL": "https://eu.api.indykite.com/", "AUTHZEN_PDP_CLIENT_KEY": "k"})
    assert cfg.kind == "indykite"
    assert cfg.url == "https://eu.api.indykite.com"
    assert cfg.headers == {"X-IK-ClientKey": "k"}


def test_indykite_needs_its_client_key() -> None:
    with pytest.raises(PdpConfigError, match="AUTHZEN_PDP_CLIENT_KEY"):
        pdp_from_env({"PDP_KIND": "indykite", "AUTHZEN_PDP_URL": "https://eu.api.indykite.com"})


def test_generic_authzen_sends_no_indykite_header() -> None:
    cfg = pdp_from_env({"PDP_KIND": "authzen", "AUTHZEN_PDP_URL": "http://pdp:8080", "AUTHZEN_PDP_TOKEN": "t"})
    assert cfg.headers == {"Authorization": "Bearer t"}


def test_generic_authzen_refuses_the_indykite_key() -> None:
    with pytest.raises(PdpConfigError, match="IndyKite"):
        pdp_from_env({"PDP_KIND": "authzen", "AUTHZEN_PDP_URL": "http://pdp", "AUTHZEN_PDP_CLIENT_KEY": "k"})


def test_generic_authzen_custom_header() -> None:
    env = {"PDP_KIND": "authzen", "AUTHZEN_PDP_URL": "http://pdp", "AUTHZEN_PDP_HEADER_NAME": "X-Api-Key"}
    with pytest.raises(PdpConfigError, match="both"):
        pdp_from_env(env)
    cfg = pdp_from_env({**env, "AUTHZEN_PDP_HEADER_VALUE": "v"})
    assert cfg.headers == {"X-Api-Key": "v"}


def test_generic_authzen_needs_a_url() -> None:
    with pytest.raises(PdpConfigError, match="AUTHZEN_PDP_URL"):
        pdp_from_env({"PDP_KIND": "authzen"})


def test_openfga_url_is_store_scoped_and_model_pinned() -> None:
    cfg = pdp_from_env(
        {
            "PDP_KIND": "openfga",
            "OPENFGA_API_URL": "http://127.0.0.1:8080/",
            "OPENFGA_STORE_ID": "01STORE",
            "OPENFGA_AUTHORIZATION_MODEL_ID": "01MODEL",
            "OPENFGA_API_TOKEN": "preshared",
        }
    )
    assert cfg.url == "http://127.0.0.1:8080/stores/01STORE"
    assert cfg.headers == {"Openfga-Authorization-Model-Id": "01MODEL", "Authorization": "Bearer preshared"}
    assert "preshared" not in cfg.describe()


@pytest.mark.parametrize("missing", ["OPENFGA_API_URL", "OPENFGA_STORE_ID"])
def test_openfga_needs_url_and_store(missing: str) -> None:
    env = {"PDP_KIND": "openfga", "OPENFGA_API_URL": "http://f", "OPENFGA_STORE_ID": "s"}
    del env[missing]
    with pytest.raises(PdpConfigError, match=missing):
        pdp_from_env(env)


def test_unknown_kind_and_bad_url_are_refused() -> None:
    with pytest.raises(PdpConfigError, match="PDP_KIND"):
        pdp_from_env({"PDP_KIND": "magic"})
    with pytest.raises(PdpConfigError, match="http"):
        pdp_from_env({"PDP_KIND": "authzen", "AUTHZEN_PDP_URL": "ftp://pdp"})


def test_settings_carry_the_pdp(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PDP_KIND", "openfga")
    monkeypatch.setenv("OPENFGA_API_URL", "http://127.0.0.1:8080")
    monkeypatch.setenv("OPENFGA_STORE_ID", "01STORE")
    monkeypatch.delenv("MODEL_PROVIDER_TYPE", raising=False)
    assert Settings.from_env().pdp.url == "http://127.0.0.1:8080/stores/01STORE"


def test_openfga_model_has_every_action_the_tools_need() -> None:
    model = json.loads((ROOT / "pdp" / "openfga" / "model.json").read_text())
    relations = {t["type"]: set(t.get("relations", {})) for t in model["type_definitions"]}
    for spec in TOOL_INTENTS.values():
        for rtype in spec.resources.values():
            assert spec.actions & relations[rtype], (rtype, spec.actions)


def test_openfga_store_file_tuples_match_the_demo_graph() -> None:
    store = yaml.safe_load((ROOT / "pdp" / "openfga" / "store.fga.yaml").read_text())
    key = lambda t: (t["user"], t["relation"], t["object"])  # noqa: E731
    assert sorted(map(key, store["tuples"])) == sorted(map(key, demo_tuples()))
