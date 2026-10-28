"""Tests for the Swagger/OpenAPI documentation endpoints."""

import pytest
import requests


@pytest.mark.api
class TestApiDocs:
    """Guard against malformed route docstrings breaking the Swagger UI (#193, #389, #547)."""

    def test_apispec_builds(self, api_client):
        """The generated spec should load, so every route docstring's YAML must parse."""
        response = requests.get(f"{api_client}/api/apispec.json", timeout=10)
        assert response.status_code == 200, (
            "apispec.json failed to build; check route docstrings for malformed Swagger YAML"
        )

        data = response.json()
        assert data["paths"]

    def test_apispec_includes_documented_parameters(self, api_client):
        """Parameters from a documented route should appear in the generated spec."""
        response = requests.get(f"{api_client}/api/apispec.json", timeout=10)
        assert response.status_code == 200

        operation = response.json()["paths"]["/api/boards/{board_id}/cards/scheduled"]["get"]
        names = {param["name"] for param in operation["parameters"]}
        assert {"board_id", "include_owner_candidates", "q"} <= names

    def test_docs_ui_loads(self, api_client):
        """The Swagger UI page should be served."""
        response = requests.get(f"{api_client}/api/docs", timeout=10)
        assert response.status_code == 200
