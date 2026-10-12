"""Lo que comparten todas las pruebas de pytest."""
import pytest

from ayuda import Cliente


@pytest.fixture(scope="session")
def api(playwright):
    """Para llamar a la API sin navegador."""
    contexto = playwright.request.new_context()
    yield contexto
    contexto.dispose()


@pytest.fixture(scope="session")
def teatro(api):
    return Cliente(api, "teatro-avenida")


@pytest.fixture(scope="session")
def club(api):
    return Cliente(api, "club-atletico")
