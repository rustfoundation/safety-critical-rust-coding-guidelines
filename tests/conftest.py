from types import SimpleNamespace

import pytest

from tests.fixtures import reviewer_bot_recorders
from tests.fixtures.reviewer_bot_env import (
    build_test_lease_context,
    clear_reviewer_bot_env,
)


@pytest.fixture(autouse=True)
def reset_reviewer_bot_process_state_fixture():
    with pytest.MonkeyPatch().context() as monkeypatch:
        clear_reviewer_bot_env(monkeypatch)
        yield


@pytest.fixture
def setenv_many(monkeypatch):
    def setter(values: dict[str, str]):
        for key, value in values.items():
            monkeypatch.setenv(key, value)

    return setter


@pytest.fixture
def lease_context():
    return build_test_lease_context()


@pytest.fixture
def tmp_deferred_path(tmp_path):
    return tmp_path / "deferred-context.json"


@pytest.fixture
def captured_comments():
    return reviewer_bot_recorders.record_comment_dicts(SimpleNamespace())


@pytest.fixture
def captured_status_label_ops():
    return reviewer_bot_recorders.record_status_label_ops(SimpleNamespace())
