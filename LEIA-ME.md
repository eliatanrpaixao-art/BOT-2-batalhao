# Silver City RP — Bot do 2º Batalhão (BOPE)

Este ZIP contém o projeto **EXCLUSIVO do 2º Batalhão**, que opera no seu servidor do Discord e em sua própria planilha Google Sheets. **Não está online** até você criar o bot e realizar a configuração.

## Novo `/cadastrar` (painel público)

**Somente administradores e cargos `CARGOS_EDICAO`/`CARGOS_COMANDO` podem publicar o painel** no canal. Depois que ele é publicado, qualquer membro do servidor pode usar os dois botões:

- **Registro**: abre um modal pedindo *Nome no jogo* e *ID*. O bot valida o ID, bloqueia cadastro repetido por conta Discord e por ID do GTA, seleciona o próximo badge de **3 dígitos** (001, 002, 003...), e preenche automaticamente as colunas `A:H` de `EFETIVO`. A patente padrão é `RECRUTA`, a unidade é `BOPE`, a situação é `ATIVO`, o campo `ENTRADA` recebe a data e `DISCORD` recebe o ID da conta. O bot tenta alterar o apelido para `Nome | ID` e atribuir `CARGO_CADASTRADO_ID`.
- **Pesquisa**: abre um modal pedindo somente o ID. A ficha com os dados do `EFETIVO` é enviada **somente ao usuário que pesquisou**, como mensagem efêmera do Discord. A ficha contém o botão **Denunciar erro?**.
- **Denunciar erro?**: abre um campo para explicar o erro. Registra a denúncia, a ficha pesquisada e o perfil do denunciante em uma aba `DENÚNCIAS` na planilha. Com `CANAL_DENUNCIAS_ID` configurado, envia um embed ao canal e marca `ENVIADA`; enquanto não estiver configurado, mantém `PENDENTE` para conferência posterior. **Denúncias pendentes já registradas não são reenviadas automaticamente** quando um canal for informado depois; consulte a aba `DENÚNCIAS`.

## Outras funções já existentes

`/consultar`, `/resumo`, `/promover`, `/situacao`, `/unidade`, `/curso`, `/advertir` e `/medalha` continuam disponíveis, respeitando as permissões por cargo. O comando antigo `/cadastrar` com 5 campos foi substituído pelo painel de botões.

## Log automático do comando `/advertir`

O comando continua solicitando **ID, motivo, punição e duração (dias)** como antes. Após a confirmação da gravação nas abas `ADVERTÊNCIAS` e `REGISTROS`, publica uma mensagem embed com **nome, ID, badge, patente, unidade, motivo, punição, data, vencimento e o administrador responsável**.

- `CANAL_ADVERTENCIAS_ID`: ID do canal exclusivo de logs de advertência deste servidor. Deixe `0` enquanto não estiver definido.
- Se estiver `0`, o bot usa `CANAL_LOGS_ID` (caso já exista um canal geral de logs).
- Se os dois estiverem `0`, o registro **continua salvo na planilha** e o comando avisa discretamente ao executor que o envio ao Discord não foi configurado.
- Caso o canal configurado seja inacessível, a advertência **não é duplicada nem desfeita**. O bot informa que a planilha foi atualizada e que o aviso precisa ser conferido manualmente.
- Logs antigos não são enviados retroativamente. Cada advertência nova gera **um único log** no canal selecionado.
- Dê ao bot as permissões **Ver canal**, **Enviar mensagens** e **Inserir links (embeds)** no canal escolhido. O comando `/advertir` continua exclusivo dos cargos de comando.

## Estrutura da planilha exigida

A planilha deve ser **Google Sheets nativo** (não apenas `.xlsx`/`.xlsm` armazenado no Drive), com as abas `EFETIVO`, `REGISTROS`, `CURSOS`, `MEDALHAS`, `ADVERTÊNCIAS` e `BOPE`. A **linha 8 é o cabeçalho**, os dados começam na **linha 9** e a aba `EFETIVO` usa as colunas:

| Coluna | Dado | Origem no cadastro |
|---|---|---|
| A | ID | Informado no modal |
| B | NOME NO RP | Informado no modal |
| C | BADGE | Gerado pelo bot como texto `001`...`999` |
| D | PATENTE | `PATENTE_INICIAL` |
| E | GUARNIÇÃO | `UNIDADE_INICIAL` (BOPE) |
| F | SITUAÇÃO | `ATIVO` |
| G | ENTRADA | Data atual, fuso America/Belem |
| H | DISCORD | ID numérico da conta Discord, armazenado como texto |

As demais colunas e fórmulas são preservadas. As outras abas recebem seus registros pela integração anterior. O bot **não marca cursos como concluídos** quando o usuário se cadastra.

### Atenção aos cadastros antigos

Se policiais já cadastrados manualmente estiverem com a coluna `H (DISCORD)` vazia, preencha o ID correto do Discord em `H`. Assim o bot os reconhecerá e não permitirá outro registro. O bloqueio por ID de jogo já funciona automaticamente.

## Como instalar

1. Crie uma **aplicação Discord** dedicada ao 2º Batalhão em https://discord.com/developers/applications, ative o bot e salve seu token **em segredo**.
2. Convide o bot apenas para o servidor do 2º Batalhão com `bot` e `applications.commands`. Configure permissões de **Ver canais**, **Enviar mensagens**, **Inserir links**, **Gerenciar apelidos** e **Gerenciar cargos** conforme necessário.
3. O cargo do bot precisa ficar **acima do cargo que ele adicionará** e acima dos membros cujos apelidos deve editar. Ele não poderá editar o apelido do dono do servidor.
4. Converta a planilha do 2º Batalhão para **Google Planilhas**, copie o ID da URL e dê acesso de **Editor** ao endereço `client_email` da conta de serviço Google, de forma restrita.
5. Ajuste as variáveis do `.env.exemplo`. Execute localmente com `pip install -r requirements.txt` e `python bot.py`, ou hospede no Railway com `python run_cloud.py` e as variáveis de ambiente, conforme `HOSPEDAGEM_RAILWAY.md`.
6. Vá ao canal desejado com a conta de Comando/RH, envie **`/cadastrar`** e teste os dois botões.

## Variáveis novas

| Nome | Exemplo | Observação |
|---|---|---|
| `CARGO_CADASTRADO_ID` | `123456789...` | Cargo atribuído ao registrar; `0` = não atribuir ainda |
| `CANAL_DENUNCIAS_ID` | `123456789...` | Canal de denúncias; `0` = gravar na aba e deixar pendente |
| `PATENTE_INICIAL` | `RECRUTA` | Patente inserida no primeiro cadastro |
| `UNIDADE_INICIAL` | `BOPE` | Unidade inserida no primeiro cadastro |

## Segurança e confiabilidade

- Nunca publique o token Discord ou a chave JSON da conta de serviço no repositório.
- O painel público não expõe os resultados de pesquisa; somente quem acionou o modal recebe o retorno.
- Cadastro único é validado por Discord ID e por ID do jogo contra o banco desta instância.
- Para garantir badges sem conflito sob cadastros simultâneos, **rode uma única réplica/instância por planilha**. Uma trava interna protege concorrência dentro desse processo, mas duas réplicas diferentes podem disputar o mesmo número.
- A conta de serviço não deve ser compartilhada publicamente; os dados da planilha podem ser pessoais.
- Se faltarem permissões do Discord, o registro ainda será salvo, mas a resposta avisará que o cargo ou apelido precisa de ajuste manual.
- Nomes precisam caber no limite de 32 caracteres do apelido `Nome | ID`.

## Testes

`python teste_painel_offline.py` testa badge crescente, reuso indevido, conta/ID duplicados, limites de nickname e concorrência local sem conexão à API. Esses testes não substituem um teste real em um servidor Discord + Google Sheets.
