# 📄 Product Requirements Document (PRD) - Backend API

**Projeto:** PODIUM - MVP
**Descrição:** Plataforma de Treinamento Imersivo com Arguição Dinâmica, utilizando Realidade Virtual (VR) e Large Language Models (LLMs) para simular apresentações acadêmicas e profissionais.

## 1. Visão Geral e Objetivos do Backend

O backend do PODIUM atuará como o _Middleware_ e o integrador de _Serviços Cognitivos_. Seus objetivos principais são:

- Receber e extrair texto de arquivos de apresentação (PDF).
- Receber arquivos de áudio (até 15 minutos neste MVP) capturados pelo Cliente VR.
- Orquestrar a conversão de áudio para texto (Speech-to-Text) e enviar o contexto unificado (Slides + Transcrição) para um LLM.
- Retornar o "Feedback Duplo", contendo as perguntas contextuais geradas (avaliação de conteúdo) e métricas de forma (ritmo/pausas).

## 2. Stack Tecnológica Base

O assistente de código deve configurar o ambiente estritamente com as seguintes tecnologias:

- **Linguagem:** Python 3.14
- **Banco de Dados:** PostgreSQL.
- **ORM e Migrations:** SQLAlchemy 2.0 (modo `asyncio`) e Alembic.
- **Processamento de Arquivos:** `PyMuPDF` (extração de texto de PDF) e `pydub` + `FFmpeg` (manipulação de áudio).
- **Inteligência Artificial:** Tentar localizar a api mais barata que de conta de fazer o que eu preciso para o projeto.
- **Infraestrutura Local:** Docker e Docker Compose (containers para API e Banco de Dados).

## 3. Estrutura de Diretórios Solicitada (Modular Monolith)

O projeto deve seguir a organização Clean Architecture para separação de responsabilidades:

- `app/api/`: Controladores e roteadores do FastAPI (endpoints).
- `app/core/`: Configurações de sistema, variáveis de ambiente `.env` (ex: `DATABASE_URL`) e configurações de CORS.
- `app/models/`: Definições das tabelas do banco de dados (SQLAlchemy).
- `app/schemas/`: Contratos de entrada e saída (Pydantic Models) para validação de payload.
- `app/services/`: Regras de negócio (ex: `pdf_service.py`, `audio_service.py`, `llm_service.py`).
- `alembic/`: Controle de versionamento do banco de dados.

## 4. Modelagem de Dados (Entidades Principais)

A configuração inicial do banco de dados deve contemplar as seguintes tabelas lógicas:

1. **Users:** Cadastro básico do usuário.
2. **Presentations:** Armazena os metadados da sessão (ID do usuário, Persona escolhida, caminho do PDF armazenado, status da apresentação).
3. **Feedbacks:** Relacionada à apresentação, armazena a transcrição completa gerada pelo STT, as perguntas inéditas geradas pelo LLM e as métricas capturadas.

## 5. Endpoints Principais (API REST)

A API deve expor, no mínimo, as seguintes rotas base:

- `POST /api/v1/presentations/init`
  - **Ação:** Cria uma nova sessão. Recebe o tipo de cenário (ex: "Sala de Aula"), a Persona do LLM e o arquivo PDF (multipart/form-data).
  - **Retorno:** ID da sessão.

- `POST /api/v1/presentations/{session_id}/audio`
  - **Ação:** Recebe o arquivo de áudio ou _chunks_ de áudio do Cliente VR via upload.
  - **Retorno:** Confirmação de recebimento.

- `POST /api/v1/presentations/{session_id}/analyze`
  - **Ação:** Dispara o processamento assíncrono. Envia o áudio para o STT (Whisper), compila com o texto do PDF e envia ao LLM para geração de perguntas contextuais.
  - **Retorno:** Objeto JSON contendo as perguntas formuladas pela banca e a análise estrutural da fala.

## 6. Instruções de Execução para a IA (System Prompt)

> **Instrução para a IA de Código:** "Atue como um Arquiteto de Software Sênior. Baseado neste PRD, crie o boilerplate inicial completo do projeto. Gere o arquivo `docker-compose.yml`, o `requirements.txt` com as dependências listadas, e a estrutura de pastas descrita. Implemente um exemplo de conexão assíncrona com o PostgreSQL utilizando SQLAlchemy e crie a rota `POST /presentations/init` com validação no Pydantic."
