<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# ZUPT Web 5.2.9

[English](README.md) | [Português do Brasil](README.pt-BR.md)

O ZUPT Web é uma interface web auto-hospedada para o arquivador ZUPT. Ele
compacta, criptografa, verifica, inspeciona e extrai arquivos `.zupt` sem conta
externa nem armazenamento em nuvem.

Esta versão compila o código-fonte imutável do ZUPT 5.2.9 com o codec
VaptVupt 2.65.11. A atualização reforça a validação de limites, fluxos
truncados, capacidade da saída, metadados de quadro e caudas XXH64. O formato
de arquivo ZUPT v1.6, as rotas web e os modos criptográficos não mudaram em
relação ao ZUPT Web 5.2.8.

## Execução local

Requisitos: Docker Engine e Docker Compose.

```sh
git clone https://git.securityops.co/cristiancmoises/zupt-web.git
cd zupt-web
./setup.sh
```

Por padrão, o serviço escuta somente em `127.0.0.1:8181`. Para usar outra
porta local:

```sh
PORT_HOST=8282 ./setup.sh
```

Quando o TLS termina em um proxy reverso, defina `ZUPT_COOKIE_SECURE=1` para
exigir o atributo `Secure` no cookie CSRF. O backend não confia automaticamente
em cabeçalhos encaminhados para deduzir o esquema visto pelo navegador.

Confirme a versão e a prontidão:

```sh
curl -fsS http://127.0.0.1:8181/healthz
curl -fsS http://127.0.0.1:8181/version
docker exec zupt-web zupt version
```

O endpoint de saúde deve informar `5.2.9`. O endpoint `/version` responde com
HTTP 503 quando o binário do ZUPT não está pronto; ele não mascara essa falha
como sucesso.

## Recursos

| Recurso | Implementação |
|---|---|
| Criptografia híbrida | ML-KEM-768 + X25519 por `--pq` |
| Criptografia somente pós-quântica | ML-KEM-768 por `--pq-only` |
| Criptografia por senha | AES-256-CTR + HMAC-SHA256 e PBKDF2-SHA256 |
| Compactação | AUTO, VaptVupt 2.65.11, LZHP ou Store |
| Validação | trailer autenticado, validação por bloco e extração contida |
| Implantação | contêiner em três estágios, sem root e com raiz somente leitura |

O modo sólido e a desduplicação por blocos são mutuamente exclusivos na
interface. O gravador sólido do ZUPT não executa desduplicação real.

## Configuração

| Variável | Padrão | Finalidade |
|---|---:|---|
| `ZUPT_MAX_UPLOAD_MB` | `512` | limite da requisição em MiB |
| `ZUPT_KEY_TTL_SEC` | `14400` | retenção de tarefas e chaves |
| `ZUPT_COMPRESS_TIMEOUT` | `600` | tempo máximo de compactação |
| `ZUPT_EXTRACT_TIMEOUT` | `600` | tempo máximo de extração/verificação |
| `ZUPT_COOKIE_SECURE` | `0` | use `1` quando o acesso do navegador for exclusivamente por HTTPS |
| `ZUPT_SECRET_KEY` | gerada no início | segredo de sessão do Flask |

Os nomes antigos `VAPTVUPT_*` ainda são aceitos como fallback de
compatibilidade. Novas implantações devem usar `ZUPT_*`.

## Limite de segurança

- Publique a interface remota apenas atrás de HTTPS. Ela recebe senhas e
  chaves privadas.
- O contêiner executa como UID 1001, remove todas as capabilities, ativa
  `no-new-privileges`, limita processos e memória e usa sistema de arquivos
  raiz somente leitura.
- Senhas chegam ao ZUPT por descritor herdado (`--pass-fd 0`), não pela lista
  de argumentos do processo.
- Cada formulário usa token CSRF; caminhos de upload e download são validados
  e isolados por tarefa.
- Implantações HTTPS devem definir `ZUPT_COOKIE_SECURE=1`; o teste ao vivo por
  HTTPS rejeita um cookie CSRF sem o atributo `Secure`.
- Arquivos enviados continuam sendo entrada não confiável. Isolamento e
  limites reduzem risco, mas não equivalem a uma prova de ausência de falhas.

## Migração do 5.2.1

O perfil atual não inclui o binário opaco `libvuptsdk` usado pela imagem web
5.2.1. Arquivos Argon2id ou `--pq-sdk` daquela versão precisam ser restaurados
com o leitor 5.2.1 em ambiente local e confiável, verificados e depois
recriados com um modo nativo atual. Não remova a única cópia nem o ambiente
de recuperação antes de testar a restauração. Consulte
[MIGRATION.md](MIGRATION.md).

## Proveniência e testes

O diretório `zupt-5.2.9/` vem do artefato oficial da tag `v5.2.9`, commit
`63f27dd0c5afcf155f813a069c29f6384d46790c`. O SHA-256 do arquivo-fonte é:

```text
24e1e3251c0bbcab049d3a7c3f1451e1b824fbb95ef454ca7c03077c8a470171
```

`build-zupt.sh` verifica os 203 arquivos do manifesto antes de compilar. Para
validar a aplicação localmente:

```sh
python3 -m venv .venv
.venv/bin/pip install --require-hashes -r requirements.txt
.venv/bin/python -m unittest discover -s tests -v
docker compose config --quiet
docker build --tag zupt-web:5.2.9 .
```

Os resultados executados para esta revisão ficam consolidados em
[AUDIT.md](AUDIT.md); um teste não executado ou bloqueado não é tratado como
aprovação.

## Licenças

O ZUPT Web usa AGPL-3.0-or-later. O código-fonte incluído possui escopos
AGPL-3.0-or-later, GPL-3.0-or-later, BSD-2-Clause, BSD-3-Clause e CC0-1.0
identificados separadamente. Preserve `LICENSE*`, `NOTICE` e
`THIRD-PARTY-NOTICES.md` ao redistribuir.

Contato para licenciamento comercial: `sac@securityops.co`.
