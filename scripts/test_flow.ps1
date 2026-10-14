<#
.SYNOPSIS
    Executa o fluxo completo do PODIUM: init -> audio -> analyze -> polling -> feedback.

.EXAMPLE
    .\scripts\test_flow.ps1 -Presentation storage\teste.pptx -Audio storage\fala_teste.wav

.EXAMPLE
    .\scripts\test_flow.ps1 -Presentation "C:\meu_tcc.pdf" -Audio "C:\minha_fala.m4a" -Persona technical_expert

.EXAMPLE
    # Analise basica: so a fala, sem slides no prompt e sem cobertura. Rodar a mesma
    # sessao nos dois modos e o que mede a diferenca de tempo entre eles.
    .\scripts\test_flow.ps1 -Presentation "C:\meu_tcc.pdf" -Audio "C:\minha_fala.m4a" -AnalysisMode basic
#>
param(
    [Parameter(Mandatory = $true)][string]$Presentation,
    [Parameter(Mandatory = $true)][string]$Audio,
    [ValidateSet('strict_professor', 'supportive_advisor', 'technical_expert')]
    [string]$Persona = 'strict_professor',
    [ValidateSet('full', 'basic')]
    [string]$AnalysisMode = 'full',
    [string]$BaseUrl = 'http://localhost:8000/api/v1',
    [int]$TimeoutSeconds = 600
)

$ErrorActionPreference = 'Stop'

# curl.exe escreve UTF-8; lemos sempre de arquivo para o console nao corromper acentos.
$tmp = Join-Path $env:TEMP "podium_$([guid]::NewGuid()).json"
# O corpo do /analyze vai por arquivo: aspas dentro de argumento de curl.exe se perdem
# no Windows PowerShell 5.1.
$analyzeBody = Join-Path $env:TEMP "podium_body_$([guid]::NewGuid()).json"

# O temporario tem que sumir mesmo quando o script aborta no meio — e agora ele aborta,
# porque as chamadas passaram a falhar alto. `trap` cobre isso sem exigir que o corpo
# inteiro do script viva dentro de um try/finally.
trap { Remove-Item $tmp, $analyzeBody -Force -ErrorAction SilentlyContinue; break }

function Invoke-Podium {
    <#
        Devolve o corpo ja convertido e falha com a mensagem da API quando o status nao e
        2xx. Antes o codigo HTTP era ignorado: um 422 do /init (arquivo sem texto
        extraivel) virava um objeto sem `session_id` e o erro exibido era o JSON cru — a
        causa real, que a API explica em `detail`, ficava escondida dentro da estrutura.
    #>
    param([string[]]$CurlArgs, [string]$Step = 'A chamada')

    $status = curl.exe -s -o $tmp -w '%{http_code}' @CurlArgs
    $body = Get-Content $tmp -Raw -Encoding UTF8

    if ($status -notmatch '^2\d\d$') {
        $detail = $body
        $errorBody = $body | ConvertFrom-Json -ErrorAction SilentlyContinue
        if ($errorBody -and $errorBody.detail) {
            # O 422 de validacao do FastAPI traz `detail` como lista de objetos, nao string.
            $detail = if ($errorBody.detail -is [string]) { $errorBody.detail }
                       else { $errorBody.detail | ConvertTo-Json -Compress -Depth 5 }
        }
        throw "$Step falhou (HTTP $status): $detail"
    }

    return ($body | ConvertFrom-Json)
}

foreach ($path in @($Presentation, $Audio)) {
    if (-not (Test-Path $path)) { throw "Arquivo nao encontrado: $path" }
}

$presentationPath = (Resolve-Path $Presentation).Path
$audioPath = (Resolve-Path $Audio).Path

Write-Host ""
Write-Host "PODIUM - teste de fluxo completo" -ForegroundColor Cyan
Write-Host "  apresentacao: $presentationPath"
Write-Host "  audio       : $audioPath"
Write-Host "  persona     : $Persona"
Write-Host "  analise     : $AnalysisMode"
Write-Host ""

# --- 1. Cria a sessao e envia a apresentacao -------------------------------
Write-Host "[1/4] Criando sessao e extraindo os slides..." -ForegroundColor Yellow
$init = Invoke-Podium -Step 'Criacao da sessao (/init)' -CurlArgs @(
    '-X', 'POST', "$BaseUrl/presentations/init",
    '-F', "file=@$presentationPath",
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
$upload = Invoke-Podium -Step 'Envio do audio (/audio)' -CurlArgs @(
    '-X', 'POST', "$BaseUrl/presentations/$sessionId/audio",
    '-F', "file=@$audioPath"
)
$duration = [math]::Round([double]$upload.duration_seconds, 1)
Write-Host "      recebido: $($upload.received_bytes) bytes  |  duracao: $duration s"

# --- 3. Dispara a analise (assincrona) -------------------------------------
Write-Host "[3/4] Disparando a analise (resposta imediata, processa em 2o plano)..." -ForegroundColor Yellow
@{ analysis_mode = $AnalysisMode } | ConvertTo-Json -Compress |
    Set-Content -Path $analyzeBody -Encoding ascii
$analysis = Invoke-Podium -Step 'Disparo da analise (/analyze)' -CurlArgs @(
    '-X', 'POST', "$BaseUrl/presentations/$sessionId/analyze",
    '-H', 'Content-Type: application/json',
    '--data-binary', "@$analyzeBody"
)
Write-Host "      status  : $($analysis.status)"

# --- 4. Polling ate concluir ----------------------------------------------
Write-Host "[4/4] Aguardando o processamento (STT + LLM)..." -ForegroundColor Yellow
$start = Get-Date
do {
    Start-Sleep -Seconds 3
    $session = Invoke-Podium -Step 'Consulta de status' -CurlArgs @(
        "$BaseUrl/presentations/$sessionId"
    )
    $elapsed = [int]((Get-Date) - $start).TotalSeconds
    Write-Host "      ${decorrido}s -> $($session.status)"

    if ($elapsed -gt $TimeoutSeconds) { throw "Timeout apos $TimeoutSeconds s." }
} while ($session.status -eq 'processing')

if ($session.status -eq 'failed') {
    Write-Host ""
    Write-Host "FALHOU: $($session.error_message)" -ForegroundColor Red
    Remove-Item $tmp, $analyzeBody -ErrorAction SilentlyContinue
    exit 1
}

# --- Resultado -------------------------------------------------------------
$fb = Invoke-Podium -Step 'Busca do feedback (/feedback)' -CurlArgs @(
    "$BaseUrl/presentations/$sessionId/feedback"
)

Write-Host ""
Write-Host "=== TRANSCRICAO ===" -ForegroundColor Green
Write-Host $fb.transcript
Write-Host ""
Write-Host "=== FORMA (metricas vocais) ===" -ForegroundColor Green
$m = $fb.delivery_metrics
if (-not $m) {
    # Analise basica sem audio: as metricas de forma nao existem, e a API diz por que.
    Write-Host "  $($fb.delivery_metrics_reason)" -ForegroundColor Yellow
    $m = [pscustomobject]@{}
}
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
    $fb.questions_approved, $fb.questions_generated, $fb.grounding_rate) -ForegroundColor Cyan
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
    $evidence = ($q.quote -replace '\s*\r?\n\s*', ' ')
    # A origem diz contra o que o trecho foi conferido: um slide ou a fala transcrita.
    $origin = if ($q.source -eq 'speech') { 'fala' } else { "slide $($q.slide_number)" }
    Write-Host ("     evidencia [{0}]: {1}" -f $origin, $evidence) -ForegroundColor DarkGray
    if ($q.rationale) { Write-Host ("     motivo: {0}" -f $q.rationale) -ForegroundColor DarkGray }
    Write-Host ""
    $i++
}
Write-Host "=== ANALISE ===" -ForegroundColor Green
Write-Host $fb.content_analysis
Write-Host ""
Write-Host "Sessao: $sessionId" -ForegroundColor DarkGray

Remove-Item $tmp, $analyzeBody -ErrorAction SilentlyContinue
