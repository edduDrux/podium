"""Adaptadores: o código que conversa com o mundo de fora.

Gemini (LLM e STT), FFmpeg/pydub, PyMuPDF e python-pptx, disco e a tabela de auditoria.
Cada adaptador cumpre uma porta de `app.domain.ports` ou é chamado pelos casos de uso;
nenhum contém regra de negócio — essa mora em `app.domain`.
"""
