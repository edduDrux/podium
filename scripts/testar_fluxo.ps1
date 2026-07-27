<#
.SYNOPSIS
    Executa o fluxo completo do PODIUM: init -> audio -> analyze -> polling -> feedback.

.EXAMPLE
    .\scripts\testar_fluxo.ps1 -Apresentacao storage\teste.pptx -Audio storage\fala_teste.wav

.EXAMPLE
    .\scripts\testar_fluxo.ps1 -Apresentacao "C:\meu_tcc.pdf" -Audio "C:\minha_fala.m4a" -Persona plateia_leiga
#>
param(
    [Parameter(Mandatory = $true)][string]$Apresentacao,
    [Parameter(Mandatory = $true)][string]$Audio,
    [ValidateSet('professor_rigoroso', 'orientador_acolhedor', 'especialista_tecnico', 'plateia_leiga')]
    [string]$Persona = 'professor_rigoroso',
    [string]$BaseUrl = 'http://localhost:8000/api/v1',
    [int]$TimeoutSegundos = 600
)

$ErrorActionPreference = 'Stop'

# curl.exe escreve UTF-8; lemos sempre de arquivo para o console nao corromper acentos.
$tmp = Join-Path $env:TEMP "podium_$([guid]::NewGuid()).json"

function Invoke-Podium {
    param([string[]]$CurlArgs)
    curl.exe -s -o $tmp @CurlArgs | Out-Null
    return (Get-Content $tmp -Raw -Encoding UTF8 | ConvertFrom-Json)
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
$init = Invoke-Podium @(
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
$upload = Invoke-Podium @(
    '-X', 'POST', "$BaseUrl/presentations/$sessionId/audio",
    '-F', "file=@$audioPath"
)
$duracao = [math]::Round([double]$upload.duration_seconds, 1)
Write-Host "      recebido: $($upload.received_bytes) bytes  |  duracao: $duracao s"

# --- 3. Dispara a analise (assincrona) -------------------------------------
Write-Host "[3/4] Disparando a analise (resposta imediata, processa em 2o plano)..." -ForegroundColor Yellow
$analise = Invoke-Podium @('-X', 'POST', "$BaseUrl/presentations/$sessionId/analyze")
Write-Host "      status  : $($analise.status)"

# --- 4. Polling ate concluir ----------------------------------------------
Write-Host "[4/4] Aguardando o processamento (STT + LLM)..." -ForegroundColor Yellow
$inicio = Get-Date
do {
    Start-Sleep -Seconds 3
    $sessao = Invoke-Podium @("$BaseUrl/presentations/$sessionId")
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
$fb = Invoke-Podium @("$BaseUrl/presentations/$sessionId/feedback")

Write-Host ""
Write-Host "=== TRANSCRICAO ===" -ForegroundColor Green
Write-Host $fb.transcript
Write-Host ""
Write-Host "=== FORMA (metricas vocais) ===" -ForegroundColor Green
$m = $fb.metrics
Write-Host ("  ritmo          : {0} palavras/min" -f $m.words_per_minute)
Write-Host ("  duracao        : {0} s ({1} palavras)" -f $m.duration_seconds, $m.word_count)
Write-Host ("  pausas         : {0} (total {1} s, maior {2} s)" -f $m.pause_count, $m.total_pause_seconds, $m.longest_pause_seconds)
Write-Host ""
Write-Host "=== CONTEUDO (perguntas da banca) ===" -ForegroundColor Green
$i = 1
foreach ($q in $fb.questions) {
    Write-Host ("  {0}. {1}" -f $i, $q.question)
    if ($q.topic) { Write-Host ("     [topico: {0}]" -f $q.topic) -ForegroundColor DarkGray }
    Write-Host ""
    $i++
}
Write-Host "=== ANALISE ===" -ForegroundColor Green
Write-Host $fb.content_analysis
Write-Host ""
Write-Host "Sessao: $sessionId" -ForegroundColor DarkGray

Remove-Item $tmp -ErrorAction SilentlyContinue
