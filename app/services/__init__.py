"""Casos de uso (o "service layer" do livro *Architecture Patterns with Python*).

Orquestram uma operação inteira: buscam o que precisam, chamam o domínio e os
adaptadores e gravam o resultado. Os endpoints em `app.api` só traduzem HTTP para estas
funções e de volta.
"""
