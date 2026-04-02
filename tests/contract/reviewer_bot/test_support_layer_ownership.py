from pathlib import Path

import pytest

from tests.fixtures import reviewer_bot_env, reviewer_bot_recorders

pytestmark = pytest.mark.contract


ROOT = Path(__file__).resolve().parents[3]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_support_layer_has_owned_env_and_recorder_modules():
    assert reviewer_bot_env is not None
    assert reviewer_bot_recorders is not None


def test_harnesses_do_not_define_local_config_bags_or_deferred_payload_loaders():
    for relative_path in [
        "tests/fixtures/app_harness.py",
        "tests/fixtures/commands_harness.py",
        "tests/fixtures/comment_routing_harness.py",
        "tests/fixtures/reconcile_harness.py",
    ]:
        text = _read(relative_path)
        assert "class _ConfigBag" not in text
        assert "class _DeferredPayloads" not in text


def test_harnesses_use_owned_env_and_recorder_homes():
    app_harness = _read("tests/fixtures/app_harness.py")
    commands_harness = _read("tests/fixtures/commands_harness.py")
    comment_harness = _read("tests/fixtures/comment_routing_harness.py")
    conftest = _read("tests/conftest.py")

    assert "from .reviewer_bot_env import" in app_harness or "reviewer_bot_env" in app_harness
    assert "from .reviewer_bot_env import" in commands_harness or "reviewer_bot_env" in commands_harness
    assert "from .reviewer_bot_env import" in comment_harness or "reviewer_bot_env" in comment_harness
    assert "reviewer_bot_env" in conftest
    assert "reviewer_bot_recorders" in commands_harness
    assert "reviewer_bot_recorders" in comment_harness
    assert "reviewer_bot_recorders" in conftest


def test_no_second_fake_runtime_or_transport_home_exists():
    fixtures_dir = ROOT / "tests/fixtures"
    fixture_files = {path.name for path in fixtures_dir.glob("*.py")}

    assert "fake_runtime.py" in fixture_files
    assert "reviewer_bot_fakes.py" in fixture_files
    assert "commands_harness.py" in fixture_files
    assert "comment_routing_harness.py" in fixture_files
    assert "reconcile_harness.py" in fixture_files
