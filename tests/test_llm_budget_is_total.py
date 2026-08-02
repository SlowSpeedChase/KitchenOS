"""The llm_gate budget must bound the whole call, not one attempt of it.

`/prep` was measured at 11.2 s and then at 25.7 s behind an 8 s budget. The
budget was being passed as the Anthropic SDK's `timeout=`, which is a
*per-attempt* value, and the SDK retries timeouts twice by default
(`anthropic._constants.DEFAULT_MAX_RETRIES == 2`). So a page "bounded to 8
seconds" could block for three attempts plus backoff — and it rendered nothing
at all until the ladder finished, because both routes are synchronous.

`create()` does not accept `max_retries`; only the client constructor and
`with_options()` do. So the retry count has to be pinned where the client is
built, which is what these tests pin.
"""

import anthropic
import pytest

from lib import recipe_grid, task_extractor


class TestRetriesAreDisabled:
    """Both AI-on-render paths build a client that will not retry."""

    def test_task_extractor_client_has_no_retries(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        monkeypatch.setattr(task_extractor, "_anthropic_client", None)
        monkeypatch.setattr(task_extractor, "_anthropic_resolved", False)
        client = task_extractor._client()
        assert client is not None
        assert client.max_retries == 0

    def test_recipe_grid_client_has_no_retries(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        client = recipe_grid._build_client()
        assert client is not None
        assert client.max_retries == 0

    def test_sdk_default_is_still_the_thing_we_are_overriding(self):
        """If the SDK ever ships max_retries=0, this override is redundant.

        Pinned so the next reader knows whether the workaround is still load-
        bearing rather than guessing.
        """
        assert anthropic._constants.DEFAULT_MAX_RETRIES == 2

    @pytest.mark.parametrize("build", [
        lambda: recipe_grid._build_client(),
    ])
    def test_no_key_yields_no_client(self, build, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        assert build() is None
