from tests.fixtures.reviewer_bot_fakes import RouteGitHubApi, github_result


def test_shared_github_fixture_exports_core_transport_helpers():
    routes = RouteGitHubApi()
    result = github_result(200, {"ok": True})

    assert routes is not None
    assert result.ok is True


def test_shared_github_fixture_smoke_routes_simple_request():
    routes = RouteGitHubApi().add_request("GET", "pulls/42", status_code=200, payload={"head": {"sha": "head-1"}})

    result = routes.github_api_request("GET", "pulls/42")

    assert result.payload == {"head": {"sha": "head-1"}}
