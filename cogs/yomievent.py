import os
import re
import uuid
import logging
import aiohttp
import asyncio
import json  # JSONを扱うためのモジュールを追加
from pymongo import MongoClient
from dotenv import load_dotenv
import discord
from discord.ext import commands
from discord import Embed, Interaction
from discord.ui import Button, View
from collections import deque
from datetime import datetime
import math

logging.basicConfig(level=logging.INFO)

# 環境変数をロード
load_dotenv()

# 環境変数からMongoDBとVoiceVoxのURLを取得
MONGODB_URL = os.getenv('MONGODB_URL')
VOICEVOX_URL = os.getenv('VOICEVOX_URL')

# JSON設定ファイルを読み込む
with open('config.json', 'r', encoding='utf-8') as config_file:
    config = json.load(config_file)

# 設定を取得
DEFAULT_SPEAKER_ID = config['default_speaker_id']
SPEAKER_STYLE_OPTIONS = config['speaker_style_options']

mongo_client = MongoClient(MONGODB_URL)
db = mongo_client['discord_bot_db']
user_settings_collection = db['user_settings']
guild_dicts_collection = db['guild_dicts']
nicknames_collection = db['nicknames']

def load_user_settings():
    settings = user_settings_collection.find_one({})
    return settings if settings else {}

def save_user_settings(settings):
    user_settings_collection.update_one({}, {"$set": settings}, upsert=True)

def load_guild_dict(guild_id: int):
    guild_dict = guild_dicts_collection.find_one({'guild_id': guild_id})
    return guild_dict if guild_dict else {}

def save_guild_dict(guild_id: int, custom_dict):
    custom_dict['guild_id'] = guild_id
    guild_dicts_collection.update_one({'guild_id': guild_id}, {"$set": custom_dict}, upsert=True)


def load_nicknames():
    nicknames = nicknames_collection.find_one({})
    return nicknames if nicknames else {}

def save_nicknames(nicknames):
    nicknames_collection.update_one({}, {"$set": nicknames}, upsert=True)

class event1(commands.Cog):

    def __init__(self, bot):
        self.bot = bot
        self.audio_queue = {}  # サーバーごとにキューを持つ
        self.is_playing = {}
        self.user_settings = load_user_settings()
        self.guild_dicts = {}
        self.text_channel_id = None
        self.voicevox_url = VOICEVOX_URL  # 環境変数から取得
        self.nicknames = load_nicknames()
        self.guild_text_channels = {} 


    async def create_and_save_audio(self, text, filename):
        speaker_id = DEFAULT_SPEAKER_ID  # システムメッセージ用のデフォルト話者
        async with aiohttp.ClientSession() as session:
            query_url = f"{self.voicevox_url}/audio_query"
            params = {'text': text, 'speaker': speaker_id}
            async with session.post(query_url, params=params) as query_resp:
                query_resp.raise_for_status()
                audio_query = await query_resp.json()

            synthesis_url = f"{self.voicevox_url}/synthesis"
            async with session.post(synthesis_url, params={'speaker': speaker_id}, json=audio_query) as synthesis_resp:
                synthesis_resp.raise_for_status()
                audio_content = await synthesis_resp.read()

        with open(filename, 'wb') as audio_file:
            audio_file.write(audio_content)

    async def play_saved_audio(self, filename, guild):
        voice_client = discord.utils.get(self.bot.voice_clients, guild=guild)
        if voice_client:
            voice_client.play(discord.FFmpegPCMAudio(filename))
            self.is_playing = True


    def get_guild_text_channel(self, guild_id):
        return self.bot.get_channel(self.guild_text_channels.get(guild_id))


    @commands.hybrid_command(name='vc', description='ボイスチャンネルに参加し、このテキストチャンネルのメッセージを読み上げます')
    async def join_vc(self, ctx):
        await ctx.defer()
        if ctx.author.voice:
            channel = ctx.author.voice.channel
            await channel.connect()
        
        # コマンドを実行したチャンネルを通知用テキストチャンネルとして保存
            self.guild_text_channels[ctx.guild.id] = ctx.channel.id

            text_channel_url = f"https://discord.com/channels/{ctx.guild.id}/{ctx.channel.id}"

        # Embedメッセージの作成
            embed = Embed(title="接続しました。",
                        colour=0x00bfff)
            embed.add_field(name="ユーザー", value=ctx.author.mention, inline=True)
            embed.add_field(name="読み上げチャンネル", value=f"[{ctx.channel.name}]({text_channel_url})", inline=True)
            embed.add_field(name="接続チャンネル", value=channel.name, inline=True)
            embed.add_field(name="コマンド使用時間", value=datetime.now().strftime("%Y/%m/%d %H:%M"), inline=False)
        
            await ctx.send(embed=embed)
        else:
            await ctx.send('あなたは現在ボイスチャンネルに接続されていません。')

    @commands.hybrid_command(name='register_dict', description='辞書にカスタム読みを登録します')
    async def register_dict(self, ctx, word: str, pronunciation: str):
        if not re.match(r'^[\u3040-\u309F\u30A0-\u30FF]+$', pronunciation):
            await ctx.send('発音にはひらがなまたはカタカナを使用してください。')
            return

        # 文字列化はせず、整数のまま取得する
        guild_id = ctx.guild.id

        # DB から読み出したり、self.guild_dicts にすでにあれば使う
        custom_dict = self.guild_dicts.setdefault(guild_id, load_guild_dict(guild_id))

        entry_id = str(uuid.uuid4().int >> 64)
        entry = {
            "word": word,
            "pronunciation": pronunciation,
            "user": ctx.author.name,
            "time": datetime.now().strftime("%Y/%m/%d:%H:%M")
        }
        custom_dict[entry_id] = entry

        # 保存時も guild_id を int のまま渡す
        save_guild_dict(guild_id, custom_dict)

        embed = Embed(title="辞書", 
                      description="設定が変更されました", 
                      color=0x66cdaa)
        embed.add_field(name="置き換え",
                        value=f'[{word}] を [{pronunciation}] に置き換えしました！',
                        inline=False)
        embed.add_field(name="辞書ID", value=entry_id, inline=False)

        await ctx.send(embed=embed)

    

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author == self.bot.user:
            return

        guild_id = message.guild.id
        custom_dict = self.guild_dicts.get(guild_id, {})

    # もし self.guild_dicts に入っていなければ DB から読む
        if not custom_dict:
            custom_dict = load_guild_dict(guild_id)
            self.guild_dicts[guild_id] = custom_dict

        text = message.content  # メッセージ内容をテキストに格納

    # 置き換え処理
        text = replace_words(text, custom_dict)
        target_channel_id = self.guild_text_channels.get(guild_id)

        if target_channel_id is None or message.channel.id != target_channel_id:
            return

        if 'http://' in message.content or 'https://' in message.content:
            return

        numbers = re.findall(r'\d+', message.content)
        if any(int(num) >= 100_000_000 for num in numbers):
            return

    # Check for attachments and add to queue
        if message.attachments:
            for attachment in message.attachments:
                if any(attachment.filename.lower().endswith(ext) for ext in ['png', 'jpg', 'jpeg', 'gif']):
                    self.audio_queue.setdefault(guild_id, []).append(('image', attachment.url))

        self.audio_queue.setdefault(guild_id, []).append(('text', message))

        if not self.is_playing.get(guild_id, False):
            await self.play_audio(guild_id)

    async def play_audio(self, guild_id):
        if guild_id not in self.audio_queue or not self.audio_queue[guild_id]:
            return

        message_type, content = self.audio_queue[guild_id].pop(0)
        voice_client = discord.utils.get(self.bot.voice_clients, guild__id=guild_id)

        if not voice_client:
            logging.error('Voice client is not connected for audio playback.')
            return

        if message_type == 'image':
            await self.send_image(guild_id, content)
        else:
            message = content
            text = message.content

        # デバッグ: 置換前のメッセージ
            logging.debug(f"Original Text: {text}")

            custom_dict = self.guild_dicts.get(guild_id, {})
            text = replace_words(text, custom_dict)

        # デバッグ: 置換後のメッセージ
            logging.debug(f"Replaced Text: {text}")

            if len(text) > 500:
                text = text[:10] + "以下略"

            try:
                user_id = str(message.author.id)
                speaker_id = self.user_settings.get(user_id, DEFAULT_SPEAKER_ID)
                user_settings = user_settings_collection.find_one({'user_id': user_id}) or {}
                intensity = user_settings.get('intensity', 1.0)
                pitch = user_settings.get('pitch', 0)
                speed = user_settings.get('speed', 1.0)

                async with aiohttp.ClientSession() as session:
                    query_url = f"{self.voicevox_url}/audio_query"
                    params = {'text': text, 'speaker': speaker_id}
                    async with session.post(query_url, params=params) as query_resp:
                        query_resp.raise_for_status()
                        audio_query = await query_resp.json()
                        audio_query['intonationScale'] = intensity
                        audio_query['pitchScale'] = pitch
                        audio_query['speedScale'] = speed

                    synthesis_url = f"{self.voicevox_url}/synthesis"
                    async with session.post(synthesis_url, params={'speaker': speaker_id}, json=audio_query) as synthesis_resp:
                        synthesis_resp.raise_for_status()
                        audio_content = await synthesis_resp.read()

                audio_filename = f"voice_output_{uuid.uuid4()}.wav"
                with open(audio_filename, 'wb') as audio_file:
                    audio_file.write(audio_content)

                self.is_playing[guild_id] = True

                def after_playing(error):
                    if os.path.exists(audio_filename):
                        os.remove(audio_filename)
                    self.is_playing[guild_id] = False
                    future = asyncio.run_coroutine_threadsafe(self.play_audio(guild_id), self.bot.loop)
                    future.result()

                voice_client.play(discord.FFmpegPCMAudio(audio_filename), after=after_playing)

            except aiohttp.ClientError as e:
                logging.error(f'VoiceVox APIエラー: {e}')
                self.is_playing[guild_id] = False
                await self.play_audio(guild_id)

    async def send_image(self, guild_id, image_url):
        # This method is a placeholder to handle image sending
        # Implement your logic here to send the image wherever necessary
        pass
  

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        guild_id = member.guild.id

        try:
            if before.channel is None and after.channel is not None:
                if member.voice:
                    voice_client = discord.utils.get(self.bot.voice_clients, guild=member.guild)
                    if voice_client and voice_client.channel == after.channel:
                        if member.id == self.bot.user.id:
                            await self.handle_bot_join(after.channel.guild, member.voice.channel)
                        else: 
                            nickname = member.display_name
                            text = f"{nickname}さんが入室しました"

                            message = DummyMessage(self.bot, text, after.channel.guild)
                            message.author = member
                            message.channel = self.get_guild_text_channel(after.channel.guild.id)

                            self.audio_queue[guild_id].append(message)

                            if not self.is_playing[guild_id]:
                                await self.play_audio(guild_id)

            if before.channel is not None and after.channel is None:
                await self.handle_channel_empty(before.channel)

        except Exception as e:
            logging.error(f'Error in on_voice_state_update for guild {guild_id}: {e}')

    async def handle_bot_join(self, guild, channel):
    
        pass

    async def handle_channel_empty(self, channel):
        guild_id = channel.guild.id
        if len(channel.members) == 1 and channel.members[0].id == self.bot.user.id:
            voice_client = discord.utils.get(self.bot.voice_clients, guild=channel.guild)
            if voice_client and voice_client.is_connected():
                await voice_client.disconnect()

                text_channel = self.get_guild_text_channel(guild_id)
                if text_channel:
                    await text_channel.send('ボイスチャンネルに誰もいなくなったため、退出しました。')



    @commands.hybrid_command(name='list_dict', description='登録された辞書の一覧を表示します')

    async def list_dict(self, ctx):
        guild_id = str(ctx.guild.id)
        custom_dict = self.guild_dicts.get(guild_id, load_guild_dict(guild_id))
        if not custom_dict:
            await ctx.send('辞書にはまだ登録がありません。')
            return

        def create_embed(page, per_page=6):
            embed = Embed(title=f'辞書リスト ページ {page + 1}/{math.ceil(len(custom_dict) / per_page)}',
                        colour=0x66cdaa)
            start = page * per_page
            end = start + per_page

            for i, (entry_id, entry) in enumerate(list(custom_dict.items())[start:end], start=1):

                if isinstance(entry, dict):
                    word = entry.get("word", "不明")
                    pronunciation = entry.get("pronunciation", "不明")
                    user = entry.get("user", "不明")
                    time = entry.get("time", "不明")

                    embed.add_field(name=f"ID: {entry_id}",
                                    value=f"{word} => {pronunciation}\n"
                                        f"User: @{user}\n"
                                        f"Time: {time}", inline=False)

            return embed

        class Paginator(View):
            def __init__(self, max_pages):
                super().__init__()
                self.page = 0
                self.max_pages = max_pages

            @discord.ui.button(label="<<", style=discord.ButtonStyle.grey)
            async def prev_page(self, interaction: Interaction, button: Button):
                self.page = max(self.page - 1, 0)
                await interaction.response.edit_message(embed=create_embed(self.page))

            @discord.ui.button(label=">>", style=discord.ButtonStyle.grey)
            async def next_page(self, interaction: Interaction, button: Button):
                self.page = min(self.page + 1, self.max_pages - 1)
                await interaction.response.edit_message(embed=create_embed(self.page))

        paginator = Paginator(math.ceil(len(custom_dict) / 6))
        await ctx.send(embed=create_embed(0), view=paginator)

    @commands.hybrid_command(name='remove_dict', description='辞書から指定された単語を削除します')
    async def remove_dict(self, ctx, word: str):
        guild_id = str(ctx.guild.id)
        custom_dict = self.guild_dicts.setdefault(guild_id, load_guild_dict(guild_id))

        found = False
        for entry_id, entry in list(custom_dict.items()):
            if isinstance(entry, dict) and entry.get('word') == word:
                del custom_dict[entry_id]
                found = True
                break

        if found:
            save_guild_dict(guild_id, custom_dict)
            await ctx.send(f'"{word}" を辞書から削除しました。')
        else:
            await ctx.send(f'"{word}" は辞書に登録されていません。')

    def get_guild_text_channel(self, guild_id):
        return self.bot.get_channel(self.guild_text_channels.get(guild_id))


async def setup(bot):
    await bot.add_cog(event1(bot))

def replace_words(text, custom_dict):
    # 各エントリーを確認し、wordに対する置き換えを行う
    for entry_id, entry in custom_dict.items():
        if isinstance(entry, dict):
            word = entry['word']
            pronunciation = entry['pronunciation']
            # メッセージ中の単語(word)を置き換える
            text = text.replace(word, pronunciation)
    return text


class DummyMessage:
    def __init__(self, bot, content, guild):
        self.bot = bot  # botを保存します
        self.content = content
        self.guild = guild
        self.author = None
        self.channel = None  # 後から設定します


        