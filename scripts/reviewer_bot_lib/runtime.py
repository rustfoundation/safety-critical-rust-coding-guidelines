"""Concrete runtime object for reviewer-bot orchestration."""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import ModuleType
from typing import Any


class _ModuleConfig:
    def get(self, name: str, default: str = "") -> str:
        return os.environ.get(name, default)

    def set(self, name: str, value: Any) -> None:
        os.environ[name] = str(value)


class _ModuleOutputSink:
    def __init__(self, config: _ModuleConfig):
        self._config = config

    def write(self, name: str, value: str) -> None:
        output_path = self._config.get("GITHUB_OUTPUT", "/dev/null")
        with open(output_path, "a", encoding="utf-8") as output_file:
            output_file.write(f"{name}={value}\n")


class _ModuleDeferredPayloadLoader:
    def __init__(self, config: _ModuleConfig):
        self._config = config

    def load(self) -> dict:
        path = self._config.get("DEFERRED_CONTEXT_PATH", "").strip()
        if not path:
            raise RuntimeError("Missing DEFERRED_CONTEXT_PATH for workflow_run reconcile")
        with open(Path(path), encoding="utf-8") as handle:
            payload = json.load(handle)
        if not isinstance(payload, dict):
            raise RuntimeError("Deferred context payload must be a JSON object")
        return payload


class _ModuleStateStore:
    def __init__(self, module: ModuleType):
        self._module = module

    def load_state(self, *, fail_on_unavailable: bool = False) -> dict:
        return self._module.load_state(fail_on_unavailable=fail_on_unavailable)

    def save_state(self, state: dict) -> bool:
        return self._module.save_state(state)


class _ModuleGitHubTransport:
    def __init__(self, module: ModuleType):
        self._module = module

    def github_api_request(self, *args, **kwargs):
        return self._module.github_api_request(*args, **kwargs)

    def github_api(self, *args, **kwargs):
        return self._module.github_api(*args, **kwargs)


class ReviewerBotRuntime:
    """Runtime service host with adapter-compatible fallbacks."""

    def __init__(
        self,
        module: ModuleType,
        *,
        config: Any | None = None,
        outputs: Any | None = None,
        deferred_payloads: Any | None = None,
        state_store: Any | None = None,
        github: Any | None = None,
    ):
        object.__setattr__(self, "_module", module)
        config_service = config or _ModuleConfig()
        object.__setattr__(self, "_config", config_service)
        object.__setattr__(self, "_outputs", outputs or _ModuleOutputSink(config_service))
        object.__setattr__(
            self,
            "_deferred_payloads",
            deferred_payloads or _ModuleDeferredPayloadLoader(config_service),
        )
        object.__setattr__(self, "_state_store", state_store or _ModuleStateStore(module))
        object.__setattr__(self, "_github", github or _ModuleGitHubTransport(module))

    def __getattr__(self, name: str) -> Any:
        return getattr(self._module, name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name.startswith("_"):
            object.__setattr__(self, name, value)
            return
        setattr(self._module, name, value)

    def get_config_value(self, name: str, default: str = "") -> str:
        return self._config.get(name, default)

    def set_config_value(self, name: str, value: Any) -> None:
        self._config.set(name, value)

    def write_output(self, name: str, value: str) -> None:
        self._outputs.write(name, value)

    def load_deferred_payload(self) -> dict:
        return self._deferred_payloads.load()

    def load_state(self, *, fail_on_unavailable: bool = False) -> dict:
        return self._state_store.load_state(fail_on_unavailable=fail_on_unavailable)

    def save_state(self, state: dict) -> bool:
        return self._state_store.save_state(state)

    def github_api_request(self, *args, **kwargs):
        return self._github.github_api_request(*args, **kwargs)

    def github_api(self, *args, **kwargs):
        return self._github.github_api(*args, **kwargs)
