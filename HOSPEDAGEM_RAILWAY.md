# Railway — Silver City RP 2º Batalhão

1. Crie um repositório **privado** no GitHub e envie os arquivos deste ZIP (não envie `.env` nem chaves).
2. Entre em https://railway.com e crie um projeto ligado ao repositório.
3. Defina o comando de inicialização **`python run_cloud.py`**.
4. Em **Variables**, cadastre:
   - `BATALHAO=2º Batalhão | Silver City RP`
   - `DISCORD_TOKEN` = token EXCLUSIVO deste bot.
   - `DISCORD_GUILD_ID` = ID do Discord EXCLUSIVO deste batalhão.
   - `GOOGLE_SHEET_ID` = ID de uma planilha **Google Sheets nativa** deste batalhão.
   - `GOOGLE_CREDENTIALS_JSON` = conteúdo JSON completo da conta de serviço Google.
   - `CARGOS_EDICAO`, `CARGOS_COMANDO` e `CARGOS_CONSULTA` = IDs dos cargos permitidos, separados por vírgula (opcional; administradores podem publicar o painel).
   - `CANAL_LOGS_ID` = ID do canal de logs gerais (opcional, `0` para nenhum).
   - `CANAL_ADVERTENCIAS_ID` = ID do canal de advertências (opcional, `0` para usar o canal geral se configurado).
   - `CANAL_DENUNCIAS_ID` = ID do canal das denúncias (**opcional, `0` até escolher**).
   - `CARGO_CADASTRADO_ID` = ID do cargo a atribuir no auto-registro (**opcional, `0` até escolher**).
   - `PATENTE_INICIAL=RECRUTA`
   - `UNIDADE_INICIAL=BOPE`
5. Na configuração do serviço, deixe **uma réplica** para evitar duplicação de badges, e use execução contínua (desative inatividade/serverless).
6. Abra os logs de deploy, confirme o login e teste `/cadastrar` no servidor. Caso o comando não apareça, verifique os escopos `bot` e `applications.commands` no convite do bot.
7. Para atribuição automática de cargo/apelido, posicione o cargo do bot acima do cargo cadastrado e permita **Gerenciar cargos** e **Gerenciar apelidos**.

**IMPORTANTE**: o JSON da conta de serviço e o token Discord são segredos. Não os envie no chat e não grave no GitHub. Não conecte os dois bots ao mesmo `GOOGLE_SHEET_ID` se desejar cadastros independentes.
