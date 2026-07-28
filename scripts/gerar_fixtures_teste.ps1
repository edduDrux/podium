<#
.SYNOPSIS
    Regenera as fixtures dos testes end-to-end: o PDF da apresentacao e os dois audios.

.DESCRIPTION
    As fixtures nao sao versionadas — sao ~8 MB de WAV, e o repositorio nao e lugar para
    binario reproduzivel. Este script as recria em qualquer maquina Windows, para que o
    teste adversarial obrigatorio do §14 do CLAUDE.md possa ser reexecutado e documentado.

    Gera tres arquivos em storage/_fixtures/ (ignorado pelo git, e intocado pela purga
    automatica, que so apaga diretorios com nome de UUID):

      tcc_slides.pdf         apresentacao de 5 slides (via PyMuPDF, dentro do container)
      fala_apresentacao.wav  a fala LEGITIMA sobre esses slides
      fala_adversarial.wav   fala sobre assunto completamente diferente (uma receita)

    A fala legitima omite de proposito o slide 5 (limitacoes) e conclui causalidade sem
    respaldo — sao as lacunas que a banca deve cobrar. A fala adversarial e o insumo do
    teste do §14: mesmo material, exposicao oral desconexa.

    A voz e escolhida pelo IDIOMA (pt-BR), nao pelo nome: o Windows PowerShell 5.1 e o
    pwsh 7 enxergam conjuntos DIFERENTES de vozes instaladas na mesma maquina — o 5.1 so
    lista as "Desktop", o 7 lista tambem as OneCore. Fixar um nome quebraria em um dos
    dois, e quebraria de novo em outra maquina. Use -Voz para preferir uma especifica.

.EXAMPLE
    .\scripts\gerar_fixtures_teste.ps1

.EXAMPLE
    .\scripts\gerar_fixtures_teste.ps1 -Voz 'Microsoft Daniel'
#>

[CmdletBinding()]
param(
    [string]$Voz = '',
    [string]$Idioma = 'pt-BR',
    [string]$Destino = 'storage/_fixtures'
)

$ErrorActionPreference = 'Stop'

$raiz = Split-Path -Parent $PSScriptRoot
Set-Location $raiz

# --- 1. PDF, via PyMuPDF no container (o §4 diz que tudo roda no Docker) --------------
Write-Host 'Gerando o PDF da apresentacao...' -ForegroundColor Cyan
docker compose exec -T api python scripts/gerar_slides_fixture.py
if ($LASTEXITCODE -ne 0) {
    throw 'Falha ao gerar o PDF. O container `api` esta de pe? (docker compose up -d)'
}

# --- 2. Audios, via SAPI ---------------------------------------------------------------
$pasta = Join-Path $raiz $Destino
if (-not (Test-Path $pasta)) { New-Item -ItemType Directory -Path $pasta | Out-Null }

$apresentacao = @'
Bom dia a todos. Meu nome é Eduardo Sartori e vou apresentar meu trabalho de conclusão de curso, que trata da avaliação de usabilidade de um simulador de apresentações acadêmicas em realidade virtual.
O problema que motivou a pesquisa é que falar em público é a principal dificuldade relatada por estudantes de graduação na hora de defender o trabalho final. Muita gente domina o conteúdo, mas trava na frente da banca.
O objetivo foi avaliar se um simulador em realidade virtual reduz a ansiedade percebida antes da banca.
Sobre o método, eu conduzi um estudo com doze participantes voluntários, em laboratório. Apliquei o System Usability Scale depois de cada sessão. A coleta levou cerca de três semanas.
Nos resultados, a pontuação média do SUS foi de setenta e oito vírgula quatro pontos, o que é considerado bom. O tempo médio de preparação caiu vinte e três por cento depois de duas sessões no simulador. E nenhum participante relatou desconforto vestibular, o que era uma preocupação minha por causa do enjoo em realidade virtual.
Com isso eu concluo que a ferramenta funciona e que ela realmente reduz a ansiedade dos estudantes. Muito obrigado.
'@

$adversarial = @'
Então, gente, hoje eu vou ensinar a fazer uma feijoada completa. Primeiro você deixa o feijão preto de molho na véspera, junto com as carnes salgadas, que precisam ser dessalgadas trocando a água pelo menos três vezes.
No dia seguinte, refoga bastante alho e cebola numa panela grande, com um pouco de bacon para dar gordura. Aí você junta o feijão, cobre com água e deixa cozinhar em fogo baixo por umas duas horas.
As carnes vão entrando por ordem de dureza: primeiro a costelinha e a carne seca, depois a linguiça calabresa e o paio. O segredo é não colocar sal antes do fim, porque as carnes salgadas já soltam bastante.
Para acompanhar, arroz branco soltinho, couve refogada bem fininha, farofa de bacon e laranja em rodelas. A laranja não é enfeite, ela ajuda na digestão.
Se quiser engrossar o caldo, pega uma concha de feijão, amassa e devolve para a panela. Fica muito melhor do que usar farinha. Bom apetite a todos.
'@

Add-Type -AssemblyName System.Speech

# Descoberta da voz antes de sintetizar: falhar aqui e mais barato que descobrir no meio.
$instaladas = (New-Object System.Speech.Synthesis.SpeechSynthesizer).GetInstalledVoices() |
    ForEach-Object { $_.VoiceInfo }

if ($Voz -and ($instaladas.Name -contains $Voz)) {
    $vozEscolhida = $Voz
} else {
    if ($Voz) {
        Write-Warning "Voz '$Voz' nao esta instalada neste runtime; escolhendo por idioma."
    }
    $vozEscolhida = ($instaladas | Where-Object { $_.Culture -eq $Idioma } |
        Select-Object -First 1).Name
}

if (-not $vozEscolhida) {
    $lista = ($instaladas | ForEach-Object { "$($_.Name) [$($_.Culture)]" }) -join ', '
    throw "Nenhuma voz $Idioma instalada. Disponiveis: $lista. " +
          'Instale uma voz pt-BR em Configuracoes > Hora e idioma > Fala.'
}
Write-Host "Voz: $vozEscolhida" -ForegroundColor DarkGray

foreach ($item in @(
    @{ Nome = 'fala_apresentacao'; Texto = $apresentacao },
    @{ Nome = 'fala_adversarial';  Texto = $adversarial }
)) {
    Write-Host "Sintetizando $($item.Nome).wav..." -ForegroundColor Cyan
    $sintetizador = New-Object System.Speech.Synthesis.SpeechSynthesizer
    $sintetizador.SelectVoice($vozEscolhida)
    $arquivo = Join-Path $pasta "$($item.Nome).wav"
    $sintetizador.SetOutputToWaveFile($arquivo)
    $sintetizador.Speak($item.Texto)
    $sintetizador.Dispose()

    $mb = [math]::Round((Get-Item $arquivo).Length / 1MB, 2)
    Write-Host "  $arquivo — $mb MB" -ForegroundColor Green
}

Write-Host ''
Write-Host 'Fixtures prontas. Para a sessao legitima:' -ForegroundColor Yellow
Write-Host "  .\scripts\testar_fluxo.ps1 -Pdf $Destino/tcc_slides.pdf -Audio $Destino/fala_apresentacao.wav"
Write-Host 'Para o teste adversarial obrigatorio (mesmo PDF, audio fora do tema):' -ForegroundColor Yellow
Write-Host "  .\scripts\testar_fluxo.ps1 -Pdf $Destino/tcc_slides.pdf -Audio $Destino/fala_adversarial.wav"
