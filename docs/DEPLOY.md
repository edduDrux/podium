# Deploy na Oracle Cloud

Como subir a API numa VM ARM do Always Free da Oracle. Por que cada escolha foi feita está
no `docs/DECISOES.md` (§14, chave de acesso; §15, deploy).

```
Quest / celular ──HTTPS 443──► Caddy ──► api:8000 ──► db:5432
                               (VM: só as portas 22, 80 e 443 abertas na Security List)
```

- `docker-compose.yml` (o de desenvolvimento) + `docker-compose.prod.yml` (por cima dele):
  banco sem porta pública, API sem `--reload` e sem o código montado, Caddy na frente.
- `deploy/Caddyfile`: o Caddy pede e renova o certificado HTTPS do domínio sozinho.
- `deploy/production.env.example`: o `.env` da VM, com o que muda em produção.
- `deploy/update.sh`: instala e atualiza (pull, build, migrations, `up`).

## Antes de começar

- **Chave do Gemini** (a mesma do `.env` de desenvolvimento serve).
- **Chave de acesso** (`API_KEY`): o mesmo valor vai no `.env` da VM e no app, no arquivo
  `Assets/Podium/Resources/PodiumAccessKey.txt` do `podium-vr` (fora do Git). Sem ela, a API
  em produção não sobe; com uma diferente da do app, toda chamada do headset dá `401`.
- **Branch:** o código atual está em `reestruturacao`. Se ela for para a `main` antes, troque
  o nome no `git clone` do passo 7.

## 1. Conta e região

1. Crie a conta Free Tier da Oracle Cloud (o cartão é só verificação).
2. **A região inicial não muda depois.** Escolha São Paulo ou Vinhedo.
3. Se a criação da VM der *Out of capacity* (comum com ARM), faça o upgrade para *Pay As You
   Go*: o que é Always Free continua gratuito, a capacidade melhora e a Oracle deixa de
   recolher instância ociosa. Crie um alerta de orçamento baixo em *Billing → Budgets*.

## 2. Chave SSH (no seu PC, PowerShell)

```powershell
ssh-keygen -t ed25519 -f $HOME\.ssh\oci_podium
```

Gera `oci_podium` (privada, fica no PC) e `oci_podium.pub` (vai para a Oracle).

## 3. Criar a VM

*Compute → Instances → Create instance*:

- **Image:** Canonical Ubuntu 24.04. Depois de escolher o shape, o console mostra a versão
  aarch64.
- **Shape:** *Ampere* → `VM.Standard.A1.Flex`. O projeto foi pensado para 1 OCPU e 12 GB
  (CLAUDE.md §5); o console mostra quanto o Always Free da conta permite.
- **Networking:** criar VCN nova, sub-rede **pública**, **atribuir IP público**.
- **Add SSH keys:** *Upload public key files* → `oci_podium.pub`.

Anote o **IP público** quando a instância ficar *Running*.

## 4. Abrir 80 e 443

*Networking → Virtual cloud networks → (a VCN) → Security Lists → Default Security List →
Add Ingress Rules*, duas regras:

| Source CIDR | IP Protocol | Destination Port |
| --- | --- | --- |
| `0.0.0.0/0` | TCP | `80` |
| `0.0.0.0/0` | TCP | `443` |

A 80 é para o Let's Encrypt validar o domínio e para redirecionar ao HTTPS. **Nunca abra
8000, 5432 nem 5433.** Se quiser, restrinja a regra da 22 ao IP da sua casa.

## 5. Domínio

O Caddy só emite certificado para um nome. Duas opções gratuitas:

- **sslip.io (a usada no deploy atual):** sem conta. O nome é o IP da VM com hífens, por
  exemplo `203-0-113-10.sslip.io` para o IP `203.0.113.10`, e já resolve para ele. Se a VM
  for recriada e o IP mudar, o domínio muda junto.
- **[DuckDNS](https://www.duckdns.org):** nome fixo. Entre, crie um subdomínio (ex.:
  `podium-tcc`) e ponha o IP da VM em *current ip*; o domínio fica `podium-tcc.duckdns.org`.

Confira no PowerShell que o nome aponta para a VM:

```powershell
Resolve-DnsName podium-tcc.duckdns.org
```

O HTTPS não é opcional: o Android do Quest recusa `http://` por padrão, e áudio de voz não
trafega aberto na internet.

## 6. Entrar e instalar o Docker

```powershell
ssh -i $HOME\.ssh\oci_podium ubuntu@IP_DA_VM
```

Na VM:

```sh
sudo apt-get update && sudo apt-get -y upgrade
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker ubuntu
exit
```

Entre de novo (o grupo `docker` só vale numa sessão nova) e confira: `docker compose version`.

## 7. Código e `.env`

Na VM:

```sh
git clone -b reestruturacao https://github.com/edduDrux/podium.git
cd podium
cp deploy/production.env.example .env
openssl rand -hex 24
nano .env
```

Troque cada `<...>` do `.env`:

- `DOMAIN` e o domínio dentro de `BACKEND_CORS_ORIGINS`: o do passo 5.
- `POSTGRES_PASSWORD` e a senha dentro de `DATABASE_URL`: a saída do `openssl` (a mesma
  nas duas). **Antes do primeiro `up`**: o Postgres só lê a senha quando cria o volume.
- `API_KEY`: o conteúdo do `PodiumAccessKey.txt` do app.
- `GEMINI_API_KEY`: a sua chave.

## 8. Subir

```sh
sh deploy/update.sh
```

Na primeira vez, o build leva alguns minutos com 1 OCPU (roda nativo em ARM64; a CI já
monta essa imagem para arm64). O script termina listando os containers: `podium_db`,
`podium_api` e `podium_caddy`, todos *Up*.

Se algo falhar: `docker compose logs api` (ou `caddy`, `db`).

## 9. Conferir

Do seu PC, PowerShell:

```powershell
curl.exe https://podium-tcc.duckdns.org/api/v1/health
```

Deve vir `"environment":"production"` e `"database":"ok"`. Depois, a chave:

```powershell
curl.exe -i https://podium-tcc.duckdns.org/api/v1/personas
```

Sem o cabeçalho: `401`. No navegador, `https://podium-tcc.duckdns.org/docs` → *Authorize*
→ cole a chave → *Try it out* no `/personas`: `200`.

## 10. Apontar o app para a VM (`podium-vr`)

1. No Editor: `Assets/Podium/Config/ApiConfig` → **Device Base Url** =
   `https://podium-tcc.duckdns.org` (sem `/` no fim e sem porta).
2. Confira que `Assets/Podium/Resources/PodiumAccessKey.txt` tem a mesma chave do `.env`.
3. Gere o build e instale pelo SideQuest. A página de envio que o headset mostra passa a
   ser `https://.../upload?code=...`, acessível do celular em qualquer rede.

## Manutenção

- **Atualizar** depois de um `git push`: na VM, `cd podium && sh deploy/update.sh`.
- **Reinício da VM:** o Docker sobe com o sistema e os containers têm
  `restart: unless-stopped`; nada a fazer.
- **Backup do banco** (diário, às 3 h): `crontab -e` e acrescente

  ```
  0 3 * * * cd /home/ubuntu/podium && docker compose exec -T db pg_dump -U podium podium | gzip > /home/ubuntu/podium-$(date +\%F).sql.gz
  ```

  O `-T` evita que o terminal corrompa a saída; o `\%` é exigência do cron.
- **Trocar a chave de acesso:** novo valor no `.env` da VM → `docker compose up -d api`
  (recria; `restart` não relê o `.env`, CLAUDE.md §8) → mesmo valor no app → build novo.
- **Disco:** os arquivos de sessão já são apagados depois de `STORAGE_RETENTION_HOURS`. Cada
  rebuild deixa imagens velhas: `docker image prune` de vez em quando.

## Problemas comuns

| Sintoma | Causa provável |
| --- | --- |
| `curl` do PC não responde | Regra do passo 4 faltando. A imagem Ubuntu da Oracle também traz iptables fechado; o tráfego das portas do Docker passa pelas regras que o próprio Docker cria, mas, se a Security List estiver certa e mesmo assim não responder, olhe `sudo iptables -L FORWARD -n`. |
| Caddy em loop com erro de certificado | O domínio não aponta para o IP da VM (passo 5) ou a porta 80 está fechada. |
| API reiniciando com `API_KEY é obrigatória` | `API_KEY` vazia no `.env` com `ENVIRONMENT=production`. Foi de propósito (DECISOES §14). |
| `password authentication failed` | A senha mudou no `.env` depois do primeiro `up`. O volume guarda a antiga. |
| Headset recebe `401` | A chave do app é diferente da do `.env`. |
