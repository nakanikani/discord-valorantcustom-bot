import os
import re
import sqlite3
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

# --- データベース (SQLite) 初期化 ---
DB_FILE = "users_data.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            riot_id TEXT,
            rank_name TEXT,
            rating INTEGER,
            icon TEXT
        )
    ''')
    conn.commit()
    conn.close()

def save_user_data(user_id: int, riot_id: str, rank_name: str, rating: int, icon: str):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    # 既存のRiot IDがあり、今回渡されたriot_idが"未登録"の場合は既存のIDを維持する
    if riot_id == "未登録":
        c.execute('SELECT riot_id FROM users WHERE user_id = ?', (user_id,))
        row = c.fetchone()
        if row and row[0] != "未登録":
            riot_id = row[0]

    c.execute('''
        INSERT INTO users (user_id, riot_id, rank_name, rating, icon)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            riot_id=excluded.riot_id,
            rank_name=excluded.rank_name,
            rating=excluded.rating,
            icon=excluded.icon
    ''', (user_id, riot_id, rank_name, rating, icon))
    conn.commit()
    conn.close()

def get_user_data(user_id: int):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('SELECT riot_id, rank_name, rating, icon FROM users WHERE user_id = ?', (user_id,))
    row = c.fetchone()
    conn.close()
    if row:
        return {"riot_id": row[0], "rank": row[1], "rating": row[2], "icon": row[3]}
    return {"riot_id": "未登録", "rank": "Unranked", "rating": 8, "icon": "❓"}

init_db()

# --- Discord Bot 設定 ---
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

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

def parse_rank_input(rank_input: str):
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

    rating = BASE_RATING[matched_rank] + (tier - 1)
    formatted_name = f"{matched_rank}{tier}"
    return formatted_name, rating, icon

def fetch_valorant_rank(riot_id):
    if "#" not in riot_id:
        return None, None, None
        
    name, tag = riot_id.split("#", 1)
    api_key = os.environ.get("HENRIK_API_KEY", "").strip()

    headers = {
        "User-Agent": "Mozilla/5.0",
        "Authorization": api_key
    }

    url = f"https://api.henrikdev.xyz/valorant/v2/mmr/ap/{name}/{tag}"

    try:
        res = requests.get(url, headers=headers, timeout=8)
        if res.status_code == 200:
            data = res.json()
            tier_name = data.get("data", {}).get("current_data", {}).get("currenttierpatched")
            
            if tier_name and tier_name != "Unranked":
                return parse_rank_input(tier_name)
    except Exception as e:
        print(f"Fetch Error: {e}")

    return None, None, None

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
        players.sort(key=lambda p: get_user_data(p.id)["rating"], reverse=True)

        team_a, team_b = [], []
        for i, player in enumerate(players):
            if i % 2 == 0:
                team_a.append(player)
            else:
                team_b.append(player)

        def fmt_team(team):
            lines = []
            for p in team:
                info = get_user_data(p.id)
                lines.append(f"• {info['icon']} {p.display_name} ({info['rank']})")
            return "\n".join(lines) or "なし"

        embed = discord.Embed(title="⚔️ ランク均等 チーム分け結果", color=discord.Color.gold())
        embed.add_field(name="🔴 チーム A", value=fmt_team(team_a), inline=True)
        embed.add_field(name="🔵 チーム B", value=fmt_team(team_b), inline=True)

        await interaction.response.send_message(embed=embed)

    async def update_embed(self, interaction: discord.Interaction):
        lines = []
        for p in self.participants:
            info = get_user_data(p.id)
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
    
    if not rank_name:
        await ctx.send(
            f"⚠️ **{riot_id}** のランクを自動取得できませんでした（非公開設定、アンランク、またはID入力ミスの可能性があります）。\n"
            f"お手数ですが、`!setrank ランク名` で手動登録をお願いします！（例: `!setrank immo1`, `!setrank ダイヤ2`）"
        )
        return

    old_data = get_user_data(ctx.author.id)
    save_user_data(ctx.author.id, riot_id, rank_name, rating, icon)

    if old_data["rank"] != "Unranked":
        await ctx.send(
            f"🔄 {ctx.author.mention} さんの登録情報を更新しました！\n"
            f"• Riot ID: `{riot_id}`\n"
            f"• ランク: {old_data['icon']} **{old_data['rank']}** ➔ {icon} **{rank_name}** ({rating}pt)"
        )
    else:
        await ctx.send(f"✅ {ctx.author.mention} さんの Riot ID (`{riot_id}`) を登録しました！（取得ランク: {icon} **{rank_name}** / {rating}pt）")

@bot.command()
async def setrank(ctx, *, rank_input: str):
    rank_name, rating, icon = parse_rank_input(rank_input)
    if not rank_name or rank_name == "Unranked":
        await ctx.send("⚠️ ランクを認識できませんでした。\n入力例: `!setrank immo3`, `!setrank イモータル3`, `!setrank g2`")
        return
    
    old_data = get_user_data(ctx.author.id)
    riot_id = old_data["riot_id"]

    # 保存処理（riot_idを保持する）
    save_user_data(ctx.author.id, riot_id, rank_name, rating, icon)

    if old_data["rank"] != "Unranked":
        await ctx.send(
            f"✏️ {ctx.author.mention} さんのランクを更新しました！\n"
            f"• ランク: {old_data['icon']} **{old_data['rank']}** ➔ {icon} **{rank_name}** ({rating}pt)"
        )
    else:
        await ctx.send(f"✏️ {ctx.author.mention} さんのランクを {icon} **{rank_name}** に設定しました！（内部レート: {rating}pt）")

@bot.command()
async def myrank(ctx):
    data = get_user_data(ctx.author.id)
    if data["rank"] == "Unranked" and data["riot_id"] == "未登録":
        await ctx.send(f"❓ {ctx.author.mention} さんのランク情報はまだ登録されていません。\n`!register 名前#TAG` または `!setrank ランク名` で登録できます。")
    else:
        await ctx.send(
            f"👤 {ctx.author.mention} さんの登録情報:\n"
            f"• Riot ID: `{data['riot_id']}`\n"
            f"• 現在のランク: {data['icon']} **{data['rank']}** (内部レート: {data['rating']}pt)"
        )

@bot.command()
async def valocus(ctx):
    embed = discord.Embed(title="🎮 VALOcus ボット コマンドヘルプ", color=discord.Color.green())
    embed.add_field(name="`!custom`", value="カスタム募集パネルを表示します。", inline=False)
    embed.add_field(name="`!register 名前#TAG`", value="Riot IDを入力して最新ランクを自動取得・登録します。", inline=False)
    embed.add_field(name="`!setrank ランク`", value="手動でランクを設定・更新します。\n（例: `!setrank immo3`, `!setrank イモータル3`, `!setrank d2`）", inline=False)
    embed.add_field(name="`!myrank`", value="現在登録されている自分のRiot IDとランク情報を確認します。", inline=False)
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