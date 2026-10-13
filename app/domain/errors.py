"""Erros de domínio: cada recusa que a API pode devolver, com nome do domínio.

O domínio e os casos de uso levantam estes erros sem saber de HTTP; quem os traduz em
status é `app.api.errors`, numa tabela só. A mensagem é a que o usuário lê — em
português, dizendo o que fazer —, e vai inteira no `detail` da resposta.
"""


class DomainError(Exception):
    """Base de toda recusa prevista pelas regras do domínio."""


class ActionNotAllowedError(DomainError):
    """A sessão existe, mas o estado em que está não permite a ação pedida."""
