"""Camada de domínio: regras que não dependem de framework, banco ou provedor externo.

O que vive aqui não importa FastAPI, SQLAlchemy nem SDK de IA — só Python e os contratos
do próprio domínio. É o que permite testar a regra sem subir infraestrutura.
"""
