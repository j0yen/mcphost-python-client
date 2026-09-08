from __future__ import annotations

from collections.abc import Iterator

import pytest
from fakeserver import FakeMcpHost


@pytest.fixture
def fake_host() -> Iterator[FakeMcpHost]:
    with FakeMcpHost() as host:
        yield host
