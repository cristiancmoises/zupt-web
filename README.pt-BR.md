<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# ZUPT Web 5.2.13

[English](README.md) | [Português do Brasil](README.pt-BR.md)

O ZUPT Web é uma interface auto-hospedada para o arquivador ZUPT. Compacta,
criptografa, verifica, inspeciona e extrai arquivos `.zupt` sem contas ou
armazenamento em nuvem. Compila o código-fonte oficial do **ZUPT 5.2.10** com
**VaptVupt 2.65.13**; o formato desktop permanece **v1.6**.
A versão Web 5.2.13 é independente da versão 5.2.10 do CLI incluído.

## Execução

Requisitos: Docker Engine e Docker Compose.

```sh
git clone https://git.securityops.co/cristiancmoises/zupt-web.git
cd zupt-web
./setup.sh
# http://localhost:8181
```

Um pacote-fonte Web `.zupt` extrai arquivos com modo 0600. Verifique primeiro
a assinatura GPG do `SHA256SUMS` daquela release Web e o checksum do pacote;
o [UPSTREAM.md](UPSTREAM.md) registra a impressão digital da chave e a
proveniência do núcleo. Na raiz do projeto extraído, restaure somente estes
pontos de entrada antes de executar o setup ou a verificação do fonte:

```sh
chmod u+x setup.sh build-zupt.sh \
  zupt-5.2.10/scripts/check-source-only.sh
```

O `setup.sh` valida o Compose, compila e testa o CLI incluído, inicia o
contêiner e confere a versão. Use `PORT_HOST=8282 ./setup.sh` para mudar a
porta local. Para gerenciar diretamente:

```sh
docker compose build
docker compose up -d
docker compose ps
docker compose logs -f
docker compose down
```

O endereço padrão é `127.0.0.1:8181`. O acesso remoto exige um proxy reverso
HTTPS e controle de acesso adequado ao público: o serviço recebe senhas e
chaves privadas. Quando o TLS termina no proxy, defina `ZUPT_COOKIE_SECURE=1`.
Use `BIND_HOST=0.0.0.0` apenas com a proteção de rede já configurada.

## Recursos

| Recurso | Implementação |
|---|---|
| Criptografia híbrida | ML-KEM-768 + X25519, `--pq` |
| Criptografia somente pós-quântica | ML-KEM-768, `--pq-only` |
| Criptografia por senha | AES-256-CTR + HMAC-SHA256; PBKDF2-SHA256 |
| Compactação | AUTO, VaptVupt 2.65.13, LZHP, Store; níveis 1–9 |
| Opções de backup | Modo sólido ou desduplicação por blocos, mutuamente exclusivos |
| Inspeção | Formato/trailer, UUID, flags, metadados criptográficos, tamanhos e blocos |
| Implantação | Imagem Docker em três estágios, sem root e com raiz somente leitura |

O Android usa o formato independente `zupt-android/v1.3`, com STORE/DEFLATE
bruto. Os arquivos desktop e Android não são intercambiáveis.

## Configuração

As variáveis `ZUPT_*` têm precedência sobre os nomes de compatibilidade
`VAPTVUPT_*` usados pelas versões 3.0.0–5.2.1.

| Variável | Padrão | Finalidade |
|---|---:|---|
| `ZUPT_MAX_UPLOAD_MB` | `512` | Limite da requisição em MiB |
| `ZUPT_KEY_TTL_SEC` | `14400` | Retenção de tarefas e chaves em segundos |
| `ZUPT_SECRET_KEY` | gerada no início | Segredo do Flask |
| `ZUPT_COMPRESS_TIMEOUT` | `600` | Tempo de compactação, 1–600 segundos |
| `ZUPT_EXTRACT_TIMEOUT` | `600` | Tempo de extração/verificação, 1–600 segundos |
| `ZUPT_COOKIE_SECURE` | `0` | Use `1` quando o navegador acessar exclusivamente por HTTPS |

O contêiner usa `ZUPT_BIN=/usr/local/bin/zupt` e
`ZUPT_WORKDIR=/tmp/zupt-work`, um tmpfs de 2 GiB com modo 0700. Executa como
UID 1001, remove todas as capabilities, ativa `no-new-privileges` e limita
memória a 4 GiB e processos a 256. A aplicação permite até 600 segundos por
operação; o Gunicorn espera 660 segundos. Outros launchers podem definir
`ZUPT_BIN` e `ZUPT_WORKDIR` diretamente.

As senhas chegam ao CLI pela entrada padrão herdada (`--pass-fd 0`), não
pelos argumentos do processo. Os formulários usam CSRF; cada operação tem
diretório isolado e downloads de chaves expiram. Essas medidas reduzem riscos;
uploads continuam sendo entrada não confiável. Salve as chaves necessárias
antes de parar o contêiner: o conteúdo do tmpfs desaparece com ele.

## Verificação

```sh
curl -fsS http://127.0.0.1:8181/healthz
# {"ok":true,"service":"zupt-web","version":"5.2.13"}
curl -fsS http://127.0.0.1:8181/version
docker exec zupt-web zupt version
```

O `/healthz` informa que o processo está ativo. O `/version` verifica a
prontidão do CLI e retorna 503 quando o binário está indisponível.
`/usr/local/bin/vaptvupt` permanece como alias para scripts antigos.

## Compatibilidade na atualização

Este perfil compilado do fonte exclui o `libvuptsdk` opaco usado pelo ZUPT Web
5.2.1. Os modos nativos por senha, `--pq` e `--pq-only` continuam disponíveis.
Arquivos Argon2id ou `--pq-sdk` do 5.2.1 precisam do leitor daquela versão.
Preserve o ambiente de recuperação e os originais até restaurar, conferir e
criptografar novamente os arquivos. Consulte [MIGRATION.md](MIGRATION.md).

## Desenvolvimento e CI

```sh
./build-zupt.sh --verify-only
python3 -m venv .venv
.venv/bin/pip install --require-hashes -r requirements.txt
.venv/bin/python -m unittest discover -s tests -v
shellcheck setup.sh build-zupt.sh
docker compose config --quiet
```

O verificador aceita LF exato ou sua transformação CRLF pura e determinística
somente nos dois caminhos batch Windows declarados pelo upstream. Outras
transformações, finais mistos, travessia, duplicatas e symlinks falham. Os testes
históricos usam o manifesto de cada tag; um pacote sem histórico Git não
executa os dois testes de integração Git.

O `./build-zupt.sh` verifica e compila o CLI, executa `make check`, remove
símbolos e rejeita RPATH/RUNPATH. A matriz completa está em [AUDIT.md](AUDIT.md);
a verificação de assinatura do fonte e o manifesto dos 294 arquivos estão em
[UPSTREAM.md](UPSTREAM.md). Resultados do núcleo não validam o serviço web.

A CI atende `main`, `5.2.13`, pull requests e execução manual. A imagem depende
dos jobs Web e CLI. Somente após o inventário da imagem e os testes HTTP dos
modos criptográficos passarem, exporta um artefato Docker com `SHA256SUMS`,
`COMMIT` Web e metadados. O artefato não é uma implantação em produção. O
Compose aceita `VCS_REF` para o rótulo de revisão; a CI usa o commit testado.

## Projeto e licenças

- [ZUPT CLI/GUI](https://github.com/cristiancmoises/zupt)
- [Espelho GitHub](https://github.com/cristiancmoises/zupt-web)
- [Espelho Codeberg](https://codeberg.org/berkeley/zupt-web)
- [Codec VaptVupt](https://git.securityops.co/cristiancmoises/vaptvupt-codec)

O ZUPT Web usa [AGPL-3.0-or-later](LICENSE). O fonte incluído tem escopos
AGPL-3.0-or-later, GPL-3.0-or-later, BSD-2-Clause, BSD-3-Clause e CC0-1.0
identificados separadamente. Preserve `LICENSE*`, `NOTICE` e
[THIRD-PARTY-NOTICES.md](zupt-5.2.10/THIRD-PARTY-NOTICES.md). Operadores de um
serviço de rede modificado devem cumprir as exigências da AGPL sobre acesso
ao código-fonte. Contato para licenciamento comercial: `sac@securityops.co`.
