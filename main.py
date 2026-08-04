import os
import re
import sqlite3
import requests
from threading import Thread
from collections import defaultdict
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

def update_user_rating(user_id: int, diff: int):
    data = get_user_data(user_id)
    new_rating = max(1, data["rating"] + diff)
    save_user_data(user_id, data["riot_id"], data["rank"], new_rating, data["icon"])
    return new_rating

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

active_view = None

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
    "アイアン": "⚪", "ブロンズ": "🟤", "シルバー": "🔘", "ゴールド": "🟡",
    "プラチナ": "🟢", "ダイヤ": "🔵", "アセンダント": "🟣", "イモータル": "🔴",
    "レディアント": "🟡✨", "Unranked": "❓"
}

BASE_RATING = {
    "アイアン": 1, "ブロンズ": 4, "シルバー": 7, "ゴールド": 10, 
    "プラチナ": 13, "ダイヤ": 16, "アセンダント": 19, "イモータル": 22, 
    "レディアント": 25, "Unranked": 8
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
    headers = {"User-Agent": "Mozilla/5.0", "Authorization": api_key}
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

def generate_team_embed_and_view(participants):
    """最新の内部レートを元にチーム分けとボタンViewを作成するヘルパー関数"""
    players = participants.copy()
    # 最新の内部レート順にソート
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
            lines.append(f"• {info['icon']} {p.display_name} ({info['rank']} / {info['rating']}pt)")
        return "\n".join(lines) or "なし"

    embed = discord.Embed(title="⚔️ ランク均等 チーム分け結果", color=discord.Color.gold())
    embed.add_field(name="🔴 チーム A", value=fmt_team(team_a), inline=True)
    embed.add_field(name="🔵 チーム B", value=fmt_team(team_b), inline=True)

    result_view = MatchResultView(team_a, team_b, participants)
    return embed, result_view

# --- 勝敗入力用 View ---
class MatchResultView(discord.ui.View):
    def __init__(self, team_a, team_b, all_participants):
        super().__init__(timeout=None)
        self.team_a = team_a
        self.team_b = team_b
        self.all_participants = all_participants
        self.processed = False

    async def handle_match_end(self, interaction: discord.Interaction, winner_team, loser_team, winner_title):
        if self.processed:
            await interaction.response.send_message("この試合の勝敗はすでに記録されています。", ephemeral=True)
            return
        self.processed = True

        # レート更新 (+1 / -1)
        for p in winner_team:
            update_user_rating(p.id, 1)
        for p in loser_team:
            update_user_rating(p.id, -1)

        # 現在のメッセージのボタンを無効化
        for child in self.children:
            child.disabled = True

        embed = interaction.message.embeds[0]
        embed.title = winner_title
        embed.set_footer(text="※勝者+1pt / 敗者-1pt を反映しました。")
        await interaction.response.edit_message(embed=embed, view=self)

        # 最新のレートを元に「次の試合のチーム分け」を自動作成して送信
        next_embed, next_view = generate_team_embed_and_view(self.all_participants)
        next_embed.title = "🔄 レート更新！【次戦のチーム分け結果】"
        await interaction.followup.send(embed=next_embed, view=next_view)

    @discord.ui.button(label="🔴 チームA 勝利", style=discord.ButtonStyle.danger, custom_id="win_a_btn")
    async def win_a(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_match_end(interaction, self.team_a, self.team_b, "🏆 試合結果: 🔴 チームA 勝利！")

    @discord.ui.button(label="🔵 チームB 勝利", style=discord.ButtonStyle.primary, custom_id="win_b_btn")
    async def win_b(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_match_end(interaction, self.team_b, self.team_a, "🏆 試合結果: 🔵 チームB 勝利！")

# --- カスタム募集用 View ---
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

        embed, result_view = generate_team_embed_and_view(self.participants)
        await interaction.response.send_message(embed=embed, view=result_view)

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
    global active_view
    active_view = CustomView()
    embed = discord.Embed(
        title="🎮 VALORANT カスタム募集",
        description="**【参加者一覧】 (0人)**\nなし",
        color=discord.Color.blue()
    )
    await ctx.send(embed=embed, view=active_view)

@bot.command()
async def members(ctx):
    global active_view
    if not active_view or not active_view.participants:
        await ctx.send("❓ 現在参加しているメンバーはいません。")
        return

    participants = active_view.participants
    rank_groups = defaultdict(list)
    for p in participants:
        info = get_user_data(p.id)
        rank_groups[(info['icon'], info['rank'])].append(p.display_name)

    embed = discord.Embed(
        title=f"📊 現在の参加状況（合計 {len(participants)}名）",
        color=discord.Color.teal()
    )

    for (icon, rank_name), names in rank_groups.items():
        embed.add_field(
            name=f"{icon} {rank_name} ({len(names)}人)",
            value=f"└ {', '.join(names)}",
            inline=False
        )

    await ctx.send(embed=embed)

@bot.command()
async def register(ctx, riot_id: str):
    rank_name, rating, icon = fetch_valorant_rank(riot_id)
    if not rank_name:
        await ctx.send(
            f"⚠️ **{riot_id}** のランクを自動取得できませんでした。\n"
            f"`!setrank ランク名` で手動登録をお願いします！"
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
        await ctx.send("⚠️ ランクを認識できませんでした。\n入力例: `!setrank immo3`, `!setrank ダイヤ2`")
        return
    
    old_data = get_user_data(ctx.author.id)
    riot_id = old_data["riot_id"]
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
        await ctx.send(f"❓ {ctx.author.mention} さんのランク情報はまだ登録されていません。")
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
    embed.add_field(name="`!members`", value="参加者のランク別分布を表示します。", inline=False)
    embed.add_field(name="`!register 名前#TAG`", value="Riot IDを入力して自動取得します。", inline=False)
    embed.add_field(name="`!setrank ランク`", value="手動でランクを設定します。", inline=False)
    embed.add_field(name="`!myrank`", value="自分の登録情報を確認します。", inline=False)
    await ctx.send(embed=embed)

@bot.command()
async def ping(ctx):
    await ctx.send("pong!")

keep_alive()
TOKEN = os.environ.get("DISCORD_TOKEN")
if TOKEN:
    bot.run(TOKEN)