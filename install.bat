@echo off

REM Install Python packages using pip
pip install -U discord.py[voice]
pip install aiohttp
pip install pymongo
pip install python-dotenv

REM Install FFmpeg using winget
winget install --id=Gyan.FFmpeg --source=winget

echo Installation complete!
pause