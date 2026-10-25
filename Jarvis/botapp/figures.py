"""A delayed working GIF, replaced by the result in the same interaction message."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import discord

log = logging.getLogger(__name__)


class FigureChannel:
    def __init__(self, interaction, root: Path, settings: dict):
        self.interaction = interaction
        self.id = interaction.channel_id
        self.folder = root / "assets" / "figure"
        self.settings = settings
        self.lock = asyncio.Lock()
        self.shown = False
        self.finished = False

    async def working_after(self, delay=.9, preview=False):
        await asyncio.sleep(delay)
        async with self.lock:
            path = self.folder / "working.gif"
            if self.finished or not path.is_file():
                return
            embed = discord.Embed(
                title="Animationsvorschau" if preview else f"{self.settings['name']} arbeitet …",
                description="Nur eine Vorschau. Gleich erscheint das ruhende Bild." if preview else "Deine Anfrage wird bearbeitet. Das Ergebnis erscheint hier.",
                color=int(self.settings["color"].lstrip("#"), 16),
            )
            embed.set_image(url="attachment://working.gif")
            try:
                picture = discord.File(path, filename="working.gif")
                try:
                    await self.interaction.edit_original_response(embed=embed, attachments=[picture], allowed_mentions=discord.AllowedMentions.none())
                finally:
                    picture.close()
                self.shown = True
            except (discord.HTTPException, OSError) as exc:
                # Optional artwork must never prevent the actual operation/reply.
                log.warning("Arbeitsanzeige nicht verfügbar (%s).", type(exc).__name__)

    async def send(self, *args, **kwargs):
        async with self.lock:
            kwargs.setdefault("allowed_mentions", discord.AllowedMentions.none())
            owned = None
            embed = kwargs.get("embed")
            state = kwargs.pop("figure_state", "done")
            path = self.folder / ("error.png" if state == "error" else "done.png")
            # Keep rank.png and any other result attachment untouched.
            if embed and not kwargs.get("file") and not kwargs.get("files") and path.is_file():
                owned = discord.File(path, filename="figure.png")
                kwargs["file"] = owned
                embed.set_thumbnail(url="attachment://figure.png")
            try:
                if self.shown and not self.finished:
                    attachments = list(kwargs.pop("files", []))
                    if "file" in kwargs:
                        attachments.append(kwargs.pop("file"))
                    # Explicit replacement removes the old GIF attachment.
                    kwargs["attachments"] = attachments
                    if args:
                        kwargs["content"] = args[0]
                    result = await self.interaction.edit_original_response(**kwargs)
                else:
                    result = await self.interaction.followup.send(*args, **kwargs, wait=True)
                self.finished = True
                return result
            finally:
                if owned:
                    owned.close()

    async def failure(self):
        try:
            await self.send(figure_state="error", embed=discord.Embed(title="Anfrage nicht abgeschlossen",
                description="Bitte Eingaben, Berechtigungen und die Bot-Protokolle prüfen.", color=0xEAB45E))
        except (discord.HTTPException, OSError) as exc:
            log.warning("Fehlerhinweis nicht zustellbar (%s).", type(exc).__name__)
