"""Erros de domínio: cada recusa que a API pode devolver, com nome do domínio.

O domínio e os casos de uso levantam estes erros sem saber de HTTP; quem os traduz em
status é `app.api.errors`, numa tabela só. A mensagem é a que o usuário lê — em
português, dizendo o que fazer —, e vai inteira no `detail` da resposta.
"""


class DomainError(Exception):
    """Base de toda recusa prevista pelas regras do domínio."""


class ActionNotAllowedError(DomainError):
    """A sessão existe, mas o estado em que está não permite a ação pedida."""


# --- Apresentação (/init) ---------------------------------------------------------------


class UnsupportedFileTypeError(DomainError):
    """O arquivo não é PDF nem PPTx."""


class FileTooLargeError(DomainError):
    """O upload passou do tamanho máximo aceito."""


class UnreadableFileError(DomainError):
    """O arquivo tem a extensão certa, mas não abre como PDF/PPTx."""


class NoExtractableTextError(DomainError):
    """O arquivo abre, mas quase não tem texto: slides que são só imagem.

    Recusar na ingestão, e não deixar o aterramento reprovar tudo lá na frente: sem texto
    o usuário receberia uma sessão concluída e vazia, sem pista de que a causa foi o
    arquivo. Falhar aqui diz o que fazer enquanto ainda dá para reenviar.
    """


# --- Áudio e transcrição ----------------------------------------------------------------


class MixedChunkFormatsError(DomainError):
    """Pedaços de áudio da mesma sessão em formatos diferentes.

    Erro do cliente, não do servidor: emendar formatos distintos até seria possível
    tecnicamente, mas indica que o VR trocou de codec no meio da gravação — e o áudio
    resultante não representaria mais uma fala contínua.
    """


class AudioTooLongError(DomainError):
    """O áudio passou da duração máxima do MVP."""


class UndecodableAudioError(DomainError):
    """O áudio não pôde ser decodificado: sem ele não há métrica de forma nem STT."""


class NoAudioError(DomainError):
    """Pediram a análise completa de uma sessão que não recebeu áudio."""


class NoSpeechError(DomainError):
    """Pediram a análise básica sem áudio e sem transcrição: não há fala nenhuma."""


class EmptyTranscriptError(DomainError):
    """O cliente mandou uma transcrição sem nenhuma palavra.

    Vazio não é reaproveitado pelo pipeline (seria indistinguível de "o modelo não
    respondeu"), então aceitar só criaria a ilusão de que o STT seria pulado. Recusar na
    entrada diz ao cliente, na hora, que o texto não serviu.
    """


# --- Tela da sala (slides em PNG) ---------------------------------------------------------


class NotRenderableError(DomainError):
    """O servidor só desenha PDF: o python-pptx lê texto, mas não desenha slides."""


class PageNotFoundError(DomainError):
    """Pediram uma página fora da apresentação."""
