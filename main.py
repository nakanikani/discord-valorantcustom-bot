import os
import re
import requests
from threading import Thread
from collections import defaultdict
from flask import Flask
import discord
from discord.ext import commands
from discord import app_commands
import supabase

# --- Render対策: Keep Alive 用 Webサーバー ---
app = Flask('')

@app.route('/')
def home():
    return "Bot is running!"

def keep_alive():
    t = Thread(target=lambda: app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080))))
    t.start()

# --- Supabase 接続設定 ---
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").strip()
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "").strip()

if not SUPABASE_URL or not SUPABASE_KEY:
    print("⚠️ SUPABASE_URL または SUPABASE_KEY が環境変数に設定されていません！")

supabase_db = supabase.create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL and SUPABASE_KEY else None

# --- ランク定義とデフォルト絵文字 ---
RANK_ICONS = {
    "アイアン": "🟤", "ブロンズ": "🟤", "シルバー": "⚪",
    "ゴールド": "🟡", "プラチナ": "🔵", "ダイヤ": "🟣",
    "アセンダント": "🟢", "イモータル": "🔴", "レディアント": "🌟",
    "Unranked": "❓"
}

RANK_ALIASES = {
    "iron": "アイアン", "i": "アイアン", "アイアン": "アイアン",
    "bronze": "ブロンズ", "b": "ブロンズ", "ブロンズ": "ブロンズ", "ブロ": "ブロンズ",
    "silver": "シルバー", "s": "シルバー", "シルバー": "シルバー", "シル": "シルバー",
    "gold": "ゴールド", "g": "ゴールド", "ゴールド": "ゴールド", "ゴル": "ゴールド",
    "platinum": "プラチナ", "plat": "プラチナ", "p": "プラチナ", "プラチナ": "プラチナ", "プラ": "プラチナ",
    "diamond": "ダイヤ", "dia": "ダイヤ", "d": "ダイヤ", "ダイヤ": "ダイヤ",
    "ascendant": "アセンダント", "asc": "アセンダント", "ase": "アセンダント", "a": "アセンダント", "アセンダント": "アセンダント", "アセ": "アセンダント", "汗": "アセンダント",
    "immortal": "イモータル", "immo": "イモータル", "imm": "イモータル", "imo": "イモータル", "イモータル": "イモータル", "イモ": "イモータル", "芋": "イモータル",
    "radiant": "レディアント", "rad": "レディアント", "r": "レディアント", "レディアント": "レディアント", "レディ": "レディアント",
    "unranked": "Unranked", "ur": "Unranked", "アンランク": "Unranked"
}

BASE_RATING = {
    "アイアン": 1, "ブロンズ": 4, "シルバー": 7, "ゴールド": 10, 
    "プラチナ": 13, "ダイヤ": 16, "アセンダント": 19, "イモータル": 22,
    "レディアント": 35, "Unranked": 8
}

# --- データベース操作関数 ---

def save_user_data(user_id: int, riot_id: str, rank_name: str, rating: int, icon: str):
    if not supabase_db:
        print("⚠️ Supabase 接続が存在しないため保存をスキップしました。")
        return

    data = {
        "user_id": int(user_id),
        "riot_id": str(riot_id) if riot_id else "未登録",
        "rank_name": str(rank_name),
        "rating": int(rating),
        "icon": str(icon)
    }
    
    try:
        supabase_db.table("users").upsert(data).execute()
        print(f"✅ 保存成功: {user_id} -> {rank_name} ({rating}pt)")
    except Exception as e:
        print(f"❌ Supabase Save Error: {e}")

def update_user_rating(user_id: int, diff: int):
    data = get_user_data(user_id, auto_refresh=False)
    new_rating = max(1, data["rating"] + diff)
    save_user_data(user_id, data["riot_id"], data["rank"], new_rating, data["icon"])
    return new_rating

def get_user_data(user_id: int, auto_refresh: bool = False):
    default_icon = RANK_ICONS.get("Unranked", "❓")
    default_data = {"riot_id": "未登録", "rank": "Unranked", "rating": 8, "icon": default_icon}
    if not supabase_db:
        return default_data

    try:
        res = supabase_db.table("users").select("*").eq("user_id", int(user_id)).execute()
        rows = res.data
    except Exception as e:
        print(f"❌ Supabase Fetch Error: {e}")
        return default_data

    if not rows:
        return default_data

    row = rows[0]
    riot_id = row.get("riot_id") or "未登録"
    rank_name = row.get("rank_name") or "Unranked"
    rating = row.get("rating", 8)
    
    base_rank_key = re.sub(r'\d+', '', rank_name)
    icon = RANK_ICONS.get(base_rank_key, RANK_ICONS.get(rank_name, default_icon))

    if auto_refresh and riot_id != "未登録":
        new_rank, new_rating, new_icon = fetch_valorant_rank(riot_id)
        if new_rank and new_rank != rank_name:
            save_user_data(user_id, riot_id, new_rank, new_rating, new_icon)
            return {"riot_id": riot_id, "rank": new_rank, "rating": new_rating, "icon": new_icon}

    return {"riot_id": riot_id, "rank": rank_name, "rating": rating, "icon": icon}

# --- 解析・取得関数 ---

def parse_rank_input(rank_input: str):
    if not rank_input:
        return "Unranked", 8, RANK_ICONS.get("Unranked", "❓")
    clean_input = rank_input.lower().replace(" ", "").replace("-", "")
    
    if "radiant" in clean_input or "rad" in clean_input or "レディアント" in clean_input or "レディ" in clean_input:
        return "レディアント", 35, RANK_ICONS.get("レディアント", "🌟")

    match = re.match(r"([a-zぁ-んァ-ヶＡ-Ｚａ-ｚー一-龠]+)(\d)?", clean_input)
    if not match:
        return "Unranked", 8, RANK_ICONS.get("Unranked", "❓")
    
    name_part, tier_part = match.groups()
    tier = int(tier_part) if tier_part and tier_part in ["1", "2", "3"] else 1
    matched_rank = RANK_ALIASES.get(name_part)
    if not matched_rank:
        return "Unranked", 8, RANK_ICONS.get("Unranked", "❓")

    icon = RANK_ICONS.get(matched_rank, "❓")
    if matched_rank == "Unranked":
        return "Unranked", 8, icon
    if matched_rank == "レディアント":
        return "レディアント", 35, icon

    if matched_rank == "イモータル" and tier == 3:
        rating = 30
    else:
        rating = BASE_RATING[matched_rank] + (tier - 1)

    return f"{matched_rank}{tier}", rating, icon

def fetch_valorant_rank(riot_id):
    if not riot_id or "#" not in riot_id:
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

# --- Bot 本体定義 ---

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

active_view = None

def generate_team_embed_and_view(participants):
    players = participants.copy()
    players.sort(key=lambda p: get_user_data(p.id, auto_refresh=False)["rating"], reverse=True)

    team_a, team_b = [], []
    for i, player in enumerate(players):
        if i % 2 == 0:
            team_a.append(player)
        else:
            team_b.append(player)

    def fmt_team(team):
        lines = []
        for p in team:
            info = get_user_data(p.id, auto_refresh=False)
            lines.append(f"• {info['icon']} {p.display_name} ({info['rank']} / {info['rating']}pt)")
        return "\n".join(lines) or "なし"

    embed = discord.Embed(title="⚔️ ランク均等 チーム分け結果", color=discord.Color.gold())
    embed.add_field(name="🔴 チーム A", value=fmt_team(team_a), inline=True)
    embed.add_field(name="🔵 チーム B", value=fmt_team(team_b), inline=True)

    return embed, MatchResultView(team_a, team_b, participants)

# --- Boom Bot風パネルの更新処理 ---
async def update_active_custom_view():
    global active_view
    if active_view and active_view.message:
        if active_view.participants:
            lines = []
            for i, p in enumerate(active_view.participants):
                info = get_user_data(p.id, auto_refresh=False)
                lines.append(f"{i} - {info['icon']} {p.mention}")
            member_list = "\n".join(lines)
        else:
            member_list = "参加者がいません"

        description_text = (
            f"**IgnoreID**\n"
            f"{member_list}\n\n"
            f"✓ IgnoreIDを使用すると、指定のメンバーを除外した状態でチーム分けができます。"
        )

        embed = discord.Embed(
            title="🎮 VALORANT カスタム募集",
            description=description_text,
            color=0x2b2d31
        )
        embed.set_footer(text=f"現在の参加人数: {len(active_view.participants)}人")

        try:
            await active_view.message.edit(embed=embed, view=active_view)
        except discord.NotFound:
            active_view = None

# --- UI View クラス ---

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

        for p in winner_team:
            update_user_rating(p.id, 1)
        for p in loser_team:
            update_user_rating(p.id, -1)

        for child in self.children:
            child.disabled = True

        embed = interaction.message.embeds[0]
        embed.title = winner_title
        embed.set_footer(text="※勝者+1pt / 敗者-1pt を反映しました。")
        await interaction.response.edit_message(embed=embed, view=self)

        next_embed, next_view = generate_team_embed_and_view(self.all_participants)
        next_embed.title = "🔄 レート更新！【次戦のチーム分け結果】"
        await interaction.followup.send(embed=next_embed, view=next_view)

    @discord.ui.button(label="🔴 チームA 勝利", style=discord.ButtonStyle.danger)
    async def win_a(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_match_end(interaction, self.team_a, self.team_b, "🏆 試合結果: 🔴 チームA 勝利！")

    @discord.ui.button(label="🔵 チームB 勝利", style=discord.ButtonStyle.primary)
    async def win_b(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_match_end(interaction, self.team_b, self.team_a, "🏆 試合結果: 🔵 チームB 勝利！")

# --- ティアを選択する用のボタンパネル（2段階目） ---
class TierButtonView(discord.ui.View):
    def __init__(self, rank_name, rank_style, rank_emoji):
        super().__init__(timeout=None)
        self.rank_name = rank_name
        self.rank_style = rank_style
        self.rank_emoji = rank_emoji

        for tier in [1, 2, 3]:
            btn = discord.ui.Button(label=f"{rank_name} {tier}", style=rank_style, emoji=rank_emoji)
            btn.callback = self.make_callback(tier)
            self.add_item(btn)
        
        back_btn = discord.ui.Button(label="戻る", style=discord.ButtonStyle.secondary, row=1)
        back_btn.callback = self.go_back
        self.add_item(back_btn)

    def make_callback(self, tier):
        async def callback(interaction: discord.Interaction):
            target_rank = f"{self.rank_name}{tier}"
            name, rating, icon = parse_rank_input(target_rank)
            
            old_data = get_user_data(interaction.user.id, auto_refresh=False)
            save_user_data(interaction.user.id, old_data["riot_id"], name, rating, icon)
            
            await interaction.response.edit_message(
                content=f"✅ ランクを {icon} **{name}** に設定しました！",
                embed=None,
                view=None
            )
            
            global active_view
            if active_view and interaction.user in active_view.participants:
                await update_active_custom_view()

        return callback

    async def go_back(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="🔰 ランク手動設定",
            description="ご自身の現在のランクボタンをクリックしてください！",
            color=discord.Color.light_grey()
        )
        await interaction.response.edit_message(embed=embed, view=RankButtonView())

# --- ランクを選択する用のボタンパネル（1段階目） ---
class RankButtonView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        
        ranks = [
            ("アイアン", discord.ButtonStyle.primary, 0),
            ("ブロンズ", discord.ButtonStyle.primary, 0),
            ("シルバー", discord.ButtonStyle.primary, 0),
            ("ゴールド", discord.ButtonStyle.primary, 0),
            ("プラチナ", discord.ButtonStyle.primary, 0),
            ("ダイヤ", discord.ButtonStyle.primary, 1),
            ("アセンダント", discord.ButtonStyle.primary, 1),
            ("イモータル", discord.ButtonStyle.primary, 1),
            ("レディアント", discord.ButtonStyle.primary, 1),
            ("Unranked", discord.ButtonStyle.secondary, 2)
        ]
        
        for name, style, row in ranks:
            emoji = RANK_ICONS.get(name, "❓")
            btn = discord.ui.Button(label=name, emoji=emoji, style=style, row=row)
            btn.callback = self.make_callback(name, style, emoji)
            self.add_item(btn)

    def make_callback(self, rank_name, style, emoji):
        async def callback(interaction: discord.Interaction):
            if rank_name in ["レディアント", "Unranked"]:
                name, rating, icon = parse_rank_input(rank_name)
                old_data = get_user_data(interaction.user.id, auto_refresh=False)
                save_user_data(interaction.user.id, old_data["riot_id"], name, rating, icon)
                
                await interaction.response.edit_message(
                    content=f"✅ ランクを {icon} **{name}** に設定しました！",
                    embed=None,
                    view=None
                )
                
                global active_view
                if active_view and interaction.user in active_view.participants:
                    await update_active_custom_view()
            else:
                embed = discord.Embed(
                    title=f"{emoji} {rank_name} のティアを選択",
                    description="該当するティア（1〜3）を選択してください。",
                    color=discord.Color.light_grey()
                )
                await interaction.response.edit_message(embed=embed, view=TierButtonView(rank_name, style, emoji))

        return callback

# --- IgnoreID入力用のポップアップ画面 ---
class IgnoreModal(discord.ui.Modal, title='メンバーの除外'):
    ignore_ids = discord.ui.TextInput(
        label='除外するIgnoreID（カンマ区切りで複数可）',
        style=discord.TextStyle.short,
        placeholder='例: 0, 2',
        required=True
    )

    def __init__(self, custom_view):
        super().__init__()
        self.custom_view = custom_view

    async def on_submit(self, interaction: discord.Interaction):
        # 入力された文字からスペースを消す
        ids_str = self.ignore_ids.value.replace(" ", "")
        
        try:
            # カンマ区切りで数字のリストにする
            ids_to_remove = [int(x) for x in ids_str.split(",")]
        except ValueError:
            await interaction.response.send_message("⚠️ 数字とカンマだけで入力してください。（例: 0, 2）", ephemeral=True)
            return

        # リストの後ろの番号から消さないとインデックスがずれるため、降順にソート
        ids_to_remove.sort(reverse=True)
        removed_names = []
        
        for i in ids_to_remove:
            if 0 <= i < len(self.custom_view.participants):
                p = self.custom_view.participants.pop(i)
                removed_names.append(p.display_name)
        
        # パネルの表示を更新
        global active_view
        await update_active_custom_view()
        
        if removed_names:
            await interaction.response.send_message(f"🗑️ 以下のメンバーを除外しました: {', '.join(removed_names)}", ephemeral=True)
        else:
            await interaction.response.send_message("⚠️ 指定されたIDのメンバーが見つかりませんでした。", ephemeral=True)


class CustomView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.participants = []
        self.message = None

    @discord.ui.button(label="参加する", style=discord.ButtonStyle.green)
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        if interaction.user in self.participants:
            await interaction.followup.send("すでに参加しています！", ephemeral=True)
            return
        self.participants.append(interaction.user)
        self.message = interaction.message
        await update_active_custom_view()
        await interaction.followup.send(f"{interaction.user.mention} が参加しました！", ephemeral=True)

    @discord.ui.button(label="辞退する", style=discord.ButtonStyle.red)
    async def leave(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        if interaction.user not in self.participants:
            await interaction.followup.send("参加していません。", ephemeral=True)
            return
        self.participants.remove(interaction.user)
        self.message = interaction.message
        await update_active_custom_view()
        await interaction.followup.send(f"{interaction.user.mention} が辞退しました。", ephemeral=True)

    @discord.ui.button(label="均等チーム分け実行", style=discord.ButtonStyle.blurple)
    async def split_teams(self, interaction: discord.Interaction, button: discord.ui.Button):
        if len(self.participants) < 2:
            await interaction.response.send_message("チーム分けには最低2人必要です！", ephemeral=True)
            return
        await interaction.response.defer()
        embed, result_view = generate_team_embed_and_view(self.participants)
        await interaction.followup.send(embed=embed, view=result_view)

    @discord.ui.button(label="ランク設定", style=discord.ButtonStyle.secondary, emoji="⚙️")
    async def set_rank_from_panel(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(
            title="🔰 ランク手動設定",
            description="ご自身の現在のランクボタンをクリックしてください！",
            color=discord.Color.light_grey()
        )
        await interaction.response.send_message(embed=embed, view=RankButtonView(), ephemeral=True)

    @discord.ui.button(label="IDで除外", style=discord.ButtonStyle.gray, emoji="🗑️")
    async def remove_by_id(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.participants:
            await interaction.response.send_message("現在参加者がいないため、除外できません。", ephemeral=True)
            return
        await interaction.response.send_modal(IgnoreModal(self))

# --- スラッシュコマンド群 ---

@bot.event
async def on_ready():
    # await bot.tree.sync() 
    print(f"Logged in as {bot.user.name}")
    print("✅ 起動しました（コマンドの同期はスキップしました）")

@bot.tree.command(name="custom", description="カスタム募集パネルを表示します")
async def custom(interaction: discord.Interaction):
    global active_view
    active_view = CustomView()
    
    description_text = (
        f"**IgnoreID**\n"
        f"参加者がいません\n\n"
        f"✓ IgnoreIDを使用すると、指定のメンバーを除外した状態でチーム分けができます。"
    )
    
    embed = discord.Embed(
        title="🎮 VALORANT カスタム募集",
        description=description_text,
        color=0x2b2d31
    )
    embed.set_footer(text="現在の参加人数: 0人")

    await interaction.response.send_message(embed=embed, view=active_view)
    active_view.message = await interaction.original_response()

@bot.tree.command(name="members", description="現在の参加メンバーのランク別分布を表示します")
async def members(interaction: discord.Interaction):
    global active_view
    if not active_view or not active_view.participants:
        await interaction.response.send_message("❓ 現在参加しているメンバーはいません。", ephemeral=True)
        return

    rank_groups = defaultdict(list)
    for p in active_view.participants:
        info = get_user_data(p.id, auto_refresh=False)
        rank_groups[(info['icon'], info['rank'])].append(p.display_name)

    embed = discord.Embed(
        title=f"📊 現在の参加状況（合計 {len(active_view.participants)}名）",
        color=discord.Color.teal()
    )

    for (icon, rank_name), names in rank_groups.items():
        embed.add_field(
            name=f"{icon} {rank_name} ({len(names)}人)",
            value=f"└ {', '.join(names)}",
            inline=False
        )
    
    await interaction.response.send_message(embed=embed, view=active_view)
    active_view.message = await interaction.original_response()

@bot.tree.command(name="register", description="Riot IDから自動でランクを取得して登録します")
@app_commands.describe(riot_id="登録するRiot ID (例: 名前#TAG)")
async def register(interaction: discord.Interaction, riot_id: str):
    await interaction.response.defer()
    rank_name, rating, icon = fetch_valorant_rank(riot_id)
    
    if not rank_name:
        embed = discord.Embed(
            title="⚠️ ランク情報を自動取得できませんでした",
            description=f"**Riot ID:** `{riot_id}`\n\n非公開設定になっているか、今幕未プレイの可能性があります。",
            color=discord.Color.gold()
        )
        embed.add_field(
            name="💡 手動で登録する場合",
            value=f"パネルの「⚙️ ランク設定」ボタンか、\n`/setrank ランク名` で直接登録できます！",
            inline=False
        )
        await interaction.followup.send(embed=embed)
        return

    old_data = get_user_data(interaction.user.id, auto_refresh=False)
    save_user_data(interaction.user.id, riot_id, rank_name, rating, icon)

    if old_data["rank"] != "Unranked":
        await interaction.followup.send(
            f"🔄 {interaction.user.mention} さんの登録情報を更新しました！\n"
            f"• ランク: {old_data['icon']} **{old_data['rank']}** ➔ {icon} **{rank_name}** ({rating}pt)"
        )
    else:
        await interaction.followup.send(f"✅ {interaction.user.mention} さんの Riot ID (`{riot_id}`) を登録しました！（取得ランク: {icon} **{rank_name}** / {rating}pt）")

@bot.tree.command(name="setrank", description="ランクを手動で直接設定します")
@app_commands.describe(rank_input="ランクの入力 (例: immo1, ダイヤ2, プラチナ)")
async def setrank(interaction: discord.Interaction, rank_input: str):
    rank_name, rating, icon = parse_rank_input(rank_input)
    if not rank_name or rank_name == "Unranked":
        await interaction.response.send_message("⚠️ ランクを認識できませんでした。\n入力例: `/setrank immo3`, `/setrank 汗1`, `/setrank 芋2`", ephemeral=True)
        return
    
    old_data = get_user_data(interaction.user.id, auto_refresh=False)
    save_user_data(interaction.user.id, old_data["riot_id"], rank_name, rating, icon)

    global active_view
    if active_view and interaction.user in active_view.participants:
        await update_active_custom_view()

    if old_data["rank"] != "Unranked":
        await interaction.response.send_message(
            f"✏️ {interaction.user.mention} さんのランクを更新しました！\n"
            f"• ランク: {old_data['icon']} **{old_data['rank']}** ➔ {icon} **{rank_name}** ({rating}pt)"
        )
    else:
        await interaction.response.send_message(f"✏️ {interaction.user.mention} さんのランクを {icon} **{rank_name}** に設定しました！（内部レート: {rating}pt）")

@bot.tree.command(name="rankpanel", description="ボタンで簡単にランクを設定できるパネルを個別で表示します")
async def rankpanel(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🔰 ランク手動設定パネル",
        description="ご自身のランクのボタンをクリックしてください！",
        color=discord.Color.brand_green()
    )
    await interaction.response.send_message(embed=embed, view=RankButtonView(), ephemeral=True)

@bot.tree.command(name="myrank", description="現在の自分の登録情報を確認します")
async def myrank(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    data = get_user_data(interaction.user.id, auto_refresh=True)
    if data["rank"] == "Unranked" and data["riot_id"] == "未登録":
        await interaction.followup.send(f"❓ {interaction.user.mention} さんのランク情報はまだ登録されていません。", ephemeral=True)
    else:
        await interaction.followup.send(
            f"👤 {interaction.user.mention} さんの登録情報:\n"
            f"• Riot ID: `{data['riot_id']}`\n"
            f"• 現在のランク: {data['icon']} **{data['rank']}** (内部レート: {data['rating']}pt)",
            ephemeral=True
        )

@bot.tree.command(name="valocus", description="コマンド一覧とヘルプを表示します")
async def valocus(interaction: discord.Interaction):
    embed = discord.Embed(title="🎮 VALOcus ボット コマンドヘルプ", color=discord.Color.green())
    embed.add_field(name="`/custom`", value="カスタム募集パネルを表示します。（パネルから直接ランク設定も可能）", inline=False)
    embed.add_field(name="`/members`", value="参加者のランク別分布を表示します。", inline=False)
    embed.add_field(name="`/register [Riot ID]`", value="Riot IDを入力して自動取得します。", inline=False)
    embed.add_field(name="`/setrank [ランク]`", value="テキストで手動でランクを設定します。", inline=False)
    embed.add_field(name="`/myrank`", value="自分の登録情報を確認します。", inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="ping", description="Botの応答を確認します")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message("pong!", ephemeral=True)

keep_alive()
TOKEN = os.environ.get("DISCORD_TOKEN")
if TOKEN:
    bot.run(TOKEN)