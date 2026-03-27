from __future__ import annotations

import pytest
from jinja2.exceptions import SecurityError, UndefinedError

from syndicateclaw.llm.templates import render_message_template


def test_llm_handler_message_templating() -> None:
    rendered = render_message_template(
        "Hello {{ state.user }}",
        {"state": {"user": "alice"}},
    )
    assert rendered == "Hello alice"


def test_llm_handler_undefined_var_raises() -> None:
    with pytest.raises(UndefinedError):
        render_message_template("Hello {{ state.missing }}", {"state": {}})


def test_llm_handler_sandbox_blocks_import() -> None:
    payload = "{{ cycler.__init__.__globals__.os.system('id') }}"
    with pytest.raises(SecurityError):
        render_message_template(payload, {"state": {}})
