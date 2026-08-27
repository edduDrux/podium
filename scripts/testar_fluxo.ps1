<#
.SYNOPSIS
    Executa o fluxo completo do PODIUM: init -> audio -> analyze -> polling -> feedback.

.EXAMPLE
    .\scripts\testar_fluxo.ps1 -Apresentacao storage\teste.pptx -Audio storage\fala_teste.wav

.EXAMPLE
    .\scripts\testar_fluxo.ps1 -Apresentacao "C:\meu_tcc.pdf" -Audio "C:\minha_fala.m4a" -Persona especialista_tecnico
#>
param(
    [Parameter(Mandatory = $true)][string]$Apresentacao,
    [Parameter(Mandatory = $true)][string]$Audio,
    [ValidateSet('professor_rigoroso', 'orientador_acolhedor', 'especialista_tecnico')]
    [string]$Persona = 'professor_rigoroso',
    [string]$BaseUrl = 'http://localhost:8000/api/v1',
    [int]$TimeoutSegundos = 600
)

$ErrorActionPreference = 'Stop'

# curl.exe escreve UTF-8; lemos sempre de arquivo para o console nao corromper acentos.
$tmp = Join-Path $env:TEMP "podium_$([guid]::NewGuid()).json"

# O temporario tem que sumir mesmo quando o script aborta no meio — e agora ele aborta,
# porque as chamadas passaram a falhar alto. `trap` cobre isso sem exigir que o corpo
# inteiro do script viva dentro de um try/finally.
trap { Remove-Item $tmp -Force -ErrorAction SilentlyContinue; break }

function Invoke-Podium {
    <#
        Devolve o corpo ja convertido e falha com a mensagem da API quando o status nao e
        2xx. Antes o codigo HTTP era ignorado: um 422 do /init (arquivo sem texto
        extraivel) virava um objeto sem `session_id` e o erro exibido era o JSON cru — a
        causa real, que a API explica em `detail`, ficava escondida dentro da estrutura.
    #>
    param([string[]]$CurlArgs, [string]$Etapa = 'A chamada')

    $status = curl.exe -s -o $tmp -w '%{http_code}' @CurlArgs
    $corpo = Get-Content $tmp -Raw -Encoding UTF8

    if ($status -notmatch '^2\d\d$') {
        $detalhe = $corpo
        $erro = $corpo | ConvertFrom-Json -ErrorAction SilentlyContinue
        if ($erro -and $erro.detail) {
            # O 422 de validacao do FastAPI traz `detail` como lista de objetos, nao string.
            $detalhe = if ($erro.detail -is [string]) { $erro.detail }
                       else { $erro.detail | ConvertTo-Json -Compress -Depth 5 }
        }
        throw "$Etapa falhou (HTTP $status): $detalhe"
    }

    return ($corpo | ConvertFrom-Json)
}

foreach ($caminho in @($Apresentacao, $Audio)) {
    if (-not (Test-Path $caminho)) { throw "Arquivo nao encontrado: $caminho" }
}

$apresentacaoPath = (Resolve-Path $Apresentacao).Path
$audioPath = (Resolve-Path $Audio).Path

Write-Host ""
Write-Host "PODIUM - teste de fluxo completo" -ForegroundColor Cyan
Write-Host "  apresentacao: $apresentacaoPath"
Write-Host "  audio       : $audioPath"
Write-Host "  persona     : $Persona"
Write-Host ""

# --- 1. Cria a sessao e envia a apresentacao -------------------------------
Write-Host "[1/4] Criando sessao e extraindo os slides..." -ForegroundColor Yellow
$init = Invoke-Podium -Etapa 'Criacao da sessao (/init)' -CurlArgs @(
    '-X', 'POST', "$BaseUrl/presentations/init",
    '-F', "file=@$apresentacaoPath",
    '-F', "persona=$Persona"
)
if (-not $init.session_id) { throw "Falha ao criar a sessao: $($init | ConvertTo-Json -Depth 5)" }

$sessionId = $init.session_id
Write-Host "      sessao  : $sessionId"
Write-Host "      formato : $($init.file_type)  |  texto extraido: $($init.slides_char_count) chars"
if ($init.slides_char_count -eq 0) {
    Write-Host "      AVISO: nenhum texto extraido (slides so com imagem?)." -ForegroundColor Red
}

# --- 2. Envia o audio ------------------------------------------------------
Write-Host "[2/4] Enviando o audio..." -ForegroundColor Yellow
$upload = Invoke-Podium -Etapa 'Envio do audio (/audio)' -CurlArgs @(
    '-X', 'POST', "$BaseUrl/presentations/$sessionId/audio",
    '-F', "file=@$audioPath"
)
$duracao = [math]::Round([double]$upload.duration_seconds, 1)
Write-Host "      recebido: $($upload.received_bytes) bytes  |  duracao: $duracao s"

# --- 3. Dispara a analise (assincrona) -------------------------------------
Write-Host "[3/4] Disparando a analise (resposta imediata, processa em 2o plano)..." -ForegroundColor Yellow
$analise = Invoke-Podium -Etapa 'Disparo da analise (/analyze)' -CurlArgs @(
    '-X', 'POST', "$BaseUrl/presentations/$sessionId/analyze"
)
Write-Host "      status  : $($analise.status)"

# --- 4. Polling ate concluir ----------------------------------------------
Write-Host "[4/4] Aguardando o processamento (STT + LLM)..." -ForegroundColor Yellow
$inicio = Get-Date
do {
    Start-Sleep -Seconds 3
    $sessao = Invoke-Podium -Etapa 'Consulta de status' -CurlArgs @(
        "$BaseUrl/presentations/$sessionId"
    )
    $decorrido = [int]((Get-Date) - $inicio).TotalSeconds
    Write-Host "      ${decorrido}s -> $($sessao.status)"

    if ($decorrido -gt $TimeoutSegundos) { throw "Timeout apos $TimeoutSegundos s." }
} while ($sessao.status -eq 'processing')

if ($sessao.status -eq 'failed') {
    Write-Host ""
    Write-Host "FALHOU: $($sessao.error_message)" -ForegroundColor Red
    Remove-Item $tmp -ErrorAction SilentlyContinue
    exit 1
}

# --- Resultado -------------------------------------------------------------
$fb = Invoke-Podium -Etapa 'Busca do feedback (/feedback)' -CurlArgs @(
    "$BaseUrl/presentations/$sessionId/feedback"
)

Write-Host ""
Write-Host "=== TRANSCRICAO ===" -ForegroundColor Green
Write-Host $fb.transcript
Write-Host ""
Write-Host "=== FORMA (metricas vocais) ===" -ForegroundColor Green
$m = $fb.metrics
# `speech_seconds` aparece junto do ritmo porque e o divisor dele: o wpm e calculado
# sobre o tempo de fala, nao sobre a duracao do arquivo, e sem os dois o numero nao e
# interpretavel.
Write-Host ("  ritmo          : {0} palavras/min (sobre {1} s de fala)" -f $m.words_per_minute, $m.speech_seconds)
Write-Host ("  duracao        : {0} s ({1} palavras)" -f $m.duration_seconds, $m.word_count)
Write-Host ("  pausas         : {0} (total {1} s, maior {2} s)" -f $m.pause_count, $m.total_pause_seconds, $m.longest_pause_seconds)
Write-Host ""
Write-Host "=== CONTEUDO (perguntas da banca) ===" -ForegroundColor Green

# A taxa de aterramento e a metrica nº 1 do capitulo de validacao (CLAUDE.md §14): mede
# quantas perguntas o modelo produziu contra quantas sobreviveram a checagem de evidencia.
# Rodar o teste sem exibi-la e rodar o teste sem ler o resultado.
Write-Host ("  aterramento    : {0} de {1} aprovadas (taxa {2})" -f `
    $fb.perguntas_aprovadas, $fb.perguntas_geradas, $fb.taxa_aterramento) -ForegroundColor Cyan
Write-Host ""

if (-not $fb.questions) {
    # Lista vazia e resultado legitimo, nao falha: o invariante e degradar sem inventar.
    # Sem este aviso, "nenhuma pergunta aprovada" e "o script nao imprimiu nada" ficam
    # indistinguiveis na tela.
    Write-Host "  Nenhuma pergunta sobreviveu ao aterramento. Ver a analise abaixo." -ForegroundColor Yellow
    Write-Host ""
}

$i = 1
foreach ($q in $fb.questions) {
    Write-Host ("  {0}. {1}" -f $i, $q.question)
    # A evidencia sai junto da pergunta porque e ela que torna a pergunta auditavel: sem
    # o slide e o trecho, nao da para distinguir na tela uma pergunta ancorada de uma
    # alucinacao plausivel.
    # As quebras de linha do trecho viram espaco so na exibicao: o extrator preserva a
    # quebra do slide original, e imprimi-la crua desalinha o bloco. O valor comparado
    # pelo aterramento e o do JSON, nao este.
    $evidencia = ($q.trecho_literal -replace '\s*\r?\n\s*', ' ')
    Write-Host ("     evidencia [slide {0}]: {1}" -f $q.slide_origem, $evidencia) -ForegroundColor DarkGray
    if ($q.rationale) { Write-Host ("     motivo: {0}" -f $q.rationale) -ForegroundColor DarkGray }
    Write-Host ""
    $i++
}
Write-Host "=== ANALISE ===" -ForegroundColor Green
Write-Host $fb.content_analysis
Write-Host ""
Write-Host "Sessao: $sessionId" -ForegroundColor DarkGray

Remove-Item $tmp -ErrorAction SilentlyContinue
