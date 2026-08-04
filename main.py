import os
import random
import re
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
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

# ランク表記ゆれ変換マップ
RANK_ALIASES = {
    "iron": "アイアン", "i": "アイアン", "アイアン": "アイアン",
    "bronze": "ブロンズ", "b": "ブロンズ", "ブロンズ": "ブロンズ",
    "silver": "シルバー", "s": "シルバー", "シルバー": "シルバー",
    "gold": "ゴールド", "g": "ゴールド", "ゴールド": "ゴールド",
    "platinum": "プラチナ", "plat": "プラチナ", "p": "プラチナ", "プラチナ": "プラチナ",
    "diamond": "ダイヤ", "dia": "ダイヤ", "d": "ダイヤ", "ダイヤ": "ダイヤ",
    "ascendant": "アセンダント", "asc": "アセンダント", "a": "アセンダント", "アセンダント": "アセンダント",
    "immortal": "イモータル", "immo": "イモータル", "imm": "イモータル", "イモータル": "イモータル",
    "radiant": "レディアント", "rad": "レディアント", "r": "レディアント", "レディアント": "レディアント",
    "unranked": "Unranked", "ur": "Unranked", "アンランク": "Unranked"
}

RANK_ICONS = {
    "アイアン": "⚪",
    "ブロンズ": "🟤",
    "シルバー": "🔘",
    "ゴールド": "🟡",
    "プラチナ": "🟢",
    "ダイヤ": "🔵",
    "アセンダント": "🟣",
    "イモータル": "🔴",
    "レディアント": "🟡✨",
    "Unranked": "❓"
}

# 各ランクの基準レート (Tier 1 時の基本値)
# アイアン1=1, ブロンズ1=4, シルバー1=7 ...
BASE_RATING = {
    "アイアン": 1, 
    "ブロンズ": 4, 
    "シルバー": 7,
    "ゴールド": 10, 
    "プラチナ": 13, 
    "ダイヤ": 16,
    "アセンダント": 19, 
    "イモータル": 22, 
    "レディアント": 25,
    "Unranked": 8
}

user_db = {}

def parse_rank_input(rank_input: str):
    """入力された文字列から正確なランク名・1ずつ増える内部レート・アイコンを返します"""
    if not rank_input:
        return "Unranked", 8, "❓"
        
    clean_input = rank_input.lower().replace(" ", "").replace("-", "")
    
    if "radiant" in clean_input or "rad" in clean_input or "レディアント" in clean_input:
        return "レディアント", 25, "🟡✨"

    match = re.match(r"([a-zぁ-んァ-ヶＡ-Ｚａ-ｚー]+)(\d)?", clean_input)
    if not match:
        return "Unranked", 8, "❓"
    
    name_part, tier_part = match.groups()
    tier = int(tier_part) if tier_part and tier_part in ["1", "2", "3"] else 1

    matched_rank = RANK_ALIASES.get(name_part)
    if not matched_rank:
        return "Unranked", 8, "❓"

    icon = RANK_ICONS.get(matched_rank, "❓")

    if matched_rank == "Unranked":
        return "Unranked", 8, icon
    if matched_rank == "レディアント":
        return "レディアント", 25, icon

    # 計算式: 各ランク1の基礎点 + (Tier - 1)
    # 例: アイアン1 -> 1 + 0 = 1, アイアン2 -> 1 + 1 = 2, アイアン3 -> 1 + 2 = 3
    rating = BASE_RATING[matched_rank] + (tier - 1)
    formatted_name = f"{matched_rank}{tier}"
    return formatted_name, rating, icon

def fetch_valorant_rank(riot_id):
    try:
        if "#" not in riot_id:
            return "Unranked", 8, "❓"
        name, tag = riot_id.split("#", 1)
        
        headers = {"User-Agent": "Mozilla/5.0"}
        url = f"https://api.henrikdev.xyz/valorant/v2/mmr/ap/{name}/{tag}"
        
        res = requests.get(url, headers=headers, timeout=8)
        if res.status_code == 200:
            data = res.json()
            current_data = data.get("data", {}).get("current_data", {})
            tier_name = current_data.get("currenttierpatched")
            
            if tier_name:
                return parse_rank_input(tier_name)
    except Exception as e:
        print(f"API Fetch Error: {e}")
        
    return "Unranked", 8, "❓"

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
        
        if interaction.user.id not in user_db:
            user_db[interaction.user.id] = {"riot_id": "未登録", "rank": "Unranked", "rating": 8, "icon": "❓"}

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

        players = self.participants.copy()
        players.sort(key=lambda p: user_db.get(p.id, {}).get("rating", 8), reverse=True)

        team_a, team_b = [], []
        for i, player in enumerate(players):
            if i % 2 == 0:
                team_a.append(player)
            else:
                team_b.append(player)

        def fmt_team(team):
            lines = []
            for p in team:
                info = user_db.get(p.id, {"rank": "Unranked", "icon": "❓"})
                lines.append(f"• {info['icon']} {p.display_name} ({info['rank']})")
            return "\n".join(lines) or "なし"

        embed = discord.Embed(title="⚔️ ランク均等 チーム分け結果", color=discord.Color.gold())
        embed.add_field(name="🔴 チーム A", value=fmt_team(team_a), inline=True)
        embed.add_field(name="🔵 チーム B", value=fmt_team(team_b), inline=True)

        await interaction.response.send_message(embed=embed)

    async def update_embed(self, interaction: discord.Interaction):
        lines = []
        for p in self.participants:
            info = user_db.get(p.id, {"rank": "Unranked", "icon": "❓"})
            lines.append(f"• {info['icon']} {p.display_name} [{info['rank']}]")
        
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

@bot.command()
async def register(ctx, riot_id: str):
    rank_name, rating, icon = fetch_valorant_rank(riot_id)
    
    user_db[ctx.author.id] = {"riot_id": riot_id, "rank": rank_name, "rating": rating, "icon": icon}
    await ctx.send(f"✅ {ctx.author.mention} さんの Riot ID (`{riot_id}`) を登録しました！（取得ランク: {icon} **{rank_name}** / レート: {rating}pt）")

@bot.command()
async def setrank(ctx, *, rank_input: str):
    rank_name, rating, icon = parse_rank_input(rank_input)
    if not rank_name or rank_name == "Unranked":
        await ctx.send("⚠️ ランクを認識できませんでした。\n入力例: `!setrank immo3`, `!setrank イモータル3`, `!setrank g2`")
        return
    
    if ctx.author.id not in user_db:
        user_db[ctx.author.id] = {"riot_id": "未登録", "rank": rank_name, "rating": rating, "icon": icon}
    else:
        user_db[ctx.author.id]["rank"] = rank_name
        user_db[ctx.author.id]["rating"] = rating
        user_db[ctx.author.id]["icon"] = icon

    await ctx.send(f"✏️ {ctx.author.mention} さんのランクを {icon} **{rank_name}** に更新しました！（内部レート: {rating}pt）")

@bot.command()
async def valocus(ctx):
    embed = discord.Embed(title="🎮 VALOcus ボット コマンドヘルプ", color=discord.Color.green())
    embed.add_field(name="`!custom`", value="カスタム募集パネルを表示します。", inline=False)
    embed.add_field(name="`!register 名前#TAG`", value="Riot IDを入力して公式APIから最新ランクを自動取得・登録します。", inline=False)
    embed.add_field(name="`!setrank ランク`", value="手動でランクを設定・更新します。\n（例: `!setrank immo3`, `!setrank イモータル3`, `!setrank d2`）", inline=False)
    embed.add_field(name="`!ping`", value="ボットの動作確認を行います。", inline=False)
    await ctx.send(embed=embed)

@bot.command()
async def ping(ctx):
    await ctx.send("pong!")

# 起動処理
keep_alive()
TOKEN = os.environ.get("DISCORD_TOKEN")
if TOKEN:
    bot.run(TOKEN)