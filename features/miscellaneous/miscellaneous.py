import os
import sys
from asyncio import Lock, TimeoutError, sleep
from base64 import b64decode
from contextlib import suppress
from datetime import datetime
from io import BytesIO
from re import compile as re_compile
from tempfile import TemporaryDirectory
from typing import List, Optional

from aiofiles import open as async_open
from discord import (CategoryChannel, Embed, File, Forbidden, HTTPException,
                     Member, Message, PartialMessage, Reaction, Status,
                     TextChannel, User)
from discord.ext.commands import (BucketType, MissingPermissions, Range,
                                  command, cooldown, flag, group,
                                  has_permissions, max_concurrency, param)
from discord.ext.tasks import aiohttp, loop
from discord.utils import (as_chunks, escape_markdown, escape_mentions, find,
                           format_dt, utcnow)
from jishaku.codeblocks import Codeblock, codeblock_converter
from munch import Munch
from orjson import dumps, loads
from pyppeteer import launch
from pyppeteer.browser import Browser
from pyppeteer.errors import NetworkError, PageError
from pyppeteer.errors import TimeoutError as PTimeoutError
from xxhash import xxh128_hexdigest
from yarl import URL

import config
from tools.converters.basic import (ImageFinderStrict, Language, SynthEngine,
                                    TimeConverter)
from tools.converters.embed import EmbedScript, EmbedScriptValidator
from tools.managers import cache
from tools.managers.cog import Cog
from tools.managers.context import Context, FlagConverter
from tools.managers.converter import Domain
from tools.managers.regex import DISCORD_MESSAGE, IMAGE_URL
from tools.models.piston import PistonExecute, PistonRuntime
from tools.pumpumpal import pumpumpal
from tools.utilities import donator, require_dm, shorten
from tools.utilities.humanize import human_timedelta
from tools.utilities.process import ensure_future
from tools.utilities.text import hash


class ScreenshotFlags(FlagConverter):
    delay: Range[int, 1, 10] = flag(
        description="The amount of seconds to let the page render.",
        default=0,
    )

    full_page: bool = flag(
        description="Whether or not to take a screenshot of the entire page.",
        default=False,
    )


class Miscellaneous(Cog):
    """Cog for Miscellaneous commands."""

    def __init__(self: "Miscellaneous", bot: "pumpumpal"):
        self.bot: "pumpumpal" = bot
        self.browser: Browser

    async def screenshot(self: "Miscellaneous"):
        # Construct the API URL with your parameters
        api_url = "https://api.screenshotone.com/take"
        params = {
            "access_key": "JIpTxMx2dFvQ5A",
            "url": url,
            "full_page": str(flags.full_page).lower(),  # Convert boolean to 'true' or 'false'
            "viewport_width": "1920",
            "viewport_height": "1080",
            "device_scale_factor": "1",
            "format": "jpg",
            "image_quality": "80",
            "block_ads": "true",
            "block_cookie_banners": "true",
            "block_banners_by_heuristics": "false",
            "block_trackers": "true",
            "delay": str(flags.delay),
            "timeout": "60",
        }

        try:
            # Make the request to ScreenshotOne API
            response = requests.get(api_url, params=params)

            # Check if the request was successful
            if response.status_code == 200:
                # Convert the response content to an image
                image = BytesIO(response.content)
                image.seek(0)

                # Send the image back in the Discord channel
                await ctx.send(file=File(image, "screenshot.jpg"))
            else:
                await ctx.send(f"Failed to take screenshot. Status code: {response.status_code}")

        except Exception as e:
            await ctx.send(f"An error occurred: {e}")

    @Cog.listener("on_user_message")
    async def sticky_message_dispatcher(
        self: "Miscellaneous", ctx: Context, message: Message
    ):
        """Dispatch the sticky message event while waiting for the activity scheduler"""

        data = await self.bot.db.fetchrow(
            "SELECT * FROM sticky_messages WHERE guild_id = $1 AND channel_id = $2",
            message.guild.id,
            message.channel.id,
        )
        if not data:
            return

        if data["message_id"] == message.id:
            return

        key = hash(f"{message.guild.id}:{message.channel.id}")
        if not self.bot.sticky_locks.get(key):
            self.bot.sticky_locks[key] = Lock()
        bucket = self.bot.sticky_locks.get(key)

        async with bucket:
            try:
                await self.bot.wait_for(
                    "message",
                    check=lambda m: m.channel == message.channel,
                    timeout=data.get("schedule") or 0,
                )
            except TimeoutError:
                pass
            else:
                return

            with suppress(HTTPException):
                await message.channel.get_partial_message(data["message_id"]).delete()

            message = await ensure_future(
                EmbedScript(data["message"]).send(
                    message.channel,
                    bot=self.bot,
                    guild=message.guild,
                    channel=message.channel,
                    user=message.author,
                )
            )
            await self.bot.db.execute(
                "UPDATE sticky_messages SET message_id = $3 WHERE guild_id = $1 AND channel_id = $2",
                message.guild.id,
                message.channel.id,
                message.id,
            )

    @Cog.listener("on_message")
    async def check_afk(self: "Miscellaneous", message: Message):
        if (ctx := await self.bot.get_context(message)) and ctx.command:
            return

        if author_afk_since := await self.bot.db.fetchval(
            """
            DELETE FROM afk
            WHERE user_id = $1
            RETURNING timestamp
            """,
            message.author.id,
        ):
            if "[afk]" in message.author.display_name.lower():
                with suppress(HTTPException):
                    await message.author.edit(
                        nick=message.author.display_name.replace("[afk]", "")
                    )

            await ctx.neutral(
                f"Welcome back, you were away for **{human_timedelta(author_afk_since, suffix=False)}**",
                emoji="👋🏾",
            )

        bucket = self.bot.buckets.get("afk").get_bucket(message)
        if bucket.update_rate_limit():
            return

        if len(message.mentions) == 1 and (user := message.mentions[0]):
            if user_afk := await self.bot.db.fetchrow(
                """
                SELECT message, timestamp FROM afk
                WHERE user_id = $1
                """,
                user.id,
            ):
                await ctx.neutral(
                    f"{user.mention} is AFK: **{user_afk['message']}** - {human_timedelta(user_afk['timestamp'], suffix=False)} ago",
                    emoji="💤",
                )

    @Cog.listener("on_user_message")
    async def check_highlights(self: "Miscellaneous", ctx: Context, message: Message):
        """Check for highlights"""
        if not message.content or message.author.bot:
            return

        highlights = [
            highlight
            for highlight in await self.bot.db.fetch(
                "SELECT DISTINCT on (user_id) * FROM highlight_words WHERE POSITION(word in $1) > 0",
                message.content.lower(),
            )
            if highlight["user_id"] != message.author.id
            and ctx.guild.get_member(highlight["user_id"])
            and ctx.channel.permissions_for(
                ctx.guild.get_member(highlight["user_id"])
            ).view_channel
        ]

        if highlights:
            bucket = self.bot.buckets.get("highlights").get_bucket(message)
            if bucket.update_rate_limit():
                return

            for highlight in highlights:
                if (
                    highlight.get("word") not in message.content.lower()
                    or highlight.get("strict")
                    and highlight.get("word") != message.content.lower()
                ):
                    continue
                if member := message.guild.get_member(highlight.get("user_id")):
                    self.bot.dispatch("highlight", message, highlight["word"], member)

    @Cog.listener()
    async def on_highlight(
        self: "Miscellaneous", message: Message, keyword: str, member: Member
    ):
        """Notify a user about a highlight"""
        if member in message.mentions:
            return

        if blocked_entities := await self.bot.db.fetch(
            "SELECT entity_id FROM highlight_block WHERE user_id = $1",
            member.id,
        ):
            if any(
                entity["entity_id"]
                in [message.author.id, message.channel.id, message.guild.id]
                for entity in blocked_entities
            ):
                return

        embed = Embed(
            url=message.jump_url,
            color=config.Color.neutral,
            title=f"Highlight in {message.guild}",
            description=f"Keyword **{escape_markdown(keyword)}** said in {message.channel.mention}\n>>> ",
        )
        embed.set_author(
            name=message.author.display_name,
            icon_url=message.author.display_avatar,
        )

        messages = []
        with suppress(Forbidden):
            async for ms in message.channel.history(limit=3, before=message):
                if ms.id == message.id:
                    continue
                if not ms.content:
                    continue

                messages.append(
                    f"[{format_dt(ms.created_at, 'T')}] {escape_markdown(str(ms.author))}:"
                    f" {shorten(escape_markdown(ms.content), 50)}"
                )

            messages.append(
                f"__[{format_dt(message.created_at, 'T')}]__ {escape_markdown(str(message.author))}:"
                f" {shorten(escape_markdown(message.content).replace(keyword, f'__{keyword}__'), 50)}"
            )

            async for ms in message.channel.history(limit=2, after=message):
                if ms.id == message.id:
                    continue
                if not ms.content:
                    continue

                messages.append(
                    f"[{format_dt(ms.created_at, 'T')}] {escape_markdown(str(ms.author))}:"
                    f" {shorten(escape_markdown(ms.content), 50)}"
                )

        embed.description += "\n".join(messages)

        with suppress(Forbidden):
            await member.send(embed=embed)

    @Cog.listener("on_user_update")
    async def submit_name(
        self: "Miscellaneous",
        before: User,
        user: User,
    ):
        if before.name == user.name and before.global_name == user.global_name:
            return

        await self.bot.db.execute(
            """
            INSERT INTO metrics.names (user_id, name)
            VALUES ($1, $2)
            """,
            user.id,
            (
                before.name
                if user.name != before.name
                else (before.global_name or before.name)
            ),
        )

    @loop(seconds=30)
    async def reminder(self: "Miscellaneous"):
        """Check for reminders"""
        for reminder in await self.bot.db.fetch("SELECT * FROM reminders"):
            if user := self.bot.get_user(reminder["user_id"]):
                if utcnow() >= reminder["timestamp"]:
                    with suppress(HTTPException):
                        await user.send(
                            embed=Embed(
                                title="Reminder",
                                description=reminder["text"],
                            )
                        )
                        await self.bot.db.execute(
                            "DELETE FROM reminders WHERE user_id = $1 AND text = $2",
                            reminder["user_id"],
                            reminder["text"],
                        )

    @Cog.listener("on_user_message")
    async def message_repost(
        self: "Miscellaneous", ctx: Context, message: Message
    ) -> Embed | None:
        """Repost a message from another channel"""
        if message.author.bot:
            return
        if not message.content:
            return
        if "discord.com/channels" not in message.content:
            return
        if message.guild and message.guild.id != ctx.guild.id:
            return

        if not (match := DISCORD_MESSAGE.match(message.content)):
            return

        _, channel_id, message_id = map(int, match.groups())
        channel = self.bot.get_channel(channel_id)
        if not channel:
            return
        if not channel.permissions_for(ctx.me).view_channel:
            return
        if not channel.permissions_for(ctx.author).view_channel:
            return
        try:
            message = await channel.fetch_message(message_id)
        except HTTPException:
            return

        if message.embeds and message.embeds[0].type != "image":
            embed = message.embeds[0]
            embed.description = embed.description or ""
        else:
            embed = Embed(
                color=(
                    message.author.color
                    if message.author.color.value
                    else config.Color.neutral
                ),
                description="",
            )
        embed.set_author(
            name=message.author,
            icon_url=message.author.display_avatar,
            url=message.jump_url,
        )

        if message.content:
            embed.description += f"\n{message.content}"

        if message.attachments and message.attachments[0].content_type.startswith(
            "image"
        ):
            embed.set_image(url=message.attachments[0].proxy_url)

        attachments = []
        for attachment in message.attachments:
            if attachment.content_type.startswith("image"):
                continue
            if attachment.size > ctx.guild.filesize_limit:
                continue
            if not attachment.filename.endswith(
                ("mp4", "mp3", "mov", "wav", "ogg", "webm")
            ):
                continue

            attachments.append(await attachment.to_file())

        embed.set_footer(
            text=f"Posted @ #{message.channel}", icon_url=message.guild.icon
        )
        embed.timestamp = message.created_at

        await ctx.channel.send(embed=embed, files=attachments)

    @command(
        name="firstmessage",
        usage="<channel>",
        example="#chat",
        aliases=["firstmsg", "first"],
    )
    async def firstmessage(
        self: "Miscellaneous", ctx: Context, *, channel: TextChannel = None
    ):
        """Jump to the first message in a channel"""
        channel = channel or ctx.channel

        if not channel.permissions_for(ctx.author).read_message_history:
            raise MissingPermissions(["read_message_history"])

        async for message in channel.history(limit=1, oldest_first=True):
            break

        if message:
            await ctx.neutral(
                f"Jump to the [**first message**]({message.jump_url}) by **{message.author}**",
                emoji="📝",
            )
        else:
            await ctx.error("No **messages** found in this **channel**")

    @command(
        name="google",
        usage="(query)",
        example="how to make a discord bot",
        aliases=["g", "search"],
    )
    async def google(self: "Miscellaneous", ctx: Context, *, query: str):
        """Search for something on Google"""

        async with ctx.typing():
            response = await self.bot.session.request(
                "GET",
                "https://notsobot.com/api/search/google",
                params=dict(
                    query=query.replace(" ", "%20"),
                    safe="false" if ctx.channel.is_nsfw() else "true",
                ),
            )

            if not response.results:
                return await ctx.error(f"No results found for `{query}`")

            embed = Embed(title=f"Google Search: {query}")

            for entry in (
                response.results[:2] if response.cards else response.results[:3]
            ):
                embed.add_field(
                    name=entry.title,
                    value=f"{entry.cite}\n{entry.description}",
                    inline=False,
                )

            await ctx.send(embed=embed)

    @Cog.listener()
    async def on_message_delete(self: "Miscellaneous", message: Message):
        if not message.guild or message.author.bot:
            return

        key = f"snipe:{message.guild.id}:messages:{message.channel.id}"
        await cache.set_add(
            key,
            dumps(
                {
                    "author": {
                        "display_name": message.author.display_name,
                        "avatar_url": message.author.display_avatar.url,
                    },
                    "content": message.content,
                    "attachment_url": (
                        message.attachments[0].url if message.attachments else None
                    ),
                    "deleted_at": utcnow().timestamp(),
                }
            ).decode("utf-8"),
            expire=7200,
        )

    @Cog.listener()
    async def on_message_edit(self: "Miscellaneous", message: Message, after: Message):
        if not message.guild or message.author.bot:
            return

        key = f"snipe:{message.guild.id}:edits:{message.channel.id}"
        await cache.set_add(
            key,
            dumps(
                {
                    "author": {
                        "display_name": message.author.display_name,
                        "avatar_url": message.author.display_avatar.url,
                    },
                    "content": message.content,
                    "attachment_url": (
                        message.attachments[0].url if message.attachments else None
                    ),
                    "edited_at": utcnow().timestamp(),
                }
            ).decode("utf-8"),
            expire=7200,
        )

    @Cog.listener()
    async def on_reaction_remove(
        self: "Miscellaneous", reaction: Reaction, member: Member
    ):
        if not member.guild or member.bot:
            return

        message = reaction.message
        key = f"snipe:{message.guild.id}:reactions:{message.channel.id}:{message.id}"
        await cache.set_add(
            key,
            dumps(
                {
                    "user": member.display_name,
                    "emoji": str(reaction),
                    "removed_at": utcnow().timestamp(),
                }
            ).decode("utf-8"),
            expire=300,
        )

    @command(
        name="clearsnipe",
        aliases=[
            "clearsnipes",
            "cs",
        ],
    )
    @cooldown(1, 10, BucketType.guild)
    @has_permissions(manage_messages=True)
    async def clearsnipe(self: "Miscellaneous", ctx: Context):
        """Clears all results for reactions, edits and messages"""
        await cache.delete_match(f"snipe:{ctx.guild.id}:*")
        await ctx.message.add_reaction("✅")

    @command(name="snipe", usage="<index>", example="3", aliases=["s"])
    async def snipe(self: "Miscellaneous", ctx: Context, index: int = 1):
        """Snipe the latest message that was deleted"""
        if index < 1:
            return await ctx.send_help()

        key = f"snipe:{ctx.guild.id}:messages:{ctx.channel.id}"
        if not (messages := await cache.get(key)):
            return await ctx.error(
                "No **deleted messages** found in the last **2 hours**!"
            )

        if index > len(messages):
            return await ctx.error(f"No **snipe** found for `index {index}`")

        message = loads(
            sorted(
                messages,
                key=lambda m: loads(m)["deleted_at"],
                reverse=True,
            )[index - 1]
        )

        embed = Embed(
            description=message["content"],
        )
        embed.set_author(
            name=message["author"]["display_name"],
            icon_url=message["author"]["avatar_url"],
        )

        if attachment_url := message.get("attachment_url"):
            embed.set_image(url=attachment_url)

        embed.set_footer(
            text=f"Deleted {human_timedelta(datetime.fromtimestamp(message['deleted_at']))} ∙ {index}/{len(messages)} messages",
            icon_url=ctx.author.display_avatar,
        )

        return await ctx.send(embed=embed)

    @command(name="reactionsnipe", aliases=["rs"])
    async def reactionsnipe(self: "Miscellaneous", ctx: Context):
        """Snipe the latest reaction that was removed"""
        key = f"snipe:{ctx.guild.id}:reactions:{ctx.channel.id}:*"
        messages: list[set[int, dict]] = []

        async for key in cache.get_match(key):
            reactions = key[1]
            sorted_reactions = sorted(
                reactions, key=lambda r: loads(r)["removed_at"], reverse=True
            )
            latest_reaction = loads(sorted_reactions[0])
            message_id = int(key[0].split(":")[-1])
            messages.append((message_id, latest_reaction))

        if not messages:
            return await ctx.error(
                "No **removed reactions** found in the last **5 minutes**!"
            )

        message_id, reaction = max(messages, key=lambda m: m[1]["removed_at"])
        message: PartialMessage = ctx.channel.get_partial_message(message_id)

        try:
            await ctx.channel.neutral(
                f"**{reaction['user']}** reacted with **{reaction['emoji']}** <t:{int(reaction['removed_at'])}:R>",
                reference=message,
            )
        except HTTPException:
            await ctx.channel.neutral(
                f"**{reaction['user']}** reacted with **{reaction['emoji']}** on [message]({message.jump_url}) <t:{int(reaction['removed_at'])}:R>",
            )

    @command(
        name="reactionhistory",
        usage="<message link>",
        example="discordapp.com/channels/...",
        aliases=["rh"],
    )
    @has_permissions(manage_messages=True)
    async def reactionhistory(
        self: "Miscellaneous", ctx: Context, message: Message = None
    ):
        """See logged reactions for a message"""
        message = message or ctx.replied_message
        if not message:
            return await ctx.send_help()

        key = f"snipe:{ctx.guild.id}:reactions:{message.channel.id}:{message.id}"
        if not (
            reactions := [
                loads(reaction)
                for reaction in sorted(
                    await cache.get(key, []),
                    key=lambda r: loads(r)["removed_at"],
                    reverse=True,
                )
            ]
        ):
            return await ctx.error(
                f"No **removed reactions** found for [message]({message.jump_url})"
            )

        return await ctx.paginate(
            Embed(
                url=message.jump_url,
                title="Reaction history",
                description="\n".join(
                    [
                        f"**{reaction['user']}** added **{reaction['emoji']}** <t:{int(reaction['removed_at'])}:R>"
                        for reaction in reactions
                    ],
                ),
            ),
            text="reaction",
        )

    @group(
        name="remind",
        usage="(duration) (text)",
        example="1h go to the gym",
        aliases=["reminder"],
        invoke_without_command=True,
    )
    @require_dm()
    async def remind(
        self: "Miscellaneous",
        ctx: Context,
        duration: TimeConverter,
        *,
        text: str,
    ):
        """Set a reminder"""
        if duration.seconds < 60:
            return await ctx.error("Duration must be at least **1 minute**")

        try:
            await self.bot.db.execute(
                "INSERT INTO reminders (user_id, text, jump_url, created_at, timestamp) VALUES ($1, $2, $3, $4, $5)",
                ctx.author.id,
                text,
                ctx.message.jump_url,
                ctx.message.created_at,
                ctx.message.created_at + duration.delta,
            )

        except Exception:
            return await ctx.error(f"Already being reminded for **{text}**")

        await ctx.approve(
            f"I'll remind you {format_dt(ctx.message.created_at + duration.delta, style='R')}"
        )

    @remind.command(
        name="remove",
        usage="(text)",
        example="go to the gym",
        aliases=["delete", "del", "rm", "cancel"],
    )
    async def remove(self: "Miscellaneous", ctx: Context, *, text: str):
        """Remove a reminder"""
        try:
            await self.bot.db.execute(
                "DELETE FROM reminders WHERE user_id = $1 AND lower(text) = $2",
                ctx.author.id,
                text.lower(),
            )
        except Exception:
            return await ctx.error(f"Coudn't find a reminder for **{text}**")

        return await ctx.approve(f"Removed reminder for **{text}**")

    @remind.command(
        name="list",
        aliases=["show", "view"],
    )
    async def reminders(self: "Miscellaneous", ctx: Context):
        """View your pending reminders"""
        reminders = await self.bot.db.fetch(
            "SELECT * FROM reminders WHERE user_id = $1", ctx.author.id
        )

        if not reminders:
            return await ctx.error("You don't have any **reminders**")

        await ctx.paginate(
            Embed(
                title="Reminders",
                description="\n".join(
                    [
                        f"**{shorten(reminder['text'], 23)}** ({format_dt(reminder['timestamp'], style='R')})"
                        for reminder in reminders
                    ],
                ),
            )
        )

    @group(
        name="highlight",
        usage="(subcommand) <args>",
        example="add angel",
        aliases=["hl", "snitch"],
        invoke_without_command=True,
    )
    async def highlight(self: "Miscellaneous", ctx: Context):
        """Notify you when a keyword is mentioned"""
        await ctx.send_help()

    @highlight.command(
        name="add",
        usage="(word)",
        example="angel",
        parameters={
            "strict": {
                "require_value": False,
                "description": "Whether the message should be a strict match",
            }
        },
        aliases=["create", "new"],
    )
    @require_dm()
    async def highlight_add(self: "Miscellaneous", ctx: Context, *, word: str):
        """Add a keyword to notify you about"""
        word = word.lower()

        if escape_mentions(word) != word:
            return await ctx.error("Your keyword can't contain mentions")
        if len(word) < 2:
            return await ctx.error(
                "Your keyword must be at least **2 characters** long"
            )
        if len(word) > 32:
            return await ctx.error(
                "Your keyword can't be longer than **32 characters**"
            )

        try:
            await self.bot.db.execute(
                "INSERT INTO highlight_words (user_id, word, strict) VALUES ($1, $2, $3)",
                ctx.author.id,
                word,
                ctx.parameters.get("strict"),
            )
        except Exception:
            return await ctx.error(f"You're already being notified about `{word}`")

        await ctx.approve(
            f"You'll now be notified about `{word}` "
            + ("(strict)" if ctx.parameters.get("strict") else "")
        )

    @highlight.command(
        name="remove",
        usage="(word)",
        example="angel",
        aliases=["delete", "del", "rm"],
    )
    async def highlight_remove(self: "Miscellaneous", ctx: Context, *, word: str):
        """Remove a keyword to notify you about"""
        query = """
                DELETE FROM highlight_words
                WHERE user_id = $1 AND word = $2
                RETURNING 1;
            """

        if await self.bot.db.fetch(query, ctx.author.id, word.lower()):
            return await ctx.approve(f"You won't be notified about `{word}` anymore")

        await ctx.error(f"You're not being notified about `{word}`")

    @highlight.command(
        name="block",
        usage="(entity)",
        example="#chat",
        aliases=["ignore"],
    )
    async def highlight_block(
        self: "Miscellaneous",
        ctx: Context,
        *,
        entity: TextChannel | CategoryChannel | Member | User,
    ):
        """Block a channel or user from notifying you"""
        if entity.id == ctx.author.id:
            return await ctx.error("You can't ignore yourself")
        try:
            await self.bot.db.execute(
                "INSERT INTO highlight_block (user_id, entity_id) VALUES ($1, $2)",
                ctx.author.id,
                entity.id,
            )
        except Exception:
            return await ctx.error(
                f"You're already ignoring [**{entity}**]({entity.jump_url if isinstance(entity, (TextChannel, CategoryChannel)) else 'https://discord.gg/pFK6erfxCp'})"
            )

        await ctx.approve(
            f"Ignoring [**{entity}**]({entity.jump_url if isinstance(entity, (TextChannel, CategoryChannel)) else 'https://discord.gg/pFK6erfxCp'})"
        )

    @highlight.command(
        name="unblock",
        usage="(entity)",
        example="#chat",
        aliases=["unignore"],
    )
    async def highlight_unblock(
        self: "Miscellaneous",
        ctx: Context,
        *,
        entity: TextChannel | CategoryChannel | Member | User,
    ):
        """Unignore a user or channel"""
        query = """
                DELETE FROM highlight_block
                WHERE user_id = $1 AND entity_id = $2
                RETURNING 1;
            """

        if await self.bot.db.fetch(query, ctx.author.id, entity.id):
            return await ctx.approve(
                f"No longer ignoring [**{entity}**]({entity.jump_url if isinstance(entity, (TextChannel, CategoryChannel)) else 'https://discord.gg/pFK6erfxCp'})"
            )

        await ctx.error(
            f"You're not ignoring [**{entity}**]({entity.jump_url if isinstance(entity, (TextChannel, CategoryChannel)) else 'https://discord.gg/pFK6erfxCp'})"
        )

    @highlight.command(
        name="list",
        aliases=["show", "view", "blocked"],
    )
    async def highlight_list(self: "Miscellaneous", ctx: Context):
        """View your highlighted keywords"""
        keywords = await self.bot.db.fetch(
            "SELECT word, strict FROM highlight_words WHERE user_id = $1",
            ctx.author.id,
        )

        if not keywords:
            return await ctx.error("You don't have any **highlighted keywords**")

        await ctx.paginate(
            Embed(
                title="Highlighted Keywords",
                description="\n".join(
                    [
                        f"**{keyword['word']}**"
                        + (" (strict)" if keyword["strict"] else "")
                        for keyword in keywords
                    ],
                ),
            )
        )

    @group(
        name="namehistory",
        usage="<user>",
        example="pumpumpal",
        aliases=["names", "nh"],
        invoke_without_command=True,
    )
    async def namehistory(
        self: "Miscellaneous", ctx: Context, *, user: Member | User = None
    ):
        """View a user's name history"""
        user = user or ctx.author

        names = await self.bot.db.fetch(
            "SELECT name, timestamp FROM metrics.names WHERE user_id = $1 ORDER BY timestamp DESC",
            user.id,
        )
        if not names:
            return await ctx.error(
                "You don't have any **names** in the database"
                if user == ctx.author
                else f"**{user}** doesn't have any **names** in the database"
            )

        await ctx.paginate(
            Embed(
                title="Name History",
                description="\n".join(
                    [
                        f"**{name['name']}** ({format_dt(name['timestamp'], style='R')})"
                        for name in names
                    ],
                ),
            )
        )

    @namehistory.command(
        name="reset",
        aliases=["clear", "wipe", "delete", "del", "rm"],
    )
    @donator(booster=True)
    async def namehistory_reset(self: "Miscellaneous", ctx: Context):
        """Reset your name history"""
        await self.bot.db.execute(
            "DELETE FROM metrics.names WHERE user_id = $1", ctx.author.id
        )
        await ctx.approve("Cleared your **name history**")

    @command(
        name="image",
        usage="(query)",
        example="Clairo",
        aliases=["img", "im", "i"],
    )
    async def image(self: "Miscellaneous", ctx: Context, *, query: str):
        """Search Google for an image"""
        response = await self.bot.session.get(
            "https://notsobot.com/api/search/google/images",
            params=dict(
                query=query.replace(" ", ""),
                safe="false" if ctx.channel.is_nsfw() else "true",
            ),
        )
        data = await response.json()

        if not data:
            return await ctx.error(f"Couldn't find any images for **{query}**")

        entries = [
            Embed(
                url=entry.get("url"),
                title=entry.get("header"),
                description=entry.get("description"),
            ).set_image(url=entry["image"]["url"])
            for entry in data
            if entry.get("header") not in ("TikTok", "Facebook", "Instagram")
        ]
        await ctx.paginate(entries)

    @command(
        name="urban",
        usage="(query)",
        example="self-projecting",
        aliases=["urbandictionary", "ud"],
    )
    async def urban(self: "Miscellaneous", ctx: Context, *, query: str):
        """Search for a definition on Urban Dictionary"""
        response = await self.bot.session.request(
            "GET",
            "http://api.urbandictionary.com/v0/define",
            params=dict(term=query),
        )

        if not response.list:
            return await ctx.error(f"Couldn't find any definitions for **{query}**")

        def repl(match):
            word = match.group(2)
            return f"[{word}](https://{word.replace(' ', '-')}.urbanup.com)"

        entries = [
            Embed(
                url=entry.permalink,
                title=entry.word,
                description=re_compile(r"(\[(.+?)\])").sub(repl, entry.definition),
            )
            .add_field(
                name="Example",
                value=re_compile(r"(\[(.+?)\])").sub(repl, entry.example),
                inline=False,
            )
            .set_footer(
                text=f"👍 {entry.thumbs_up:,} 👎 {entry.thumbs_down:,} - {entry.word}"
            )
            for entry in response.list
        ]
        await ctx.paginate(entries)

    @command(
        name="translate",
        usage="<language> (text)",
        example="Spanish Hello!",
        aliases=["tr"],
    )
    async def translate(
        self: "Miscellaneous",
        ctx: Context,
        language: Language | None = "en",
        *,
        text: str,
    ):
        """Translate text to another language"""

        async with ctx.typing():
            response = await self.bot.session.request(
                "GET",
                "https://clients5.google.com/translate_a/single",
                params={
                    "dj": "1",
                    "dt": ["sp", "t", "ld", "bd"],
                    "client": "dict-chrome-ex",
                    "sl": "auto",
                    "tl": language,
                    "q": text,
                },
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/104.0.0.0 Safari/537.36"
                },
            )
            if not response:
                return await ctx.error("Couldn't **translate** the **text**")

            text = "".join(sentence.trans for sentence in response.sentences)
            if not text:
                return await ctx.error("Couldn't **translate** the **text**")

        if ctx.author.mobile_status != Status.offline:
            return await ctx.reply(text)

        embed = Embed(
            title="Google Translate",
            description=f"```{text[:4000]}```",
        )
        await ctx.reply(embed=embed)

    @command(
        name="wolfram",
        usage="(query)",
        example="integral of x^2",
        aliases=["wolframalpha", "wa", "w"],
    )
    async def wolfram(self: "Miscellaneous", ctx: Context, *, query: str):
        """Search a query on Wolfram Alpha"""

        async with ctx.typing():
            response = await self.bot.session.request(
                "GET",
                "https://api.wolframalpha.com/v2/query",
                params=dict(
                    input=query,
                    appid=config.Authorization.wolfram,
                    output="json",
                ),
            )

            if not response.fields:
                return await ctx.error("Couldn't **understand** your input")

            embed = Embed(
                title=response.title,
                url=response.url,
            )

            for index, field in enumerate(response.fields[:4]):
                if index == 2:
                    continue

                embed.add_field(
                    name=field.name,
                    value=(">>> " if index == 3 else "")
                    + field.value.replace("( ", "(")
                    .replace(" )", ")")
                    .replace("(", "(`")
                    .replace(")", "`)"),
                    inline=index != 3,
                )
            embed.set_footer(
                text="Wolfram Alpha",
                icon_url="https://cdn.discordapp.com/attachments/1247539606212317275/1247542047787978782/20220521192226_24ef0.gif?ex=66606792&is=665f1612&hm=005672bb28f2482d29b098967aa8f224fcc4c8fe34a4a444bf51d870faf8468d&",
            )
        await ctx.send(embed=embed)

    @command(name="afk", usage="<status>", example="sleeping...(slart)")
    async def afk(self: "Miscellaneous", ctx: Context, *, status: str = "AFK"):
        """Set an AFK status for when you are mentioned"""
        status = shorten(status, 100)
        await self.bot.db.execute(
            """
            INSERT INTO afk (
                user_id,
                message,
                timestamp
            ) VALUES ($1, $2, $3)
            ON CONFLICT (user_id)
            DO NOTHING;
            """,
            ctx.author.id,
            status,
            ctx.message.created_at,
        )

        await ctx.approve(f"You're now AFK with the status: **{status}**")

    @command(
        name="createembed",
        usage="(embed script)",
        example="{title: wow!}",
        aliases=["embed", "ce"],
    )
    async def createembed(
        self: "Miscellaneous", ctx: Context, *, script: EmbedScriptValidator
    ):
        """Send an embed to the channel"""
        await script.send(
            ctx,
            bot=self.bot,
            guild=ctx.guild,
            channel=ctx.channel,
            user=ctx.author,
        )

    @command(
        name="copyembed",
        usage="(message)",
        example="dscord.com/chnls/999/..",
        aliases=["embedcode", "ec"],
    )
    async def copyembed(self: "Miscellaneous", ctx: Context, message: Message):
        """Copy embed code for a message"""
        result = []
        if content := message.content:
            result.append(f"{{content: {content}}}")

        for embed in message.embeds:
            result.append("{embed}")
            if color := embed.color:
                result.append(f"{{color: {color}}}")

            if author := embed.author:
                _author = []
                if name := author.name:
                    _author.append(name)
                if icon_url := author.icon_url:
                    _author.append(icon_url)
                if url := author.url:
                    _author.append(url)

                result.append(f"{{author: {' && '.join(_author)}}}")

            if url := embed.url:
                result.append(f"{{url: {url}}}")

            if title := embed.title:
                result.append(f"{{title: {title}}}")

            if description := embed.description:
                result.append(f"{{description: {description}}}")

            result.extend(
                f"{{field: {field.name} && {field.value} && {str(field.inline).lower()}}}"
                for field in embed.fields
            )
            if thumbnail := embed.thumbnail:
                result.append(f"{{thumbnail: {thumbnail.url}}}")

            if image := embed.image:
                result.append(f"{{image: {image.url}}}")

            if footer := embed.footer:
                _footer = []
                if text := footer.text:
                    _footer.append(text)
                if icon_url := footer.icon_url:
                    _footer.append(icon_url)

                result.append(f"{{footer: {' && '.join(_footer)}}}")

            if timestamp := embed.timestamp:
                result.append(f"{{timestamp: {str(timestamp)}}}")

        if not result:
            return await ctx.error(
                f"Message [`{message.id}`]({message.jump_url}) doesn't contain an embed"
            )

        result = "\n".join(result)
        return await ctx.approve(f"Copied the **embed code**\n```{result}```")

    @command(
        name="synth",
        usage="<engine> (text)",
        example="ghostface hey mommy",
        aliases=["synthesizer", "synthesize", "tts"],
    )
    async def synth(self, ctx: Context, engine: SynthEngine | None, *, text: str):
        """Synthesize text into speech"""

        async with ctx.typing():
            response = await self.bot.session.post(
                "https://api16-normal-useast5.us.tiktokv.com/media/api/text/speech/invoke/",
                params=dict(
                    text_speaker=engine or "en_us_002",
                    req_text=text.replace("+", "plus")
                    .replace("-", "minus")
                    .replace("=", "equals")
                    .replace("/", "slash")
                    .replace("@", "at")[:300],
                    speaker_map_type=0,
                    aid=1233,
                ),
                headers={
                    "User-Agent": "com.zhiliaoapp.musically/2022600030 (Linux; U; Android 7.1.2; es_ES; SM-G988N; Build/NRD90M;tt-ok/3.12.13.1)",
                    "Cookie": "sessionid=" + "3797e14bf07c613de9b8b3663a6f2861",
                },
            )
            data = await response.json()

        if data["status_code"] != 0:
            return await ctx.error("Couldn't **synthesize** text")

        vstr: str = data["data"]["v_str"]
        _padding = len(vstr) % 4
        vstr += "=" * _padding

        decoded = b64decode(vstr)
        clean_data = BytesIO(decoded)
        clean_data.seek(0)

        file = File(fp=clean_data, filename="Synthesize.mp3")
        await ctx.reply(file=file)

    @command(
        name="transparent",
        usage="(image)",
        example="dscord.com/chnls/999/..png",
        aliases=["tp"],
    )
    @donator()
    @cooldown(1, 10, BucketType.user)
    @max_concurrency(1, BucketType.user)
    async def transparent(self, ctx: Context, *, image: ImageFinderStrict = None):
        """Remove the background of an image"""
        image = image or await ImageFinderStrict.search(ctx)

        async with ctx.typing():
            response = await self.bot.session.get(image)
            if sys.getsizeof(response.content) > 15728640:
                return await ctx.error(
                    "Image is too large to make **transparent** (max 15MB)"
                )

            image = await response.read()

            with TemporaryDirectory() as temp_dir:
                temp_file = os.path.join(
                    temp_dir,
                    f"file{hash(str(response.url))}."
                    + IMAGE_URL.match(str(response.url)).group("mime"),
                )
                temp_file_output = os.path.join(
                    temp_dir,
                    f"file{hash(str(response.url))}_output."
                    + IMAGE_URL.match(str(response.url)).group("mime"),
                )
                async with async_open(temp_file, "wb") as file:
                    await file.write(image)

                try:
                    response = await self.bot.session.post(
                        "https://api.remove.bg/v1.0/removebg",
                        headers={"X-API-Key": config.Authorization.removebg},
                        params=dict(size="auto"),
                        data=dict(image_file=open(temp_file, "rb")),
                    )
                    response.raise_for_status()
                    async with async_open(temp_file_output, "wb") as file:
                        await file.write(await response.read())
                except Exception:
                    return await ctx.error("Couldn't make image **transparent**")

                if not os.path.exists(temp_file_output):
                    return await ctx.error("Couldn't make image **transparent**")

                await ctx.reply(
                    file=File(temp_file_output, filename="pumpumpalTransparent.png")
                )

    @command(
        name="screenshot",
        aliases=["ss"],
        usage="(url) <flags>",
        example="https://shiro.wtf --full-page --delay 5",
    )

    async def screenshot(
        self: "Miscellaneous",
        ctx: Context,
        url: str,
        *,
        flags: Optional[dict] = None,
    ):
        """Takes a screenshot of a website using ScreenshotOne API."""

        if not url.startswith("http"):
            return await ctx.send("The URL provided is invalid!")

        # Default flags if not provided
        flags = flags or {}
        full_page = flags.get("full_page", False)
        delay = int(flags.get("delay", 0))

        api_url = "https://api.screenshotone.com/take"
        params = {
            "access_key": "JIpTxMx2dFvQ5A",
            "url": url,
            "full_page": str(full_page).lower(),
            "viewport_width": "1920",
            "viewport_height": "1080",
            "device_scale_factor": "1",
            "format": "jpg",
            "image_quality": "80",
            "block_ads": "true",
            "block_cookie_banners": "true",
            "block_banners_by_heuristics": "false",
            "block_trackers": "true",
            "delay": str(delay),
            "timeout": "60",
        }

        async with ctx.typing():
            async with aiohttp.ClientSession() as session:
                try:
                    async with session.get(api_url, params=params) as response:
                        if response.status == 200:
                            buffer = BytesIO(await response.read())
                            buffer.seek(0)

                            embed = Embed(description=f"> [*`{url}`*]")
                            embed.set_image(url="attachment://screenshot.jpg")
                            embed.set_footer(
                                text=(
                                    f"Requested by {ctx.author}"
                                    + (f" ∙ {delay}s delay" if delay else "")
                                    + (" ∙ Full page" if full_page else "")
                                ),
                            )

                            await ctx.send(
                                embed=embed,
                                file=File(
                                    buffer,
                                    filename="screenshot.jpg",
                                ),
                            )
                        else:
                            await ctx.send(f"Failed to take screenshot. Status code: {response.status}")

                except Exception as e:
                    await ctx.send(f"An error occurred: {e}")

    @group(
        name="compile",
        aliases=[
            "build",
            "eval",
            "run",
        ],
        invoke_without_command=True,
    )
    async def compile(
        self: "Miscellaneous",
        ctx: Context,
        *,
        code: Codeblock = param(
            converter=codeblock_converter,
            description="The code to compile.",
        ),
    ):
        """
        Evaluate code through a private Piston instance.

        The language is automatically detected from the codeblock language,
        if it's not specified, it will default to `python`.

        > Below is a **Hello world** example using `rust` as the language.
        ```rust
        fn main() {
            println!("Hello, world!");
        }
        ```
        """

        async with ctx.typing():
            language = code.language or "python"

            runtimes: List[Munch] = await self.bot.session.request(
                "https://emkc.org/api/v2/piston/runtimes",
            )
            runtime: Optional[Munch] = find(
                lambda runtime: (
                    language.lower() == runtime.language
                    or language.lower() in runtime.aliases
                ),
                runtimes,
            )
            if not runtime:
                return await ctx.error(
                    f"Couldn't find a runtime for `{code.language}`!"
                )

            data: PistonExecute = await self.bot.session.request(
                "POST",
                "https://emkc.org/api/v2/piston/execute",
                json={
                    "language": runtime.language,
                    "version": runtime.version,
                    "files": [
                        {
                            "name": xxh128_hexdigest(code.content),
                            "content": code.content,
                        },
                    ],
                },
            )

        embeds = []
        for chunk in as_chunks(data.run.output, 2000):
            chunk = "".join(chunk)

            embed = Embed(
                description=(
                    f"> Compiled `{data.language}` code.\n"
                    f"```{runtime.language}\n{chunk}```"
                ),
            )
            embeds.append(embed)

        if not embeds:
            return await ctx.error("No output was returned.")

        return await ctx.paginate(embeds)

    @compile.command(
        name="runtimes",
        aliases=[
            "languages",
            "langs",
        ],
    )
    async def compile_runtimes(self: "Miscellaneous", ctx: Context):
        """View all available runtimes."""
        runtimes: List[PistonRuntime] = await self.bot.session.request(
            "https://emkc.org/api/v2/piston/runtimes",
        )

        embeds = []
        for chunk in as_chunks(
            [
                (
                    f"**{runtime.language}** (`v{runtime.version}`)"
                    + (f" | *{', '.join(runtime.aliases)}*" if runtime.aliases else "")
                )
                for runtime in runtimes
            ],
            2000,
        ):
            embed = Embed(
                description="\n".join(chunk),
                title="Available Runtimes",
            )
            embeds.append(embed)

        return await ctx.paginate(embeds)
