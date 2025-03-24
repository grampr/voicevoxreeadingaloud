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


def load_user_settings():
    settings = user_settings_collection.find_one({})
    return settings if settings else {}

def save_user_settings(settings):
    user_settings_collection.update_one({}, {"$set": settings}, upsert=True)

def load_guild_dict(guild_id):
    guild_dict = guild_dicts_collection.find_one({'guild_id': guild_id})
    return guild_dict if guild_dict else {}

def save_guild_dict(guild_id, custom_dict):
    custom_dict['guild_id'] = guild_id
    guild_dicts_collection.update_one({'guild_id': guild_id}, {"$set": custom_dict}, upsert=True)





class Voice(commands.Cog):

    def __init__(self, bot):
        self.bot = bot
        self.audio_queue = {}  # サーバーごとにキューを持つ
        self.is_playing = {}
        self.user_settings = load_user_settings()
        self.guild_dicts = {}
        self.text_channel_id = None
        self.voicevox_url = VOICEVOX_URL  # 環境変数から取得
        self.guild_text_channels = {} 

    def get_guild_text_channel(self, guild_id):
        return self.bot.get_channel(self.guild_text_channels.get(guild_id))
    
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


    @commands.hybrid_command(name='skip', description='現在再生中の音声をスキップします')
    async def skip_audio(self, ctx):
        if self.is_playing and self.current_voice_client and self.current_voice_client.is_playing():
            self.current_voice_client.stop()
            await ctx.send("再生中の音声をスキップしました。")
        else:
            await ctx.send("読み上げていませんので実行できません。")

    async def play_saved_audio(self, filename, guild):
        voice_client = discord.utils.get(self.bot.voice_clients, guild=guild)
        self.current_voice_client = voice_client
        if not voice_client:
            logging.error("ボイスチャンネルに接続されていません。再生できません。")
            return
        voice_client.play(discord.FFmpegPCMAudio(filename), after=lambda e: self.after_play_audio(e))
        self.is_playing = True

    @commands.hybrid_command(name='set_speaker', description='ユーザーごとの話者およびスタイルを設定します')
    @discord.app_commands.choices(
        speaker_name=[
            discord.app_commands.Choice(name="四国めたん", value="四国めたん"),
            discord.app_commands.Choice(name="ずんだもん", value="ずんだもん"),
            discord.app_commands.Choice(name="春日部つむぎ", value="春日部つむぎ"),
            discord.app_commands.Choice(name="冥鳴ひまり", value="冥鳴ひまり"),
        ],
        style_name=[
            discord.app_commands.Choice(name="あまあま", value="あまあま"),
            discord.app_commands.Choice(name="ノーマル", value="ノーマル"),
            discord.app_commands.Choice(name="ささやき", value="ささやき"),
            discord.app_commands.Choice(name="ヘロヘロ", value="ヘロヘロ"),
            discord.app_commands.Choice(name="ヒソヒソ", value="ヒソヒソ"),
            discord.app_commands.Choice(name="なみだめ", value="なみだめ"),
            discord.app_commands.Choice(name="セクシー", value="セクシー"),
            discord.app_commands.Choice(name="ツンツン", value="ツンツン"),
    ])
    async def set_speaker(self, ctx, speaker_name: str, style_name: str = 'ノーマル'):
        if speaker_name not in SPEAKER_STYLE_OPTIONS:
            await ctx.send(f"無効な話者名です。有効な話者: {', '.join(SPEAKER_STYLE_OPTIONS.keys())}")
            return

        style_id = SPEAKER_STYLE_OPTIONS[speaker_name].get(style_name, SPEAKER_STYLE_OPTIONS[speaker_name]['ノーマル'])

        self.user_settings[str(ctx.author.id)] = style_id
        save_user_settings(self.user_settings)
        await ctx.send(f"{ctx.author.name} の話者が {speaker_name}（スタイル: {style_name}）に設定されました。")



    @commands.hybrid_command(name='leave_vc', description='ボイスチャンネルから退出します')
    async def leave_vc(self, ctx):
        voice_client = ctx.voice_client
        if voice_client:
            await voice_client.disconnect()
            await ctx.send('ボイスチャンネルから退出しました')
            self.text_channel_id = None
        else:
            await ctx.send("ボイスチャンネルに接続されていません")

    @commands.hybrid_command(name="set_voice_settings", description="音声設定を変更します。")
    @discord.app_commands.choices(
        intensity=[
            discord.app_commands.Choice(name="0.5", value=0.5),
            discord.app_commands.Choice(name="0.6", value=0.6),
            discord.app_commands.Choice(name="0.7", value=0.7),
            discord.app_commands.Choice(name="0.8", value=0.8),
            discord.app_commands.Choice(name="0.9", value=0.9),
            discord.app_commands.Choice(name="1.0", value=1.0),
            discord.app_commands.Choice(name="1.1", value=1.1),
            discord.app_commands.Choice(name="1.2", value=1.2),
            discord.app_commands.Choice(name="1.3", value=1.3),
            discord.app_commands.Choice(name="1.4", value=1.4),
            discord.app_commands.Choice(name="1.5", value=1.5),
        ],
        pitch=[
            discord.app_commands.Choice(name="0.00", value=0.00),
            discord.app_commands.Choice(name="0.03", value=0.03),
            discord.app_commands.Choice(name="0.06", value=0.06),
            discord.app_commands.Choice(name="0.075", value=0.075),
            discord.app_commands.Choice(name="0.09", value=0.09),
            discord.app_commands.Choice(name="0.12", value=0.12),
            discord.app_commands.Choice(name="0.15", value=0.15),
        ],
        speed=[
            discord.app_commands.Choice(name="0.5", value=0.5),
            discord.app_commands.Choice(name="0.6", value=0.6),
            discord.app_commands.Choice(name="0.7", value=0.7),
            discord.app_commands.Choice(name="0.8", value=0.8),
            discord.app_commands.Choice(name="0.9", value=0.9),
            discord.app_commands.Choice(name="1.0", value=1.0),
            discord.app_commands.Choice(name="1.1", value=1.1),
            discord.app_commands.Choice(name="1.2", value=1.2),
            discord.app_commands.Choice(name="1.3", value=1.3),
            discord.app_commands.Choice(name="1.4", value=1.4),
            discord.app_commands.Choice(name="1.5", value=1.5),
            discord.app_commands.Choice(name="1.6", value=1.6),
            discord.app_commands.Choice(name="1.7", value=1.7),
            discord.app_commands.Choice(name="1.8", value=1.8),
            discord.app_commands.Choice(name="1.9", value=1.9),
            discord.app_commands.Choice(name="2.0", value=2.0),
        ]
    )
    async def set_voice_settings(self, ctx: commands.Context, intensity: discord.app_commands.Choice[float], pitch: discord.app_commands.Choice[float], speed: discord.app_commands.Choice[float]):
        if isinstance(ctx, commands.Context):
            user_id = str(ctx.author.id)
        else:
            user_id = str(ctx.user.id)

        settings = {
            'intensity': intensity.value,
            'pitch': pitch.value,
            'speed': speed.value
        }

        # MongoDBに設定を保存
        user_settings_collection.update_one(
            {'user_id': user_id},
            {'$set': settings},
            upsert=True
        )

        response_msg = f"音声設定を更新しました: 抑揚={intensity.name}, 音高={pitch.name}, 話速={speed.name}"

        if isinstance(ctx, commands.Context):
            await ctx.send(response_msg)
        else:
            await ctx.response.send_message(response_msg)

async def setup(bot):
    await bot.add_cog(Voice(bot))

