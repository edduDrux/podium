"""O contrato documentado no OpenAPI, que é contra o que o cliente Unity é escrito."""

import pytest

from app.api.errors import STATUS_BY_ERROR
from app.domain import errors
from app.domain.errors import DomainError
from app.main import app

PREFIX = "/api/v1/presentations"


@pytest.fixture(scope="module")
def schema() -> dict:
    return app.openapi()


def _responses(schema: dict, path: str, method: str) -> dict:
    return schema["paths"][f"{PREFIX}{path}"][method]["responses"]


def test_every_domain_error_has_a_status():
    """Erro de domínio fora da tabela viraria 500 em vez da recusa prevista."""
    domain_errors = {
        cls
        for cls in vars(errors).values()
        if isinstance(cls, type) and issubclass(cls, DomainError) and cls is not DomainError
    }
    assert domain_errors == set(STATUS_BY_ERROR)


def test_init_documents_each_refusal(schema):
    responses = _responses(schema, "/init", "post")

    assert {"201", "404", "409", "413", "415", "422"} <= set(responses)
    assert "Apenas" not in responses["415"]["description"]  # motivo vem da docstring
    assert "PDF nem PPTx" in responses["415"]["description"]
    # O /init não recebe sessão: o 404 e o 409 dele são só os do código de pareamento.
    assert "sessão não existe" not in responses["404"]["description"]
    assert "pareamento" in responses["404"]["description"]
    assert "pareamento" in responses["409"]["description"]


def test_analyze_documents_both_modes_refusals(schema):
    conflict = _responses(schema, "/{session_id}/analyze", "post")["409"]["description"]

    assert "análise completa" in conflict
    assert "análise básica" in conflict


def test_slide_page_documents_both_not_founds(schema):
    """O 404 da imagem pode ser a sessão ou a página: os dois motivos aparecem."""
    not_found = _responses(schema, "/{session_id}/slides/{number}", "get")["404"]["description"]

    assert "sessão não existe" in not_found
    assert "fora da apresentação" in not_found


def test_slide_page_number_starts_at_one(schema):
    parameters = schema["paths"][f"{PREFIX}/{{session_id}}/slides/{{number}}"]["get"]["parameters"]
    (number,) = [p for p in parameters if p["name"] == "number"]

    assert number["schema"]["minimum"] == 1


@pytest.mark.asyncio
async def test_slide_page_zero_is_422(client, presentation):
    response = await client.get(f"{PREFIX}/{presentation.id}/slides/0")

    assert response.status_code == 422


def test_every_422_also_explains_field_validation(schema):
    """O 422 do domínio não pode apagar, no OpenAPI, o 422 da validação de campos."""
    for path, methods in schema["paths"].items():
        for method, operation in methods.items():
            unprocessable = operation["responses"].get("422")
            if unprocessable and path.startswith(PREFIX):
                assert "validação" in unprocessable["description"], (method, path)
