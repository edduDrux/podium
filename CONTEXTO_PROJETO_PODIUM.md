content = """# 🧠 Contexto Geral do Projeto: PODIUM

## 1. O que é o PODIUM?

O PODIUM é uma plataforma imersiva de treinamento de oratória que utiliza Realidade Virtual (VR) e Large Language Models (LLMs) para simular arguições contextuais . O objetivo é ajudar estudantes e profissionais a superarem a ansiedade de apresentações públicas. Ao contrário de ferramentas tradicionais que avaliam apenas a forma (ritmo, tom de voz), o PODIUM integra a imersão visual com a análise semântica, simulando uma banca que faz perguntas inéditas com base no **conteúdo** que foi apresentado .

## 2. O Escopo do MVP

Para o Produto Mínimo Viável (MVP), o sistema funcionará com as seguintes restrições e fluxos:

- **Cenário VR:** Inicialmente restrito ao ambiente de "Sala de Aula" (foco em defesa de TCC e trabalhos acadêmicos).
- **Ingestão de Arquivos:** O sistema recebe a apresentação do usuário em formato PDF e PPTx .
- **Captura de Áudio:** Gravação contínua do áudio do usuário durante a apresentação no VR, limitada a um máximo de 15 minutos.
- **Dinâmica:** O usuário escolhe a "persona" da IA. Ao finalizar a fala, o sistema analisa os slides (PDF/PPTx) somados à transcrição do que foi dito fora dos slides (Áudio) para gerar as perguntas e o feedback.

## 3. O Papel desta API (Backend)

Este projeto atua como o **Middleware** e a camada de **Serviços Cognitivos**. Ele funciona de forma invisível para o usuário final, recebendo requisições exclusivamente do Cliente VR (desenvolvido em Unity/C#).

**Responsabilidades Principais:**

1. **Gestão de Arquivos:** Receber e armazenar temporariamente os PDFs e os _chunks_ de áudio enviados pelo Oculus VR.
2. **Extração (Parser):** Ler e extrair o texto limpo do arquivo PDF enviado [cite: 2].
3. **Transcrição (STT):** Integrar com um serviço de Speech-to-Text para converter o áudio da apresentação em texto.
4. **Análise com LLM:** Montar o prompt estruturado contendo a transcrição da fala + o texto dos slides + a persona escolhida, enviando-os para a API de um modelo de linguagem (ex: OpenAI GPT ou Anthropic Claude).
5. **Retorno de Feedback (Feedback Duplo):** Devolver ao frontend as perguntas geradas e as métricas de forma (como ritmo e pausas).

## 4. Glossário Rápido para a IA

- **Cliente VR:** O frontend no óculos de realidade virtual.
- **STT:** Speech-to-Text (Conversão de voz para texto).
- **LLM:** Large Language Model (Motor de IA que gera as perguntas).
- **Feedback Duplo:** Avaliação simultânea de Conteúdo (Perguntas) e Forma (Métricas vocais).
  """
