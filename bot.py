import os
import random
import time
from dataclasses import dataclass
from typing import Dict, Optional

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = int(os.getenv("GUILD_ID", "0"))

DEFAULT_START = 100
CHALLENGE_TIMEOUT = 120

### Simple Deathroll
PREFIX = "!"
intents.message_content = True
client = discord.Client(intents=intents)

@dataclass
class Game:
    game_id: str
    origin_channel_id: int
    game_channel_id: int
    challenger_id: int
    opponent_id: int
    current_max: int
    turn_id: Optional[int]
    status: str  # pending | active | finished
    message_id: Optional[int]
    created_at: float
    use_thread: bool


games: Dict[str, Game] = {}


intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)


def game_embed(g: Game, extra_line: Optional[str] = None) -> discord.Embed:
    embed = discord.Embed(title="🎲 Deathroll", color=discord.Color.blurple())

    embed.add_field(
        name="Players",
        value=f"<@{g.challenger_id}> vs <@{g.opponent_id}>",
        inline=False,
    )

    embed.add_field(
        name="Current Max",
        value=f"**{g.current_max}**",
        inline=True,
    )

    if g.status == "active":
        embed.add_field(
            name="Turn",
            value=f"<@{g.turn_id}>",
            inline=True,
        )
    elif g.status == "finished":
        embed.add_field(
            name="Status",
            value="Game Over",
            inline=True,
        )

    if extra_line:
        embed.add_field(name="Last Roll", value=extra_line, inline=False)

    return embed


class RollView(discord.ui.View):
    def __init__(self, game_id: str):
        super().__init__(timeout=None)
        self.game_id = game_id

    @discord.ui.button(label="Roll 🎲", style=discord.ButtonStyle.primary)
    async def roll(self, interaction: discord.Interaction, button: discord.ui.Button):
        g = games.get(self.game_id)
        if not g or g.status != "active":
            return await interaction.response.send_message("Game not active.", ephemeral=True)

        if interaction.user.id != g.turn_id:
            return await interaction.response.send_message("Not your turn.", ephemeral=True)

        roll = random.randint(1, g.current_max)
        prev_max = g.current_max

        # Lose condition
        if roll == 1:
            g.status = "finished"
            games[self.game_id] = g

            winner = g.opponent_id if interaction.user.id == g.challenger_id else g.challenger_id

            embed = game_embed(
                g,
                extra_line=f"<@{interaction.user.id}> rolled **1** (1–{prev_max}) 💀\n"
                           f"🏆 Winner: <@{winner}>",
            )

            button.disabled = True
            await interaction.response.edit_message(embed=embed, view=self)
            return

        # Continue game
        g.current_max = roll
        g.turn_id = g.opponent_id if interaction.user.id == g.challenger_id else g.challenger_id
        games[self.game_id] = g

        embed = game_embed(
            g,
            extra_line=f"<@{interaction.user.id}> rolled **{roll}** (1–{prev_max})",
        )

        await interaction.response.edit_message(embed=embed, view=self)


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")

    if GUILD_ID:
        guild = discord.Object(id=GUILD_ID)
        bot.tree.copy_global_to(guild=guild)
        await bot.tree.sync(guild=guild)
    else:
        await bot.tree.sync()

@bot.tree.command(name="deathroll", description="Challenge someone to a deathroll.")
@app_commands.describe(
    opponent="Who you want to deathroll",
    start="Starting max (default 100)",
    thread="Create a thread (default true)",
)
async def deathroll(
    interaction: discord.Interaction,
    opponent: discord.Member,
    start: Optional[int] = None,
    thread: Optional[bool] = True,
):
    if opponent.bot:
        return await interaction.response.send_message("You can't challenge a bot.", ephemeral=True)

    if opponent.id == interaction.user.id:
        return await interaction.response.send_message("You can't challenge yourself.", ephemeral=True)

    start_val = start or DEFAULT_START

    game_id = str(interaction.id)

    g = Game(
        game_id=game_id,
        origin_channel_id=interaction.channel_id,
        game_channel_id=interaction.channel_id,
        challenger_id=interaction.user.id,
        opponent_id=opponent.id,
        current_max=start_val,
        turn_id=None,
        status="pending",
        message_id=None,
        created_at=time.time(),
        use_thread=bool(thread),
    )

    games[game_id] = g

    view = discord.ui.View(timeout=CHALLENGE_TIMEOUT)

    async def accept(i: discord.Interaction):
        if i.user.id != g.opponent_id:
            return await i.response.send_message("Only the challenged user can accept.", ephemeral=True)

        await i.response.defer()

        g.status = "active"
        g.turn_id = random.choice([g.challenger_id, g.opponent_id])

        channel_id = g.origin_channel_id


        if g.use_thread and isinstance(i.channel, discord.TextChannel):
            try:
                th = await i.channel.create_thread(
                    name=f"deathroll-{game_id[:6]}",
                    auto_archive_duration=60,
                    type=discord.ChannelType.public_thread,
                )
                channel_id = th.id
            except Exception as e:
                print("Thread creation failed:", repr(e))

        g.game_channel_id = channel_id
        games[game_id] = g

        for item in view.children:
            item.disabled = True

        await i.edit_original_response(content="Challenge accepted!", view=view)

        ch = await bot.fetch_channel(channel_id)

        embed = game_embed(g)

        msg = await ch.send(embed=embed, view=RollView(game_id))
        g.message_id = msg.id
        games[game_id] = g

    async def decline(i: discord.Interaction):
        if i.user.id != g.opponent_id:
            return await i.response.send_message("Only the challenged user can decline.", ephemeral=True)

        g.status = "finished"
        games[game_id] = g

        for item in view.children:
            item.disabled = True

        await i.response.edit_message(content="Challenge declined.", view=view)

    accept_btn = discord.ui.Button(label="Accept", style=discord.ButtonStyle.success)
    decline_btn = discord.ui.Button(label="Decline", style=discord.ButtonStyle.danger)

    accept_btn.callback = accept
    decline_btn.callback = decline

    view.add_item(accept_btn)
    view.add_item(decline_btn)

    await interaction.response.send_message(
        content=f"🎲 {interaction.user.mention} challenges {opponent.mention} to a deathroll!\nStart: **{start_val}**",
        view=view,
    )

### Simple Deathroll

@client.event
async def on_message(message: discord.Message):
    # Ignore messages from the bot itself
    if message.author == client.user:
        return

    # Check for the !roll command
    if message.content.startswith(f"{PREFIX}roll"):
        parts = message.content.strip().split()

        # Validate usage: must be exactly "!roll <number>"
        if len(parts) != 2:
            await message.channel.send(
                f"{message.author.mention} Usage: `!roll <number>` (number must be between 1 and 100000)"
            )
            return

        # Validate that the argument is a valid integer
        try:
            max_num = int(parts[1])
        except ValueError:
            await message.channel.send(
                f"{message.author.mention} That's not a valid number. Usage: `!roll <number>`"
            )
            return

        # Validate the range
        if not (1 <= max_num <= 100_000):
            await message.channel.send(
                f"{message.author.mention} Please pick a number between **1** and **100,000**."
            )
            return

        # Roll!
        result = random.randint(1, max_num)
        await message.channel.send(
            f"{message.author.mention} rolled a **{result:,}** (1–{max_num:,})"
        )


if not TOKEN:
    raise RuntimeError("Missing DISCORD_TOKEN")

bot.run(TOKEN)
