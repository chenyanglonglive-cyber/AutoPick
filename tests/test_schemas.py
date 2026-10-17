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


def test_gallery_import_request_accepts_file_paths_or_gallery_path():
    from backend.autopick.schemas import GalleryImportRequest

    req1 = GalleryImportRequest(gallery_path="C:\\test")
    assert req1.gallery_path == "C:\\test"
    assert req1.file_paths is None

    req2 = GalleryImportRequest(file_paths=["C:\\img1.jpg", "C:\\img2.jpg"])
    assert req2.file_paths == ["C:\\img1.jpg", "C:\\img2.jpg"]
    assert req2.gallery_path is None
