import pytest

from tests.fixtures import http_responses, reviewer_bot_fakes, reviewer_bot_recorders
from tests.fixtures.focused_fake_services import (
    ArtifactDownloadTransportStub,
    ConfigBag,
    DeferredPayloadStore,
    GitHubStub,
    GraphQLTransportStub,
    HandlerStub,
    LockStub,
    OutputCapture,
    RestTransportStub,
    StateStoreStub,
    TouchTrackerStub,
)
from tests.fixtures.reviewer_bot_fakes import RouteGitHubApi, github_result

pytestmark = pytest.mark.contract


def test_transport_fake_authority_is_owned_by_reviewer_bot_fakes_module():
    assert reviewer_bot_fakes.RouteGitHubApi is RouteGitHubApi
    assert reviewer_bot_fakes.github_result is github_result


def test_low_level_http_response_helper_has_dedicated_home():
    assert http_responses.FakeGitHubResponse is not None
    assert http_responses.__all__ == ["FakeGitHubResponse"]


def test_reviewer_bot_recorders_module_remains_available_for_shared_recorders():
    assert reviewer_bot_recorders is not None


def test_focused_fake_service_module_is_authority_for_small_fixture_services():
    expected = {
        "ConfigBag": ConfigBag,
        "OutputCapture": OutputCapture,
        "DeferredPayloadStore": DeferredPayloadStore,
        "StateStoreStub": StateStoreStub,
        "LockStub": LockStub,
        "GitHubStub": GitHubStub,
        "RestTransportStub": RestTransportStub,
        "GraphQLTransportStub": GraphQLTransportStub,
        "ArtifactDownloadTransportStub": ArtifactDownloadTransportStub,
        "HandlerStub": HandlerStub,
        "TouchTrackerStub": TouchTrackerStub,
    }

    for name, obj in expected.items():
        assert obj.__name__ == name
        assert obj.__module__ == "tests.fixtures.focused_fake_services"


def test_support_layer_contract_focuses_on_active_authority_boundaries_only():
    active_authorities = {
        RouteGitHubApi.__module__,
        github_result.__module__,
        http_responses.FakeGitHubResponse.__module__,
        ConfigBag.__module__,
        reviewer_bot_recorders.__name__,
    }

    assert active_authorities == {
        "tests.fixtures.reviewer_bot_fakes",
        "tests.fixtures.http_responses",
        "tests.fixtures.focused_fake_services",
        "tests.fixtures.reviewer_bot_recorders",
    }
