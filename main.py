import os
import random
from threading import Thread
from flask import Flask
import discord
from discord.ext import commands

# --- Render対策: Webサーバー ---
app = Flask('')

@app.route('/')
def home():
    return "Bot is running!"

def keep_alive():
    t = Thread(target=lambda: app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080))))
    t.start()

# --- Discord Bot 設定 ---
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# --- カスタム募集UI（ボタン制御） ---
class CustomView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None) # 永続ボタン
        self.participants = []

    @discord.ui.button(label="参加する", style=discord.ButtonStyle.green, custom_id="join_btn")
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user in self.participants:
            await interaction.response.send_message("すでに参加しています！", ephemeral=True)
            return
        self.participants.append(interaction.user)
        await interaction.response.send_message(f"{interaction.user.mention} が参加しました！", ephemeral=False)
        await self.update_embed(interaction)

    @discord.ui.button(label="キャンセル", style=discord.ButtonStyle.red, custom_id="leave_btn")
    async def leave(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user not in self.participants:
            await interaction.response.send_message("参加していません。", ephemeral=True)
            return
        self.participants.remove(interaction.user)
        await interaction.response.send_message(f"{interaction.user.mention} が辞退しました。", ephemeral=False)
        await self.update_embed(interaction)

    @discord.ui.button(label="チーム分け実行", style=discord.ButtonStyle.blurple, custom_id="split_btn")
    async def split_teams(self, interaction: discord.Interaction, button: discord.ui.Button):
        if len(self.participants) < 2:
            await interaction.response.send_message("チーム分けには最低2人必要です！", ephemeral=True)
            return

        players = self.participants.copy()
        random.shuffle(players)
        
        mid = len(players) // 2
        team_a = players[:mid]
        team_b = players[mid:]

        team_a_str = "\n".join([p.display_name for p in team_a])
        team_b_str = "\n".join([p.display_name for p in team_b])

        embed = discord.Embed(title="⚔️ チーム分け結果", color=discord.Color.gold())
        embed.add_field(name="🔴 チーム A", value=team_a_str or "なし", inline=True)
        embed.add_field(name="🔵 チーム B", value=team_b_str or "なし", inline=True)

        await interaction.response.send_message(embed=embed)

    async def update_embed(self, interaction: discord.Interaction):
        # 参加者一覧の埋め込みメッセージを更新
        member_list = "\n".join([p.display_name for p in self.participants]) or "なし"
        embed = discord.Embed(
            title="🎮 VALORANT カスタム募集",
            description=f"**【参加者一覧】 ({len(self.participants)}人)**\n{member_list}",
            color=discord.Color.blue()
        )
        await interaction.message.edit(embed=embed, view=self)

# --- コマンド ---
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user.name}")

@bot.command()
async def custom(ctx):
    embed = discord.Embed(
        title="🎮 VALORANT カスタム募集",
        description="**【参加者一覧】 (0人)**\nなし",
        color=discord.Color.blue()
    )
    await ctx.send(embed=embed, view=CustomView())

# 起動処理
keep_alive()
TOKEN = os.environ.get("DISCORD_TOKEN")
if TOKEN:
    bot.run(TOKEN)