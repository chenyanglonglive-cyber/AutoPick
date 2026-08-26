from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.autopick.schemas import SearchRequest


def test_gallery_search_result_limit_is_supported():
    request = SearchRequest(query="红色纸片", top_k=120)

    assert request.top_k == 120


def test_search_result_limit_remains_bounded():
    with pytest.raises(ValidationError):
        SearchRequest(query="红色纸片", top_k=201)
