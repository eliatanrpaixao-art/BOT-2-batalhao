"""Núcleo dos bots Silver City RP.

Cada processo é configurado com um token, um único guild_id e um único
spreadsheet_id. Não execute os dois bots com o mesmo arquivo .env.
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Optional
from zoneinfo import ZoneInfo

import discord
import gspread
from discord import app_commands
from dotenv import load_dotenv

LOG = logging.getLogger("silver-city")
RED = 0xC7133A
ZONE = ZoneInfo("America/Belem")
UNIDADES = ("BOPE", "GRI", "SPEED", "GRAER", "GTM", "GRT", "PATRULHA")
SITUACOES = ("ATIVO", "AFASTADO", "FÉRIAS", "RESERVA")
CURSO_SITUACOES = ("CONCLUÍDO", "EM ANDAMENTO", "PENDENTE", "REPROVADO")


class ErroNegocio(Exception):
    """Erro de validação legível para o usuário."""


def data_hoje() -> str:
    return datetime.now(ZONE).strftime("%d/%m/%Y")


def normalizar_id(value: object) -> str:
    texto = str(value or "").strip()
    if texto.endswith(".0") and texto[:-2].isdigit():
        texto = texto[:-2]
    if not texto.isdigit() or int(texto) <= 0:
        raise ErroNegocio("O ID deve ser um número inteiro positivo.")
    return str(int(texto))


def valor(row: list[str], index: int) -> str:
    return str(row[index]).strip() if len(row) > index else ""


def esc_aba(name: str) -> str:
    return "'" + name.replace("'", "''") + "'"


@dataclass(frozen=True)
class Config:
    batalhao: str
    token: str
    guild_id: int
    spreadsheet_id: str
    credentials_file: Path
    cargos_consulta: frozenset[int]
    cargos_edicao: frozenset[int]
    cargos_comando: frozenset[int]
    canal_logs: int
    canal_advertencias: int
    canal_denuncias: int
    cargo_registrado: int
    patente_inicial: str
    unidade_inicial: str


def ids_env(value: str) -> frozenset[int]:
    return frozenset(int(part.strip()) for part in value.split(",") if part.strip())


def carregar_config(env_file: Path) -> Config:
    load_dotenv(dotenv_path=env_file, override=True)
    faltantes = [name for name in ("DISCORD_TOKEN", "DISCORD_GUILD_ID", "GOOGLE_SHEET_ID")
                 if not os.getenv(name, "").strip()]
    if faltantes:
        raise RuntimeError("Configure as variáveis no .env: " + ", ".join(faltantes))
    credentials_file = (env_file.parent / os.getenv("GOOGLE_CREDENTIALS_FILE", "credenciais.json")).resolve()
    if not credentials_file.is_file():
        raise RuntimeError(f"Credencial Google não encontrada: {credentials_file}")
    return Config(
        batalhao=os.getenv("BATALHAO", "Silver City"),
        token=os.environ["DISCORD_TOKEN"],
        guild_id=int(os.environ["DISCORD_GUILD_ID"]),
        spreadsheet_id=os.environ["GOOGLE_SHEET_ID"].strip(),
        credentials_file=credentials_file,
        cargos_consulta=ids_env(os.getenv("CARGOS_CONSULTA", "")),
        cargos_edicao=ids_env(os.getenv("CARGOS_EDICAO", "")),
        cargos_comando=ids_env(os.getenv("CARGOS_COMANDO", "")),
        canal_logs=int(os.getenv("CANAL_LOGS_ID", "0") or "0"),
        canal_advertencias=int(os.getenv("CANAL_ADVERTENCIAS_ID", "0") or "0"),
        canal_denuncias=int(os.getenv("CANAL_DENUNCIAS_ID", "0") or "0"),
        cargo_registrado=int(os.getenv("CARGO_CADASTRADO_ID", "0") or "0"),
        patente_inicial=os.getenv("PATENTE_INICIAL", "RECRUTA").strip().upper(),
        unidade_inicial=os.getenv("UNIDADE_INICIAL", "BOPE").strip().upper(),
    )


class Planilha:
    """Interface com a planilha nativa Google Sheets, sem alterar estilos.

    Colunas com fórmulas existentes são deixadas intactas:
      REGISTROS E/G, CURSOS B, MEDALHAS B, ADVERTÊNCIAS B/C/D/J.
    """

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.client = gspread.service_account(
            filename=str(cfg.credentials_file),
            scopes=["https://www.googleapis.com/auth/spreadsheets"],
        )
        self.book = self.client.open_by_key(cfg.spreadsheet_id)
        self._cache: dict[str, gspread.Worksheet] = {}
        self.lock = threading.RLock()
        self._check_layout()

    def aba(self, name: str) -> gspread.Worksheet:
        if name not in self._cache:
            self._cache[name] = self.book.worksheet(name)
        return self._cache[name]

    def _check_layout(self) -> None:
        esperados = {
            "EFETIVO": ["ID", "NOME NO RP", "BADGE", "PATENTE", "GUARNIÇÃO", "SITUAÇÃO"],
            "REGISTROS": ["DATA", "TIPO", "SUBTIPO", "APLICADOR", "RECEPTOR", "ID RECEPTOR"],
            "CURSOS": ["ID POLICIAL", "NOME RP", "CURSO"],
            "ADVERTÊNCIAS": ["ID POLICIAL", "NOME RP", "BADGE", "PATENTE"],
            "MEDALHAS": ["ID POLICIAL", "NOME RP", "CONDECORAÇÃO"],
        }
        for nome, esperado in esperados.items():
            atual = self.aba(nome).row_values(8)
            if [x.strip().upper() for x in atual[:len(esperado)]] != esperado:
                raise RuntimeError(f"Cabeçalho inesperado em {nome}!8. Não foi alterado nenhum dado.")
        # Verificação extra: ambos os arquivos possuem a unidade BOPE.
        self.aba("BOPE")

    def _bloco(self, aba: str, start: int, end: int, columns: str) -> list[list[str]]:
        return self.aba(aba).get(f"A{start}:{columns}{end}")

    def _localizar(self, id_policia: int) -> tuple[int, list[str]]:
        alvo = normalizar_id(id_policia)
        sh = self.aba("EFETIVO")
        rows = self._bloco("EFETIVO", 9, sh.row_count, "J")
        achados = [(i + 9, row) for i, row in enumerate(rows)
                   if valor(row, 0).isdigit() and normalizar_id(valor(row, 0)) == alvo]
        if not achados:
            raise ErroNegocio(f"ID {alvo} não encontrado no {self.cfg.batalhao}.")
        if len(achados) > 1:
            raise ErroNegocio(f"Há IDs {alvo} repetidos na aba EFETIVO. Corrija antes de editar.")
        return achados[0]

    def _primeira_livre(self, aba: str, col: str = "A") -> int:
        sh = self.aba(aba)
        values = sh.get(f"{col}9:{col}{sh.row_count}")
        for r in range(9, sh.row_count + 1):
            offset = r - 9
            if offset >= len(values) or not valor(values[offset], 0):
                return r
        raise ErroNegocio(f"A aba {aba} está sem linhas livres. Amplie o espaço na planilha.")

    def _faixa(self, aba: str, celula: str, matriz: list[list[object]]) -> dict:
        # Não interpretar textos enviados por usuários como fórmulas de Planilhas.
        seguro = [[("'" + v if isinstance(v, str) and v.lstrip().startswith(("=", "+", "-", "@")) else v)
                   for v in linha] for linha in matriz]
        return {"range": f"{esc_aba(aba)}!{celula}", "values": seguro}

    def _registrar(self, tipo: str, subtipo: str, operador: str,
                   id_policia: int, detalhe: str) -> list[dict]:
        r = self._primeira_livre("REGISTROS", "F")
        # E = nome e G = unidade já são fórmulas automáticas; não tocar.
        return [
            self._faixa("REGISTROS", f"A{r}:D{r}", [[data_hoje(), tipo, subtipo, operador]]),
            self._faixa("REGISTROS", f"F{r}", [[id_policia]]),
            self._faixa("REGISTROS", f"H{r}", [[detalhe]]),
        ]

    def _gravar(self, ranges: list[dict]) -> None:
        # Google Sheets values.batchUpdate grava múltiplas abas em uma requisição.
        self.book.values_batch_update({"valueInputOption": "USER_ENTERED", "data": ranges})

    def consultar(self, id_policia: int) -> dict[str, str]:
        with self.lock:
            _, row = self._localizar(id_policia)
            keys = ["id", "nome", "badge", "patente", "unidade", "situacao", "entrada", "discord"]
            return {k: valor(row, i) for i, k in enumerate(keys)}

    def consultar_completo(self, id_policia: str) -> dict[str, str]:
        """Retorna todos os 21 campos do efetivo, sem alterar estilos ou fórmulas."""
        with self.lock:
            n, _ = self._localizar(id_policia)
            cab = self.aba("EFETIVO").row_values(8)
            row = self.aba("EFETIVO").row_values(n)
            result = {}
            for i, header in enumerate(cab[:21]):
                if header.strip():
                    field = valor(row, i)
                    if header.strip().upper() == "BADGE" and field.isdigit():
                        field = str(int(field)).zfill(3)
                    result[header.strip().upper()] = field or "—"
            return result

    @staticmethod
    def _badge_seguinte(rows: list[list[str]]) -> str:
        numeros = [int(valor(row, 2)) for row in rows
                   if valor(row, 2).isdigit() and 0 < int(valor(row, 2)) <= 999]
        prox = max(numeros, default=0) + 1
        if prox > 999:
            raise ErroNegocio("Limite de 999 badges atingido. Contate a administração.")
        return f"{prox:03d}"

    def cadastrar_auto(self, id_policia: str, nome: str, discord_id: str, operador: str) -> dict[str, str]:
        """Auto-registro: ID+usuário únicos, badge crescente, início no BOPE.

        Uma única instância de bot deve acessar esta planilha para evitar
        cadastros concorrentes em réplicas diferentes. O lock protege as
        interações simultâneas DENTRO do processo.
        """
        with self.lock:
            id_str = normalizar_id(id_policia)
            if not discord_id.isdigit():
                raise ErroNegocio("ID da conta Discord inválido.")
            nome = " ".join(nome.strip().split())
            if len(nome) < 2 or len(nome) > 80:
                raise ErroNegocio("O nome no RP deve ter entre 2 e 80 caracteres.")
            # Discord aceita até 32 caracteres para apelidos; não truncar o nome.
            if len(f"{nome} | {id_str}") > 32:
                raise ErroNegocio("Nome muito longo para o apelido do Discord. "
                                  "Use um nome que caiba em 32 caracteres junto com ' | ID'.")
            if self.cfg.unidade_inicial not in UNIDADES:
                raise ErroNegocio("Unidade inicial inválida na configuração do bot.")
            sh = self.aba("EFETIVO")
            all_rows = self._bloco("EFETIVO", 9, sh.row_count, "J")
            first_blank = None
            for idx in range(sh.row_count - 8):
                row = all_rows[idx] if idx < len(all_rows) else []
                raw_id = valor(row, 0)
                raw_discord = valor(row, 7).strip().replace('<@', '').replace('>', '').replace('!', '')
                if raw_discord and raw_discord == discord_id:
                    raise ErroNegocio("Você já possui cadastro neste batalhão e não pode se cadastrar novamente.")
                try:
                    existe_id = bool(raw_id and normalizar_id(raw_id) == id_str)
                except ErroNegocio:
                    existe_id = False
                if existe_id:
                    raise ErroNegocio(f"O ID {id_str} já está cadastrado neste batalhão. Peça correção à administração.")
                if first_blank is None and not any(valor(row, i) for i in range(10)):
                    first_blank = idx + 9
            if first_blank is None:
                raise ErroNegocio("O EFETIVO está sem linhas livres. Amplie a tabela antes de registrar.")
            badge = self._badge_seguinte(all_rows)
            # Não reutilizar badges anteriores citados no histórico de cadastros.
            import re
            historico = self._bloco("REGISTROS", 9, self.aba("REGISTROS").row_count, "H")
            antigos = [int(m.group(1)) for registro in historico
                       for m in re.finditer(r"\bBadge\s+(\d{1,3})\b", valor(registro, 7), re.I)]
            ultimo = max([int(badge) - 1, *antigos])
            if ultimo >= 999:
                raise ErroNegocio("O limite de 999 badges já foi atingido.")
            badge = f"{ultimo + 1:03d}"
            # Badge gravado como STRING via updateCells para preservar 001, 002 etc.
            # Mantém toda a formatação da célula (altera somente userEnteredValue).
            from datetime import date
            excel_day = (datetime.now(ZONE).date() - date(1899, 12, 30)).days
            field_values = [
                {"numberValue": int(id_str)},
                {"stringValue": nome},
                {"stringValue": badge},
                {"stringValue": self.cfg.patente_inicial},
                {"stringValue": self.cfg.unidade_inicial},
                {"stringValue": "ATIVO"},
                {"numberValue": excel_day},
                {"stringValue": discord_id},
            ]
            self.book.batch_update({"requests": [{"updateCells": {
                "range": {"sheetId": sh.id, "startRowIndex": first_blank - 1,
                          "endRowIndex": first_blank, "startColumnIndex": 0, "endColumnIndex": 8},
                "rows": [{"values": [{"userEnteredValue": v} for v in field_values]}],
                "fields": "userEnteredValue",
            }}]})
            try:
                self._gravar(self._registrar("CADASTRO", "Auto-registro", operador, int(id_str),
                                            f"{nome} | Badge {badge} | Discord {discord_id}"))
            except Exception:
                LOG.exception("Cadastro salvo, mas falhou histórico REGISTROS do ID %s", id_str)
            return {"id": id_str, "nome": nome, "badge": badge,
                    "patente": self.cfg.patente_inicial, "unidade": self.cfg.unidade_inicial,
                    "situacao": "ATIVO", "linha": str(first_blank)}

    def salvar_denuncia(self, ficha: dict[str, str], perfil: dict[str, str], motivo: str) -> int:
        """Salva a denúncia mesmo sem canal configurado, para não perdê-la."""
        with self.lock:
            if not motivo.strip() or len(motivo.strip()) < 8:
                raise ErroNegocio("Descreva o erro com pelo menos 8 caracteres.")
            try:
                sh = self.aba("DENÚNCIAS")
            except gspread.WorksheetNotFound:
                sh = self.book.add_worksheet(title="DENÚNCIAS", rows=500, cols=9)
                self._cache["DENÚNCIAS"] = sh
                sh.update("A1:I1", [["DATA", "ID PESQUISADO", "NOME NO RP", "USUÁRIO DISCORD",
                                     "DISCORD ID", "APELIDO DISCORD", "ERRO REPORTADO", "STATUS", "AVATAR URL"]])
                self.book.batch_update({"requests": [{"repeatCell": {
                    "range": {"sheetId": sh.id, "startRowIndex": 0, "endRowIndex": 1,
                              "startColumnIndex": 0, "endColumnIndex": 9},
                    "cell": {"userEnteredFormat": {"backgroundColor": {"red": 0.78, "green": 0.07, "blue": 0.23},
                                                       "textFormat": {"bold": True, "foregroundColor": {"red": 1, "green": 1, "blue": 1}}}},
                    "fields": "userEnteredFormat",
                }}]})
                sh.freeze(rows=1)
            # Denúncias começam logo abaixo do cabeçalho (linha 2).
            registros = sh.get(f"A2:A{sh.row_count}")
            linha = next((idx + 2 for idx, item in enumerate(registros)
                          if not valor(item, 0)), max(2, len(registros) + 2))
            if linha > sh.row_count:
                sh.add_rows(100)
            values = [[data_hoje(), ficha.get("ID", ""), ficha.get("NOME NO RP", ""),
                       perfil.get("username", ""), perfil.get("id", ""),
                       perfil.get("display_name", ""), motivo.strip(), "PENDENTE",
                       perfil.get("avatar_url", "")]]
            sh.update(f"A{linha}:I{linha}", values, value_input_option="RAW")
            return linha

    def marcar_denuncia_enviada(self, linha: int) -> None:
        with self.lock:
            self.aba("DENÚNCIAS").update_acell(f"H{linha}", "ENVIADA")

    def resumo(self) -> dict[str, int]:
        with self.lock:
            rows = self._bloco("EFETIVO", 9, self.aba("EFETIVO").row_count, "F")
            validos = [r for r in rows if valor(r, 1)]
            return {"total": len(validos), "ativos": sum(valor(r, 5).upper() == "ATIVO" for r in validos),
                    "bope": sum(valor(r, 4).upper() == "BOPE" for r in validos),
                    "sem_situacao": sum(not valor(r, 5) for r in validos)}

    def cadastrar(self, id_policia: int, nome: str, badge: str, patente: str,
                  unidade: str, operador: str, discord_id: str = "") -> str:
        with self.lock:
            id_str = normalizar_id(id_policia)
            nome = nome.strip()
            if not nome or len(nome) > 100:
                raise ErroNegocio("O nome deve ter entre 1 e 100 caracteres.")
            if unidade not in UNIDADES:
                raise ErroNegocio("Unidade inválida.")
            rows = self._bloco("EFETIVO", 9, self.aba("EFETIVO").row_count, "C")
            for r in rows:
                if valor(r, 0).isdigit() and normalizar_id(valor(r, 0)) == id_str:
                    raise ErroNegocio("Este ID já está cadastrado.")
                if badge and valor(r, 2) == badge.strip() and valor(r, 1):
                    raise ErroNegocio("Este badge já está vinculado a outro policial.")
            linha = self._primeira_livre("EFETIVO", "A")
            self._gravar([
                self._faixa("EFETIVO", f"A{linha}:H{linha}",
                            [[int(id_str), nome, badge.strip(), patente.strip().upper(), unidade,
                              "ATIVO", data_hoje(), discord_id]]),
                *self._registrar("CADASTRO", "Novo policial", operador, int(id_str), nome),
            ])
            return f"Policial **{nome}** (ID {id_str}) cadastrado em **{unidade}**."

    def promover(self, id_policia: int, patente: str, operador: str) -> str:
        with self.lock:
            linha, row = self._localizar(id_policia)
            antiga = valor(row, 3) or "SEM PATENTE"
            nova = patente.strip().upper()
            if not nova or len(nova) > 70:
                raise ErroNegocio("Informe uma patente válida.")
            self._gravar([
                self._faixa("EFETIVO", f"D{linha}", [[nova]]),
                self._faixa("EFETIVO", f"I{linha}", [[data_hoje()]]),
                *self._registrar("PROMOÇÃO", nova, operador, id_policia, f"{antiga} → {nova}"),
            ])
            return f"**{valor(row, 1)}**: {antiga} → **{nova}**."

    def situacao(self, id_policia: int, situacao: str, operador: str) -> str:
        with self.lock:
            if situacao not in SITUACOES:
                raise ErroNegocio("Situação inválida.")
            linha, row = self._localizar(id_policia)
            self._gravar([
                self._faixa("EFETIVO", f"F{linha}", [[situacao]]),
                *self._registrar("SITUAÇÃO", situacao, operador, id_policia,
                                 f"{valor(row, 5) or 'NÃO INFORMADA'} → {situacao}"),
            ])
            return f"**{valor(row, 1)}** agora está: **{situacao}**."

    def unidade(self, id_policia: int, unidade: str, operador: str) -> str:
        with self.lock:
            if unidade not in UNIDADES:
                raise ErroNegocio("Unidade inválida.")
            linha, row = self._localizar(id_policia)
            self._gravar([
                self._faixa("EFETIVO", f"E{linha}", [[unidade]]),
                *self._registrar("TRANSFERÊNCIA INTERNA", unidade, operador, id_policia,
                                 f"{valor(row, 4) or 'SEM UNIDADE'} → {unidade}"),
            ])
            return f"**{valor(row, 1)}**: {valor(row, 4)} → **{unidade}**."

    def curso(self, id_policia: int, nome_curso: str, operador: str,
              situacao: str = "CONCLUÍDO", validade_dias: int = 0) -> str:
        with self.lock:
            _, membro = self._localizar(id_policia)
            if situacao not in CURSO_SITUACOES:
                raise ErroNegocio("Situação de curso inválida.")
            if not 0 <= validade_dias <= 3650:
                raise ErroNegocio("A validade deve estar entre 0 e 3650 dias.")
            linha = self._primeira_livre("CURSOS", "A")
            venc = (datetime.now(ZONE).date() + timedelta(days=validade_dias)).strftime("%d/%m/%Y") if validade_dias else ""
            self._gravar([
                self._faixa("CURSOS", f"A{linha}", [[id_policia]]),
                # A coluna B é preenchida pela fórmula existente na planilha.
                self._faixa("CURSOS", f"C{linha}:H{linha}",
                            [[nome_curso.strip(), valor(membro, 4), situacao, operador, data_hoje(), venc]]),
                *self._registrar("CURSO", nome_curso.strip(), operador, id_policia, situacao),
            ])
            return f"Curso **{nome_curso}** registrado para **{valor(membro, 1)}** ({situacao})."

    def advertir(self, id_policia: int, motivo: str, punicao: str,
                 duracao_dias: int, operador: str) -> str:
        with self.lock:
            _, membro = self._localizar(id_policia)
            if not 0 <= duracao_dias <= 3650:
                raise ErroNegocio("A duração deve estar entre 0 e 3650 dias.")
            if not motivo.strip() or not punicao.strip():
                raise ErroNegocio("Informe motivo e punição.")
            linha = self._primeira_livre("ADVERTÊNCIAS", "A")
            venc = (datetime.now(ZONE).date() + timedelta(days=duracao_dias)).strftime("%d/%m/%Y") if duracao_dias else ""
            self._gravar([
                self._faixa("ADVERTÊNCIAS", f"A{linha}", [[id_policia]]),
                # B/C/D/J contêm fórmulas, inclusive cálculo automático do status.
                self._faixa("ADVERTÊNCIAS", f"E{linha}:I{linha}",
                            [[motivo.strip(), punicao.strip(), data_hoje(), venc, operador]]),
                *self._registrar("ADVERTÊNCIA", punicao.strip(), operador, id_policia, motivo.strip()),
            ])
            return f"Advertência registrada para **{valor(membro, 1)}**."

    def medalha(self, id_policia: int, condecoracao: str, motivo: str, operador: str) -> str:
        with self.lock:
            _, membro = self._localizar(id_policia)
            if not condecoracao.strip() or not motivo.strip():
                raise ErroNegocio("Informe a condecoração e o motivo.")
            linha = self._primeira_livre("MEDALHAS", "A")
            self._gravar([
                self._faixa("MEDALHAS", f"A{linha}", [[id_policia]]),
                # B tem fórmula de consulta ao EFETIVO.
                self._faixa("MEDALHAS", f"C{linha}:G{linha}",
                            [[condecoracao.strip(), motivo.strip(), data_hoje(), operador, "ENTREGUE"]]),
                *self._registrar("MEDALHA", condecoracao.strip(), operador, id_policia, motivo.strip()),
            ])
            return f"Medalha **{condecoracao}** registrada para **{valor(membro, 1)}**."


def autorizado(interaction: discord.Interaction, cfg: Config, nivel: str) -> bool:
    if interaction.guild_id != cfg.guild_id or not isinstance(interaction.user, discord.Member):
        return False
    if interaction.user.guild_permissions.administrator:
        return True
    roles = {role.id for role in interaction.user.roles}
    if nivel == "consulta":
        permitidos = cfg.cargos_consulta | cfg.cargos_edicao | cfg.cargos_comando
    elif nivel == "edicao":
        permitidos = cfg.cargos_edicao | cfg.cargos_comando
    else:
        permitidos = cfg.cargos_comando
    return bool(roles & permitidos)


def operador_de(interaction: discord.Interaction) -> str:
    return f"{interaction.user.display_name} ({interaction.user.id})"


def criar_bot(cfg: Config) -> discord.Client:
    intents = discord.Intents.default()
    intents.message_content = False

    class Cliente(discord.Client):
        async def setup_hook(self) -> None:
            # Registrados APENAS no servidor autorizado e para esta aplicação.
            guild = discord.Object(id=cfg.guild_id)
            self.add_view(portal.painel())
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            LOG.info("Comandos sincronizados para %s (%d)", cfg.batalhao, cfg.guild_id)

    client = Cliente(intents=intents)
    client.tree = app_commands.CommandTree(client)
    service: Optional[Planilha] = None
    startup_lock = asyncio.Lock()

    async def get_service() -> Planilha:
        nonlocal service
        async with startup_lock:
            if service is None:
                service = await asyncio.to_thread(Planilha, cfg)
            return service

    async def log_portal(interaction: discord.Interaction, texto: str) -> None:
        if not cfg.canal_logs:
            return
        canal = client.get_channel(cfg.canal_logs)
        if not isinstance(canal, discord.TextChannel) or canal.guild.id != cfg.guild_id:
            return
        try:
            await canal.send(f"🟥 **{cfg.batalhao}** · {texto}\nPor: {interaction.user.mention}",
                             allowed_mentions=discord.AllowedMentions.none())
        except discord.DiscordException:
            LOG.warning("Não consegui enviar log para o canal %s", cfg.canal_logs)

    from portal_cadastro import Portal
    portal = Portal(client, cfg, get_service, log_portal)

    async def executar(interaction: discord.Interaction, nivel: str,
                       job: Callable[[], object], descricao: str) -> None:
        nonlocal service
        if not autorizado(interaction, cfg, nivel):
            await interaction.response.send_message(
                "Você não tem permissão ou está no servidor incorreto.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            async with startup_lock:
                if service is None:
                    service = await asyncio.to_thread(Planilha, cfg)
            result = await asyncio.to_thread(job)
            texto = str(result)
            await interaction.followup.send(texto, ephemeral=True)
            if cfg.canal_logs and nivel != "consulta":
                channel = client.get_channel(cfg.canal_logs)
                if isinstance(channel, discord.TextChannel) and channel.guild.id == cfg.guild_id:
                    try:
                        await channel.send(
                            f"🟥 **{cfg.batalhao}** · {descricao}\n"
                            f"Por: {interaction.user.mention} (`{interaction.user.id}`)\n"
                            f"Resultado: {texto}", allowed_mentions=discord.AllowedMentions.none())
                    except discord.DiscordException:
                        LOG.warning("Falha ao publicar log no canal %d", cfg.canal_logs)
        except ErroNegocio as err:
            await interaction.followup.send(f"⚠️ {err}", ephemeral=True)
        except Exception as err:
            LOG.exception("Falha ao executar %s", descricao)
            await interaction.followup.send(
                "❌ Não foi possível concluir a operação. Verifique as permissões da planilha "
                "e os logs do bot. Nenhuma confirmação de alteração foi emitida.", ephemeral=True)

    @client.event
    async def on_ready() -> None:
        LOG.info("Bot %s conectado como %s, servidor %d", cfg.batalhao, client.user, cfg.guild_id)

    @client.tree.command(name="consultar", description="Consulta um policial pelo ID.")
    @app_commands.describe(id="ID no GTA RP")
    async def consultar(interaction: discord.Interaction, id: int) -> None:
        async def exec_consulta() -> None:
            if not autorizado(interaction, cfg, "consulta"):
                await interaction.response.send_message("Sem permissão.", ephemeral=True)
                return
            await interaction.response.defer(ephemeral=True)
            try:
                nonlocal service
                async with startup_lock:
                    if service is None:
                        service = await asyncio.to_thread(Planilha, cfg)
                data = await asyncio.to_thread(service.consultar, id)
                embed = discord.Embed(title=f"Ficha policial · {cfg.batalhao}", color=RED)
                for key, title in [("id", "ID"), ("nome", "Nome no RP"),
                                   ("badge", "Badge"), ("patente", "Patente"),
                                   ("unidade", "Unidade"), ("situacao", "Situação"),
                                   ("entrada", "Entrada")]:
                    embed.add_field(name=title, value=data[key] or "—", inline=True)
                await interaction.followup.send(embed=embed, ephemeral=True)
            except ErroNegocio as err:
                await interaction.followup.send(f"⚠️ {err}", ephemeral=True)
            except Exception:
                LOG.exception("Consulta falhou")
                await interaction.followup.send("Erro de acesso à planilha.", ephemeral=True)
        await exec_consulta()

    @client.tree.command(name="resumo", description="Resumo do efetivo deste batalhão.")
    async def resumo(interaction: discord.Interaction) -> None:
        nonlocal service
        if not autorizado(interaction, cfg, "consulta"):
            await interaction.response.send_message("Sem permissão.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            async with startup_lock:
                if service is None:
                    service = await asyncio.to_thread(Planilha, cfg)
            d = await asyncio.to_thread(service.resumo)
            await interaction.followup.send(
                f"**{cfg.batalhao}**\nEfetivo: **{d['total']}** · Ativos: **{d['ativos']}**"
                f" · BOPE: **{d['bope']}** · Sem situação: **{d['sem_situacao']}**",
                ephemeral=True)
        except Exception:
            LOG.exception("Resumo falhou")
            await interaction.followup.send("Erro ao consultar o efetivo.", ephemeral=True)

    @client.tree.command(name="cadastrar", description="Publica o painel de Registro e Pesquisa do batalhão.")
    async def cadastrar(interaction: discord.Interaction) -> None:
        # Somente comando/admin publica novos painéis; os botões são públicos.
        if not autorizado(interaction, cfg, "edicao"):
            await interaction.response.send_message(
                "Somente administração ou RH pode publicar o painel de cadastro.", ephemeral=True)
            return
        await interaction.response.send_message(embed=portal.mensagem_painel(), view=portal.painel(),
                                                allowed_mentions=discord.AllowedMentions.none())

    @client.tree.command(name="promover", description="Atualiza a patente e registra a promoção.")
    async def promover(interaction: discord.Interaction, id: int, patente: str) -> None:
        await executar(interaction, "comando",
                       lambda: service.promover(id, patente, operador_de(interaction)), f"Promoção · ID {id}")

    @client.tree.command(name="situacao", description="Altera a situação do policial.")
    @app_commands.choices(situacao=[app_commands.Choice(name=s, value=s) for s in SITUACOES])
    async def situacao(interaction: discord.Interaction, id: int, situacao: app_commands.Choice[str]) -> None:
        await executar(interaction, "edicao",
                       lambda: service.situacao(id, situacao.value, operador_de(interaction)), f"Situação · ID {id}")

    @client.tree.command(name="unidade", description="Transfere um policial entre unidades do mesmo batalhão.")
    @app_commands.choices(unidade=[app_commands.Choice(name=s, value=s) for s in UNIDADES])
    async def unidade(interaction: discord.Interaction, id: int, unidade: app_commands.Choice[str]) -> None:
        await executar(interaction, "comando",
                       lambda: service.unidade(id, unidade.value, operador_de(interaction)), f"Unidade · ID {id}")

    @client.tree.command(name="curso", description="Registra curso/treinamento no histórico.")
    @app_commands.describe(validade_dias="0 = sem vencimento")
    @app_commands.choices(situacao=[app_commands.Choice(name=s, value=s) for s in CURSO_SITUACOES])
    async def curso(interaction: discord.Interaction, id: int, nome: str,
                    situacao: app_commands.Choice[str], validade_dias: int = 0) -> None:
        await executar(interaction, "edicao",
                       lambda: service.curso(id, nome, operador_de(interaction), situacao.value, validade_dias),
                       f"Curso · ID {id}")

    async def enviar_log_advertencia(interaction: discord.Interaction, ficha: dict[str, str],
                                    id_policia: int, motivo: str, punicao: str,
                                    duracao_dias: int) -> str:
        """Publica somente uma log completa, após a gravação na planilha.

        Canal específico prevalece; se ausente, usa o canal geral já configurado.
        Uma falha de envio nunca desfaz ou repete a advertência salva.
        """
        canal_id = cfg.canal_advertencias or cfg.canal_logs
        if not canal_id:
            return "não_configurado"
        channel = client.get_channel(canal_id)
        if channel is None:
            try:
                channel = await client.fetch_channel(canal_id)
            except discord.DiscordException:
                LOG.warning("Canal de advertências indisponível: %s", canal_id)
                return "falha"
        if not isinstance(channel, discord.TextChannel) or channel.guild.id != cfg.guild_id:
            LOG.warning("Canal de advertências %s não pertence ao servidor configurado", canal_id)
            return "falha"

        def seguro(valor: object, tamanho: int = 1000) -> str:
            texto = discord.utils.escape_markdown(discord.utils.escape_mentions(str(valor).strip()))
            return (texto[:tamanho] + "…") if len(texto) > tamanho else (texto or "—")

        hoje = datetime.now(ZONE)
        validade = ((hoje.date() + timedelta(days=duracao_dias)).strftime("%d/%m/%Y")
                    if duracao_dias else "Sem prazo")
        embed = discord.Embed(
            title="🚨 Nova advertência registrada",
            description=f"**{seguro(cfg.batalhao, 160)}** | Silver City RP",
            color=RED, timestamp=hoje,
        )
        embed.add_field(name="👤 Policial", value=seguro(ficha.get("nome") or "Não informado"), inline=False)
        embed.add_field(name="🆔 ID no jogo", value=f"`{id_policia}`", inline=True)
        badge = ficha.get("badge", "").strip()
        embed.add_field(name="🎖️ Badge", value=(badge.zfill(3) if badge.isdigit() else seguro(badge)), inline=True)
        embed.add_field(name="📌 Patente", value=seguro(ficha.get("patente")), inline=True)
        embed.add_field(name="🛡️ Unidade", value=seguro(ficha.get("unidade")), inline=True)
        embed.add_field(name="📅 Aplicada em", value=hoje.strftime("%d/%m/%Y"), inline=True)
        embed.add_field(name="⏳ Expira em", value=validade, inline=True)
        embed.add_field(name="📝 Motivo", value=seguro(motivo), inline=False)
        embed.add_field(name="⚖️ Punição", value=seguro(punicao), inline=False)
        embed.add_field(
            name="👮 Aplicada por",
            value=f"{interaction.user.mention} (`{interaction.user.id}`)", inline=False,
        )
        embed.set_footer(text="Silver City RP • Salvo em ADVERTÊNCIAS e REGISTROS")
        try:
            await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
            return "enviado"
        except discord.DiscordException:
            LOG.exception("Advertência salva, mas o log Discord falhou no canal %s", canal_id)
            return "falha"

    @client.tree.command(name="advertir", description="Registra advertência e prazo de expiração.")
    @app_commands.describe(duracao_dias="0 = sem prazo")
    async def advertir(interaction: discord.Interaction, id: int, motivo: str,
                       punicao: str, duracao_dias: int = 30) -> None:
        if not autorizado(interaction, cfg, "comando"):
            await interaction.response.send_message(
                "Você não tem permissão ou está no servidor incorreto.", ephemeral=True,
            )
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            plan = await get_service()
            ficha = await asyncio.to_thread(plan.consultar, id)
            # Mantém intactos os campos, validações e rotina de gravação anteriores.
            resultado = await asyncio.to_thread(
                plan.advertir, id, motivo, punicao, duracao_dias, operador_de(interaction),
            )
        except ErroNegocio as err:
            await interaction.followup.send(f"⚠️ {err}", ephemeral=True)
            return
        except Exception:
            LOG.exception("Falha ao registrar advertência · ID %s", id)
            await interaction.followup.send(
                "❌ Não consegui confirmar a advertência. Confira a planilha antes de tentar novamente.",
                ephemeral=True,
            )
            return

        # O log só é disparado depois do sucesso da gravação no Google Sheets.
        status = await enviar_log_advertencia(interaction, ficha, id, motivo, punicao, duracao_dias)
        if status == "enviado":
            observacao = "📨 Log enviado ao canal configurado."
        elif status == "não_configurado":
            observacao = ("ℹ️ Canal de advertências ainda não configurado. "
                          "O histórico foi salvo na planilha; configure `CANAL_ADVERTENCIAS_ID` depois.")
        else:
            observacao = ("⚠️ Advertência salva na planilha, mas o log não chegou ao canal. "
                          "Confira o ID do canal e as permissões do bot antes de reenviar o aviso.")
        await interaction.followup.send(
            f"✅ {resultado}\n{observacao}", ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @client.tree.command(name="medalha", description="Registra condecoração para um policial.")
    async def medalha(interaction: discord.Interaction, id: int, nome: str, motivo: str) -> None:
        await executar(interaction, "comando",
                       lambda: service.medalha(id, nome, motivo, operador_de(interaction)),
                       f"Medalha · ID {id}")

    return client


def iniciar(env_path: str) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg = carregar_config(Path(env_path).resolve())
    criar_bot(cfg).run(cfg.token, log_handler=None)
