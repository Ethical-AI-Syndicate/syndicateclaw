from __future__ import annotations

import tests.conftest as root_conftest


def test_db_engine_fixture_is_not_autouse() -> None:
    fixture = root_conftest.db_engine
    marker = fixture._pytestfixturefunction or fixture._fixture_function_marker
    assert marker.autouse is False
