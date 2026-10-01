<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# ZUPT Web 5.2.12

[English](README.md) | [Português do Brasil](README.pt-BR.md)

O ZUPT Web é uma interface web auto-hospedada para o arquivador ZUPT. Ele
compacta, criptografa, verifica, inspeciona e extrai arquivos `.zupt` sem conta
externa nem armazenamento em nuvem.

O Web 5.2.12 inclui a fonte desktop corrigida e fixada em [UPSTREAM.md](UPSTREAM.md).
As tags imutáveis Web 5.2.10 e 5.2.11 permanecem históricas e inalteradas;
o Web 5.2.10 mantém sua falha conhecida de manifesto nos finais de linha do
checkout. O limite exato entre checkout Git e exportação de código-fonte
introduzido no Web 5.2.11 é preservado.
Somente os dois arquivos batch Windows declarados aceitam LF exato ou CRLF
puro determinístico; finais mistos e adulteração falham. Os demais bytes e a
lista completa de arquivos permanecem exatos. O CLI incluído é ZUPT 5.2.10 com o codec
VaptVupt 2.65.13. A atualização prepara somente os buckets alcançáveis do matcher
para entradas de até 4 KiB e sua pré-passagem inicial nos modos com entropia da
implementação desktop incluída. Testes de igualdade exata da saída e roundtrip
verificam a compatibilidade. A fonte desktop corrigida desativa o eco do terminal
POSIX antes de exibir a solicitação de senha e restaura o estado do terminal
após interrupções por sinal. As senhas web continuam usando o descritor herdado,
sem passar pela linha de comando. O formato desktop ZUPT v1.6, as rotas web e os modos criptográficos
não mudaram em relação ao ZUPT Web 5.2.9. O Android usa o formato independente
`zupt-android/v1.3`, com STORE e DEFLATE bruto; os arquivos não são intercambiáveis.

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

O endpoint de saúde deve informar `5.2.12`. O endpoint `/version` responde com
HTTP 503 quando o binário do ZUPT não está pronto; ele não mascara essa falha
como sucesso.

## Recursos

| Recurso | Implementação |
|---|---|
| Criptografia híbrida | ML-KEM-768 + X25519 por `--pq` |
| Criptografia somente pós-quântica | ML-KEM-768 por `--pq-only` |
| Criptografia por senha | AES-256-CTR + HMAC-SHA256 e PBKDF2-SHA256 |
| Compactação | AUTO, VaptVupt 2.65.13, LZHP ou Store |
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

O diretório `zupt-5.2.10/` contém a árvore-fonte completa sincronizada do
release corrigido. Consulte [UPSTREAM.md](UPSTREAM.md) para a proveniência.
`build-zupt.sh` verifica todos os arquivos do manifesto antes de compilar. Para
validar a aplicação localmente:

```sh
python3 -m venv .venv
.venv/bin/pip install --require-hashes -r requirements.txt
.venv/bin/python -m unittest discover -s tests -v
docker compose config --quiet
docker build --tag zupt-web:5.2.12 .
```

Os dois testes de integração checkout/exportação de tag exigem Git e o histórico
imutável `v5.2.10` e `v5.2.11` desta árvore. Cada snapshot histórico usa seu
próprio manifesto: a exportação inválida conhecida da v5.2.10 é rejeitada,
e a exportação corrigida da v5.2.11 passa. Pacotes de código-fonte sem metadados Git
informam exatamente esses dois testes como ignorados explicitamente; os demais
26 continuam sendo executados. Com esse histórico Git, os 28 são executados.

Os resultados executados para esta revisão ficam consolidados em
[AUDIT.md](AUDIT.md); um teste não executado ou bloqueado não é tratado como
aprovação.

## Licenças

O ZUPT Web usa AGPL-3.0-or-later. O código-fonte incluído possui escopos
AGPL-3.0-or-later, GPL-3.0-or-later, BSD-2-Clause, BSD-3-Clause e CC0-1.0
identificados separadamente. Preserve `LICENSE*`, `NOTICE` e
`THIRD-PARTY-NOTICES.md` ao redistribuir.

Contato para licenciamento comercial: `sac@securityops.co`.
