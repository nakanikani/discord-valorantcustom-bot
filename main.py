import os
import random
import requests
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

# ランクと内部レート（ポイント）の定義
RANK_RATING = {
    "アイアン": 1, "ブロンズ": 2, "シルバー": 3,
    "ゴールド": 4, "プラチナ": 5, "ダイヤ": 6,
    "アセンダント": 7, "イモータル": 8, "レディアント": 9,
    "Unranked": 3  # デフォルト（シルバー相当）
}

# ユーザー情報データベース（簡易メモリ保持）
# 構造: { user_id: {"riot_id": "Name#Tag", "rank": "ゴールド", "rating": 4} }
user_db = {}

# VALORANT APIからランクを取得する関数 (HenrikDev API使用)
def fetch_valorant_rank(riot_id):
    try:
        if "#" not in riot_id:
            return None
        name, tag = riot_id.split("#", 1)
        url = f"https://api.henrikdev.xyz/valorant/v1/mmr/ap/{name}/{tag}"
        res = requests.get(url, timeout=5)
        if res.status_code == 200:
            data = res.json()
            tier_name = data.get("data", {}).get("currenttierpatched", "Unranked")
            # メインランク名（例: "Gold 1" -> "ゴールド"）の簡易判定
            for jp_rank in RANK_RATING.keys():
                if jp_rank.lower() in tier_name.lower():
                    return jp_rank
            return "Unranked"
    except Exception as e:
        print(f"API Error: {e}")
    return None

# --- UI (ボタン制御) ---
class CustomView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.participants = []

    @discord.ui.button(label="参加する", style=discord.ButtonStyle.green, custom_id="join_btn")
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user in self.participants:
            await interaction.response.send_message("すでに参加しています！", ephemeral=True)
            return
        self.participants.append(interaction.user)
        
        # ランク未設定の場合はデフォルト割り当て
        if interaction.user.id not in user_db:
            user_db[interaction.user.id] = {"riot_id": "未登録", "rank": "Unranked", "rating": 3}

        await interaction.response.send_message(f"{interaction.user.mention} が参加しました！", ephemeral=False)
        await self.update_embed(interaction)

    @discord.ui.button(label="辞退する", style=discord.ButtonStyle.red, custom_id="leave_btn")
    async def leave(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user not in self.participants:
            await interaction.response.send_message("参加していません。", ephemeral=True)
            return
        self.participants.remove(interaction.user)
        await interaction.response.send_message(f"{interaction.user.mention} が辞退しました。", ephemeral=False)
        await self.update_embed(interaction)

    @discord.ui.button(label="均等チーム分け実行", style=discord.ButtonStyle.blurple, custom_id="split_btn")
    async def split_teams(self, interaction: discord.Interaction, button: discord.ui.Button):
        if len(self.participants) < 2:
            await interaction.response.send_message("チーム分けには最低2人必要です！", ephemeral=True)
            return

        # レート順にソートして蛇行（スネーク）ドラフトでチーム分け
        players = self.participants.copy()
        players.sort(key=lambda p: user_db.get(p.id, {}).get("rating", 3), reverse=True)

        team_a, team_b = [], []
        for i, player in enumerate(players):
            if (i // 1) % 2 == 0:
                team_a.append(player)
            else:
                team_b.append(player)

        def fmt_team(team):
            lines = []
            for p in team:
                info = user_db.get(p.id, {"rank": "Unranked"})
                lines.append(f"• {p.display_name} ({info['rank']})")
            return "\n".join(lines) or "なし"

        embed = discord.Embed(title="⚔️ ランク均等 チーム分け結果", color=discord.Color.gold())
        embed.add_field(name="🔴 チーム A", value=fmt_team(team_a), inline=True)
        embed.add_field(name="🔵 チーム B", value=fmt_team(team_b), inline=True)

        await interaction.response.send_message(embed=embed)

    async def update_embed(self, interaction: discord.Interaction):
        lines = []
        for p in self.participants:
            info = user_db.get(p.id, {"rank": "Unranked"})
            lines.append(f"• {p.display_name} [{info['rank']}]")
        
        member_list = "\n".join(lines) or "なし"
        embed = discord.Embed(
            title="🎮 VALORANT カスタム募集",
            description=f"**【参加者一覧】 ({len(self.participants)}人)**\n{member_list}",
            color=discord.Color.blue()
        )
        await interaction.message.edit(embed=embed, view=self)

# --- コマンド群 ---
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

# 1. API自動連携コマンド
@bot.command()
async def register(ctx, riot_id: str):
    rank = fetch_valorant_rank(riot_id)
    if not rank:
        rank = "Unranked"
    
    rating = RANK_RATING.get(rank, 3)
    user_db[ctx.author.id] = {"riot_id": riot_id, "rank": rank, "rating": rating}
    await ctx.send(f"✅ {ctx.author.mention} さんの Riot ID (`{riot_id}`) を登録しました！（取得ランク: **{rank}**）")

# 2. 手動ランク設定（補正）コマンド
@bot.command()
async def setrank(ctx, rank_name: str):
    if rank_name not in RANK_RATING:
        ranks_str = ", ".join(RANK_RATING.keys())
        await ctx.send(f"⚠️ 指定できるランク: `{ranks_str}`")
        return
    
    rating = RANK_RATING[rank_name]
    if ctx.author.id not in user_db:
        user_db[ctx.author.id] = {"riot_id": "未登録", "rank": rank_name, "rating": rating}
    else:
        user_db[ctx.author.id]["rank"] = rank_name
        user_db[ctx.author.id]["rating"] = rating

    await ctx.send(f"✏️ {ctx.author.mention} さんのランクを **{rank_name}** に更新しました！")

# 起動処理
keep_alive()
TOKEN = os.environ.get("DISCORD_TOKEN")
if TOKEN:
    bot.run(TOKEN)