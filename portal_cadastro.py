"""Painel de autorregistro do Silver City RP — Discord UI + Google Sheets.

Não requer Message Content Intent. Persistência dos botões Registro/Pesquisa
via View(timeout=None) e IDs específicos deste servidor.
"""
from __future__ import annotations

import logging
from typing import Callable, Awaitable, Any

import discord

LOG = logging.getLogger("silver-city.portal")
RED = 0xC7133A


def ficha_embed(batalhao: str, data: dict[str, str]) -> discord.Embed:
    titulo = f"Ficha policial — {batalhao}"
    embed = discord.Embed(title=titulo, color=RED,
                          description=f"**ID pesquisado: {data.get('ID', '—')}**")
    used = 0
    for key, content in data.items():
        if key == 'ID':
            continue
        if used >= 24:  # Discord permite até 25 campos
            break
        name = str(key)[:200]
        value = str(content).strip() if content is not None else ""
        if name == 'BADGE' and value.isdigit():
            value = f"{int(value):03d}"
        value = discord.utils.escape_mentions(value or "—")[:450]
        embed.add_field(name=name, value=value or "—", inline=(name not in ("OBSERVAÇÕES",)))
        used += 1
    embed.set_footer(text="Resultado privado • Use Denunciar erro? para reportar divergências")
    return embed


class Portal:
    """Estado e callbacks isolados por guild/bot (duas instâncias independentes)."""

    def __init__(self, client: discord.Client, cfg: Any, get_service: Callable[[], Awaitable[Any]],
                 log_event: Callable[[discord.Interaction, str], Awaitable[None]]):
        self.client = client
        self.cfg = cfg
        self.get_service = get_service
        self.log_event = log_event

    def no_servidor(self, interaction: discord.Interaction) -> bool:
        return interaction.guild_id == self.cfg.guild_id and isinstance(interaction.user, discord.Member)

    def painel(self) -> discord.ui.View:
        portal = self

        class PainelView(discord.ui.View):
            def __init__(self):
                super().__init__(timeout=None)  # sobrevive a reinicializações

            @discord.ui.button(label="Registro", emoji="📝", style=discord.ButtonStyle.success,
                               custom_id=f"silvercity:v1:{portal.cfg.guild_id}:registro")
            async def registro(self, interaction: discord.Interaction, button: discord.ui.Button):
                if not portal.no_servidor(interaction):
                    await interaction.response.send_message("Este painel não pertence a este servidor.", ephemeral=True)
                    return
                await interaction.response.send_modal(portal.modal_registro())

            @discord.ui.button(label="Pesquisa", emoji="🔎", style=discord.ButtonStyle.primary,
                               custom_id=f"silvercity:v1:{portal.cfg.guild_id}:pesquisa")
            async def pesquisa(self, interaction: discord.Interaction, button: discord.ui.Button):
                if not portal.no_servidor(interaction):
                    await interaction.response.send_message("Este painel não pertence a este servidor.", ephemeral=True)
                    return
                await interaction.response.send_modal(portal.modal_pesquisa())

        return PainelView()

    def mensagem_painel(self) -> discord.Embed:
        embed = discord.Embed(
            title=f"🟥 Cadastro policial — {self.cfg.batalhao}",
            description=(
                "**Bem-vindo(a) à Silver City RP!**\n\n"
                "**Registro** — informe seu **Nome no jogo** e seu **ID** do GTA RP. "
                "O sistema reserva automaticamente o próximo **badge** (001, 002, 003...), "
                "define a patente e situação iniciais, registra você na planilha, "
                "e tenta atribuir seu cargo e apelido `Nome | ID`.\n\n"
                "**Pesquisa** — informe o **ID** para consultar a ficha policial; "
                "o resultado ficará **visível apenas para você**. "
                "Na ficha, use **Denunciar erro?** caso encontre informações incorretas.\n\n"
                "⚠️ Só é permitido **um cadastro por conta Discord e por ID no jogo**."
            ),
            color=RED,
        )
        embed.set_footer(text="Silver City RP • BOPE • Selecione um botão abaixo")
        return embed

    def modal_registro(self) -> discord.ui.Modal:
        portal = self

        class RegistroModal(discord.ui.Modal, title="Registro policial — Silver City"):
            nome = discord.ui.TextInput(label="Nome no jogo", placeholder="Ex.: Rodrigo Caveira",
                                        min_length=2, max_length=80, required=True)
            id_jogo = discord.ui.TextInput(label="ID no jogo", placeholder="Ex.: 186",
                                           min_length=1, max_length=12, required=True)

            async def on_submit(self, interaction: discord.Interaction) -> None:
                if not portal.no_servidor(interaction):
                    await interaction.response.send_message("Servidor incorreto.", ephemeral=True)
                    return
                await interaction.response.defer(ephemeral=True, thinking=True)
                from bot_core import ErroNegocio
                try:
                    service = await portal.get_service()
                    import asyncio
                    cadastro = await asyncio.to_thread(
                        service.cadastrar_auto, str(self.id_jogo), str(self.nome), str(interaction.user.id),
                        f"{interaction.user.display_name} ({interaction.user.id})"
                    )
                    # O registro é confirmado antes de tentar alterar o Discord.
                    avisos = []
                    apelido = f"{cadastro['nome']} | {cadastro['id']}"
                    try:
                        await interaction.user.edit(nick=apelido, reason="Registro automático Silver City RP")
                    except (discord.Forbidden, discord.HTTPException):
                        avisos.append("Não consegui mudar seu apelido. Um superior deve conferir a permissão **Gerenciar apelidos** e a hierarquia de cargos.")
                    if portal.cfg.cargo_registrado:
                        role = interaction.guild.get_role(portal.cfg.cargo_registrado) if interaction.guild else None
                        if role is None:
                            avisos.append("O cargo de cadastrado não foi encontrado no servidor. Confira `CARGO_CADASTRADO_ID`.")
                        else:
                            try:
                                await interaction.user.add_roles(role, reason="Cadastro Silver City RP")
                            except (discord.Forbidden, discord.HTTPException):
                                avisos.append("Não consegui atribuir o cargo; confira **Gerenciar cargos** e a hierarquia do bot.")
                    else:
                        avisos.append("O cargo automático ainda não foi configurado (`CARGO_CADASTRADO_ID`).")
                    embed = discord.Embed(title="✅ Cadastro concluído", color=0x19AA77,
                                          description=f"**{discord.utils.escape_mentions(apelido)}**")
                    embed.add_field(name="ID", value=cadastro['id'])
                    embed.add_field(name="Badge", value=cadastro['badge'])
                    embed.add_field(name="Patente", value=cadastro['patente'])
                    embed.add_field(name="Unidade", value=cadastro['unidade'])
                    embed.add_field(name="Situação", value=cadastro['situacao'])
                    if avisos:
                        embed.add_field(name="Ajustes pendentes no Discord", value="\n".join(avisos)[:900], inline=False)
                    await interaction.followup.send(embed=embed, ephemeral=True,
                                                    allowed_mentions=discord.AllowedMentions.none())
                    await portal.log_event(interaction, f"Cadastro automático de {cadastro['nome']} "
                                           f"(ID {cadastro['id']}, badge {cadastro['badge']})")
                except ErroNegocio as exc:
                    await interaction.followup.send(f"⚠️ {exc}", ephemeral=True)
                except Exception:
                    LOG.exception("Erro em cadastro automático")
                    await interaction.followup.send("❌ Erro ao registrar. Confira os logs e a planilha antes de tentar novamente.", ephemeral=True)

        return RegistroModal()

    def modal_pesquisa(self) -> discord.ui.Modal:
        portal = self

        class PesquisaModal(discord.ui.Modal, title="Pesquisar policial — Silver City"):
            id_jogo = discord.ui.TextInput(label="ID no jogo", placeholder="Digite o ID para consultar",
                                           max_length=12, required=True)

            async def on_submit(self, interaction: discord.Interaction) -> None:
                if not portal.no_servidor(interaction):
                    await interaction.response.send_message("Servidor incorreto.", ephemeral=True)
                    return
                await interaction.response.defer(ephemeral=True, thinking=True)
                from bot_core import ErroNegocio
                try:
                    import asyncio
                    service = await portal.get_service()
                    data = await asyncio.to_thread(service.consultar_completo, str(self.id_jogo))
                    await interaction.followup.send(
                        embed=ficha_embed(portal.cfg.batalhao, data),
                        view=portal.report_view(data, interaction.user.id),
                        ephemeral=True,
                        allowed_mentions=discord.AllowedMentions.none(),
                    )
                except ErroNegocio as exc:
                    await interaction.followup.send(f"⚠️ {exc}", ephemeral=True)
                except Exception:
                    LOG.exception("Erro na pesquisa de cadastro")
                    await interaction.followup.send("❌ Erro ao consultar a planilha.", ephemeral=True)

        return PesquisaModal()

    def report_view(self, ficha: dict[str, str], autor_id: int) -> discord.ui.View:
        portal = self

        class ReportView(discord.ui.View):
            def __init__(self):
                super().__init__(timeout=15 * 60)

            @discord.ui.button(label="Denunciar erro?", emoji="⚠️", style=discord.ButtonStyle.danger)
            async def denunciar(self, interaction: discord.Interaction, button: discord.ui.Button):
                if not portal.no_servidor(interaction) or interaction.user.id != autor_id:
                    await interaction.response.send_message("Somente quem fez a pesquisa pode denunciar erros nesta ficha.", ephemeral=True)
                    return
                await interaction.response.send_modal(portal.modal_denuncia(ficha))

        return ReportView()

    def modal_denuncia(self, ficha: dict[str, str]) -> discord.ui.Modal:
        portal = self

        class DenunciaModal(discord.ui.Modal, title="Denunciar erro na ficha policial"):
            motivo = discord.ui.TextInput(label="Qual informação está incorreta?",
                                          placeholder="Explique o erro encontrado no cadastro...",
                                          style=discord.TextStyle.paragraph,
                                          min_length=8, max_length=1000, required=True)

            async def on_submit(self, interaction: discord.Interaction) -> None:
                if not portal.no_servidor(interaction):
                    await interaction.response.send_message("Servidor incorreto.", ephemeral=True)
                    return
                await interaction.response.defer(ephemeral=True, thinking=True)
                try:
                    import asyncio
                    service = await portal.get_service()
                    perfil = {
                        'id': str(interaction.user.id),
                        'username': str(interaction.user),
                        'display_name': interaction.user.display_name,
                        'avatar_url': str(interaction.user.display_avatar.url),
                    }
                    registro = await asyncio.to_thread(service.salvar_denuncia, ficha, perfil, str(self.motivo))
                    nome = ficha.get('NOME NO RP', '—')
                    embed = discord.Embed(title=f"🚨 Denúncia de erro — {portal.cfg.batalhao}", color=RED)
                    embed.add_field(name="Perfil do denunciante", value=(
                        f"{interaction.user.mention}\n**Usuário:** {discord.utils.escape_mentions(perfil['username'])}\n"
                        f"**Apelido:** {discord.utils.escape_mentions(perfil['display_name'])}\n"
                        f"**Discord ID:** `{perfil['id']}`"), inline=False)
                    embed.add_field(name="Cadastro reportado", value=f"{discord.utils.escape_mentions(str(nome))} | ID `{ficha.get('ID', '—')}`", inline=False)
                    embed.add_field(name="Erro informado", value=discord.utils.escape_mentions(str(self.motivo)), inline=False)
                    embed.set_thumbnail(url=perfil['avatar_url'])
                    embed.set_footer(text=f"Denúncia registrada na planilha: linha {registro}")
                    enviado = False
                    if portal.cfg.canal_denuncias:
                        channel = portal.client.get_channel(portal.cfg.canal_denuncias)
                        if channel is None:
                            try:
                                channel = await portal.client.fetch_channel(portal.cfg.canal_denuncias)
                            except discord.DiscordException:
                                LOG.warning("Canal de denúncias não acessível: %s", portal.cfg.canal_denuncias)
                        if isinstance(channel, discord.TextChannel) and channel.guild.id == portal.cfg.guild_id:
                            try:
                                await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
                                enviado = True
                            except discord.DiscordException:
                                LOG.warning("Falha ao enviar denúncia para canal %s", portal.cfg.canal_denuncias)
                    if enviado:
                        try:
                            await asyncio.to_thread(service.marcar_denuncia_enviada, registro)
                        except Exception:
                            LOG.exception("Enviou denúncia, mas não atualizou status na planilha")
                        resposta = "✅ Denúncia enviada ao canal responsável e registrada na planilha."
                    else:
                        resposta = ("✅ Denúncia salva na aba **DENÚNCIAS**. O envio para o Discord "
                                    "ficará pendente até que um administrador configure ou corrija `CANAL_DENUNCIAS_ID`.")
                    await interaction.followup.send(resposta, ephemeral=True)
                except Exception:
                    LOG.exception("Falha ao registrar denúncia")
                    await interaction.followup.send("❌ Não consegui registrar a denúncia. Tente novamente mais tarde.", ephemeral=True)

        return DenunciaModal()
