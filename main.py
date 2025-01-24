import asyncio
import json
import logging
import logging.handlers
from datetime import datetime, timezone
import aiohttp
import config
import sys
import time
import os

if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

os.makedirs('logs', exist_ok=True)

class CustomFormatter(logging.Formatter):
    """Custom formatter that adds colors and simplified error format"""
    grey = "\x1b[38;21m"
    blue = "\x1b[38;5;39m"
    yellow = "\x1b[38;5;226m"
    red = "\x1b[38;5;196m"
    bold_red = "\x1b[31;1m"
    reset = "\x1b[0m"

    FORMATS = {
        logging.DEBUG: f"{grey}%(message)s{reset}",
        logging.INFO: f"{blue}%(message)s{reset}",
        logging.WARNING: f"{yellow}WARNING: %(message)s{reset}",
        logging.ERROR: f"{red}ERROR: %(message)s{reset}",
        logging.CRITICAL: f"{bold_red}CRITICAL: %(message)s{reset}",
    }

    def format(self, record):
        log_fmt = self.FORMATS.get(record.levelno)
        formatter = logging.Formatter(log_fmt)
        return formatter.format(record)

def setup_logging():
    """Configure logging with both console and file output"""
    logger = logging.getLogger('bzbot') 
    logger.setLevel(logging.INFO) 
    
    logger.handlers = []
    
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(CustomFormatter())
    logger.addHandler(console_handler)
    
    file_handler = logging.handlers.RotatingFileHandler(
        'logs/bzbot.log',  
        maxBytes=1024 * 1024,  # 1MB per file
        backupCount=5, 
        encoding='utf-8'
    )

    file_format = logging.Formatter(
        '%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    file_handler.setFormatter(file_format)
    logger.addHandler(file_handler)
    
    return logger

logger = setup_logging()

class BZBot:
    def __init__(self):
        """Initialize the GameWatch client"""
        self.session = None
        self.previous_sessions = {}
        self.message_ids = {}
        self.message_counter = 0
        self.is_running = True
        self.sessions = {}
        self.mods = {}
        self.last_update = None
        self.update_lock = asyncio.Lock()
        self.messages = {}
        self.active_sessions = {}
        self.player_counts = {}
        self.last_api_responses = {}
        self.last_known_states = {}
        self.last_known_mods = {}
        self.start_time = time.time()
        
        try:
            with open('vsrmaplist.json', 'r') as f:
                self.vsr_maps = json.load(f)
        except Exception as e:
            logger.error(f"Warning: Could not load vsrmaplist.json: {e}")
            self.vsr_maps = []

    async def initialize(self):
        self.session = aiohttp.ClientSession()
        
    async def close(self):
        if self.session:
            await self.session.close()

    async def fetch_api_data(self):
        """Fetch data from the API with better error handling"""
        try:
            logger.info(f"Fetching data from API: {config.API_URL}")
            async with self.session.get(config.API_URL) as response:
                if response.status == 200:
                    data = await response.json()
                    logger.debug("API request successful")
                    return data
                else:
                    logger.error(f"API request failed with status {response.status}")
                    logger.debug(f"Response: {await response.text()}")
                    return None
        except aiohttp.ClientError as e:
            logger.error(f"Network error during API request: {str(e)}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error during API request: {str(e)}")
            return None

    async def format_session_embed(self, session, mods_mapping, api_response=None):
        """Creates a Discord embed for a game session"""
        try:
            player_list = ""
            for player in session.get('Players', []):
                player_list += f"• {player.get('Name', 'Unknown')}\n"
            if not player_list:
                player_list = "No players"
            
            mod_field = "Unknown"
            game_data = session.get('Game', {})
            mod_id = str(game_data.get('Mod', ''))
            if mods_mapping and mod_id in mods_mapping:
                mod_data = mods_mapping[mod_id]
                mod_name = mod_data.get('Name', 'Unknown')
                mod_url = mod_data.get('Url', '')
                mod_field = f"[{mod_name}]({mod_url})" if mod_url else mod_name

            embed = {
                "title": "Join Game",
                "url": f"steam://run/1276390//+connect%20{session.get('Address')}",
                "color": 5793266,
                "fields": [
                    {"name": "👥  Players", "value": player_list, "inline": True},
                    {"name": "🔧  Mod", "value": mod_field, "inline": True},
                ],
                "timestamp": datetime.now(timezone.utc).isoformat()
            }

            profile_urls = {}
            profile_names = {}
            if api_response and 'DataCache' in api_response:
                player_ids = api_response['DataCache'].get('Players', {}).get('IDs', {})
                
                steam_data = player_ids.get('Steam', {})
                for steam_id, profile_data in steam_data.items():
                    profile_url = profile_data.get('ProfileUrl')
                    nickname = profile_data.get('Nickname')
                    if profile_url and nickname:
                        profile_urls[f"S{steam_id}"] = profile_url
                        profile_names[f"S{steam_id}"] = nickname
                
                gog_data = player_ids.get('Gog', {})
                for gog_id, profile_data in gog_data.items():
                    profile_url = profile_data.get('ProfileUrl')
                    username = profile_data.get('Username')
                    if profile_url and username:
                        profile_urls[f"G{gog_id}"] = profile_url
                        profile_names[f"G{gog_id}"] = username

            host_name = "Unknown"
            if session.get('Players') and len(session['Players']) > 0:
                host_player = session['Players'][0]
                host_ids = host_player.get('IDs', {})
                
                steam_data = host_ids.get('Steam', {})
                if steam_data and steam_data.get('ID'):
                    profile_key = f"S{steam_data['ID']}"
                else:
                    gog_data = host_ids.get('Gog', {})
                    profile_key = f"G{gog_data['ID']}" if gog_data and gog_data.get('ID') else None
                
                host_name = profile_names.get(profile_key, host_player.get('Name', 'Unknown'))

            player_count = session.get('PlayerCount', {}).get('Player', 0)
            player_types = session.get('PlayerTypes', [])
            max_players = player_types[0].get('Max', 0) if player_types else 0
            
            level = session.get('Level', {})
            game_mode = level.get('GameMode', {}).get('ID', 'Unknown')
            
            map_file = level.get('MapFile', '')
            if map_file:
                map_name = map_file.replace('.bzn', '')
                if map_name.endswith('25'):
                    map_name = map_name[:-2]
            else:
                map_name = 'Unknown'

            status = session.get('Status', {}).get('State', 'Unknown')
            time_seconds = session.get('Time', {}).get('Seconds', 0)
            time_mins = time_seconds // 60
            
            if status == "PreGame":
                status = f"In-Lobby ({time_mins} mins)"
            elif status == "InGame":
                status = f"In-Game ({time_mins} mins)"
            
            nat_type = session.get('Address', {}).get('NAT_TYPE', 'Unknown')
            
            game_version = session.get('Game', {}).get('Version', 'Unknown')
            mod_id = session.get('Game', {}).get('Mod')
            mod_name = mods_mapping.get(mod_id, {}).get('Name', 'Unknown')
            mod_url = mods_mapping.get(mod_id, {}).get('Url')

            if mod_url:
                mod_field = f"[{mod_name}]({mod_url})\n{game_version}"
            else:
                mod_field = f"{mod_name}\n{game_version}"

            nat_id = session.get('Address', {}).get('NAT', '')
            formatted_nat = nat_id.replace('@', 'A').replace('-', '0').replace('_', 'L')
            join_url = f"https://join.bz2vsr.com/{formatted_nat}"

            embed = {
                "title": "▶️  Join Game",
                "url": join_url,
                "fields": [],
                "footer": {
                    "text": f"GameWatch • Last Updated: {datetime.now().strftime('%I:%M %p')} 🔄"
                },
                "color": 3447003  
            }

            embed["fields"].extend([
                {"name": "🎮  Game Name", "value": f"```{session.get('Name', 'Unnamed')}```", "inline": True},
                {"name": "👤  Host", "value": f"```{host_name}```", "inline": True},
                {"name": "\u200b", "value": "\u200b", "inline": True},
                {"name": "👥  Players", "value": f"```{player_count}/{max_players}```", "inline": True},
                {"name": "📊  Status", "value": f"```{status}```", "inline": True},
                {"name": "\u200b", "value": "\u200b", "inline": True},
                {"name": "🎲  Mode", "value": f"```{game_mode}```", "inline": True},
                {"name": "🌐  NAT Type", "value": f"```{nat_type}```", "inline": True},
                {"name": "\u200b", "value": "\u200b", "inline": True},
            ])

            is_locked = session.get('Status', {}).get('IsLocked', False)
            if is_locked:
                embed["fields"].extend([
                    {"name": "🔒  Locked", "value": "```ansi\n\u001b[31mYes\u001b[0m```", "inline": True},
                    {"name": "\u200b", "value": "\u200b", "inline": True},
                    {"name": "\u200b", "value": "\u200b", "inline": True},
                ])

            teams = {}
            profile_names = {}
            profile_urls = {}

            for player in session.get('Players', []):
                team_data = player.get('Team', {})
                team_id = str(team_data.get('ID', team_data.get('SubTeam', {}).get('ID', -1)))
                
                if team_id not in teams:
                    teams[team_id] = []
                
                player_ids = player.get('IDs', {})
                
                steam_data = player_ids.get('Steam', {})
                if steam_data and steam_data.get('ID'):
                    profile_key = f"S{steam_data['ID']}"
                    if api_response:
                        steam_info = api_response.get('DataCache', {}).get('Players', {}).get('IDs', {}).get('Steam', {}).get(steam_data['ID'], {})
                        profile_urls[profile_key] = steam_info.get('ProfileUrl')
                        profile_names[profile_key] = steam_info.get('Nickname', player.get('Name', 'Unknown'))
                else:
                    gog_data = player_ids.get('Gog', {})
                    if gog_data and gog_data.get('ID'):
                        profile_key = f"G{gog_data['ID']}"
                        if api_response:
                            gog_info = api_response.get('DataCache', {}).get('Players', {}).get('IDs', {}).get('Gog', {}).get(gog_data['ID'], {})
                            profile_urls[profile_key] = gog_info.get('ProfileUrl')
                            profile_names[profile_key] = gog_info.get('Username', player.get('Name', 'Unknown'))
                    else:
                        profile_key = None
                
                player_name = profile_names.get(profile_key, player.get('Name', 'Unknown'))
                
                if team_data.get('Leader') is True:
                    prefix = "C: "
                else:
                    prefix = ""
                
                if profile_key and profile_urls.get(profile_key):
                    player_name = f"{prefix}[{player_name}]({profile_urls[profile_key]})"
                else:
                    player_name = f"{prefix}{player_name}"
                
                kills = player.get('Stats', {}).get('Kills', 0)
                deaths = player.get('Stats', {}).get('Deaths', 0)
                score = player.get('Stats', {}).get('Score', 0)
                
                player_with_stats = f"{player_name} ({kills}/{deaths}/{score})"
                teams[team_id].append(player_with_stats)

            is_mpi = session.get('Level', {}).get('GameMode', {}).get('ID', 'Unknown') == "MPI"
            is_strat = session.get('Level', {}).get('GameMode', {}).get('ID', 'Unknown') == "STRAT"
            
            if is_strat or is_mpi:
                embed["fields"].append({"name": "\u200b", "value": "\u200b", "inline": False})

                team1_players = teams.get('1', [])
                team1_value = "\n".join(team1_players) if team1_players else "*Empty*"
                embed["fields"].append({
                    "name": "👥  **TEAM 1**",
                    "value": team1_value,
                    "inline": True
                })

                if is_mpi:
                    team2_value = "**Computer**"
                else:
                    team2_players = teams.get('2', [])
                    team2_value = "\n".join(team2_players) if team2_players else "*Empty*"
                
                embed["fields"].append({
                    "name": "👥  **TEAM 2**",
                    "value": team2_value,
                    "inline": True
                })

                embed["fields"].append({"name": "\u200b", "value": "\u200b", "inline": True})

                embed["fields"].append({"name": "\u200b", "value": "\u200b", "inline": False})

            map_file = session.get('Level', {}).get('MapFile', 'Unknown')
            map_name = session.get('Level', {}).get('Name', 'Unknown')
            
            if ':' in map_name:
                map_name = map_name.split(':')[-1].strip()
            
            clean_map_file = map_file.lower().replace('.bzn', '')
            if clean_map_file.endswith('25'):
                clean_map_file = clean_map_file[:-2]
            
            map_details = f"Name: {map_name}\n"
            map_details += f"File: {clean_map_file}\n"
            
            if map_file:
                vsr_map = next((m for m in self.vsr_maps if m.get('File', '').lower() == clean_map_file.lower()), None)
                
                if vsr_map:
                    pools = vsr_map.get('Pools', 'Unknown')
                    loose = vsr_map.get('Loose', 'Unknown')
                    b2b = vsr_map.get('Size', {}).get('baseToBase', 'Unknown')
                    size = vsr_map.get('Size', {}).get('formattedSize', 'Unknown')
                    author = vsr_map.get('Author', 'Unknown')
                    
                    map_details += f"\nPools: {pools}"
                    map_details += f"\nLoose: {loose}"
                    map_details += f"\nB2B Distance (m): {b2b}"
                    map_details += f"\nSize (m): {size}"
                    map_details += f"\nAuthor: {author}"
            
            embed["fields"].extend([
                {"name": "🗺️  Map Details", "value": f"[Browse Maps](https://bz2vsr.com/maps/?map={clean_map_file})\n```{map_details}```", "inline": False},
            ])

            embed["fields"].extend([
                {"name": "", "value": mod_field, "inline": True}
            ])

            map_image = session.get('Level', {}).get('Image')
            if map_image:
                embed["thumbnail"] = {"url": map_image}

            return embed
            
        except Exception as e:
            logger.error(f"An error occurred: {str(e)}")
            return None

    async def send_discord_notification(self, session, mods_mapping, is_new=False, new_session_count=0, api_response=None):
        embed = await self.format_session_embed(session, mods_mapping, api_response)
        session_id = session['ID']
        
        try:
            if is_new or session_id not in self.message_ids:
                content = ""
                if new_session_count > 0:
                    if new_session_count == 1:
                        host_name = "Unknown"
                        if session.get('Players'):
                            host_player = session['Players'][0]
                            host_ids = host_player.get('IDs', {})
                            
                            steam_data = host_ids.get('Steam', {})
                            if steam_data and steam_data.get('ID'):
                                profile_key = f"S{steam_data['ID']}"
                            else:
                                gog_data = host_ids.get('Gog', {})
                                profile_key = f"G{gog_data['ID']}" if gog_data and gog_data.get('ID') else None
                            
                            if api_response and 'DataCache' in api_response:
                                player_ids = api_response['DataCache'].get('Players', {}).get('IDs', {})
                                if profile_key and profile_key.startswith('S'):
                                    steam_id = profile_key[1:]
                                    host_name = player_ids.get('Steam', {}).get(steam_id, {}).get('Nickname', host_name)
                                elif profile_key and profile_key.startswith('G'):
                                    gog_id = profile_key[1:]
                                    host_name = player_ids.get('Gog', {}).get(gog_id, {}).get('Username', host_name)
                        
                        content = f"🆕 Game Up (Host: {host_name}) @everyone"
                    else:
                        content = f"🆕 {new_session_count} Games Up @everyone"
                
                webhook_url = f"{config.DISCORD_WEBHOOK_URL}?wait=true"
                webhook_data = {
                    "content": content,
                    "embeds": [embed]
                }
                
                async with self.session.post(webhook_url, json=webhook_data) as response:
                    if response.status == 200:
                        response_data = await response.json()
                        self.message_ids[session_id] = response_data['id']
                        logger.info(f"New Discord notification sent for session: {session.get('Name')} (Message ID: {response_data['id']})")
                    else:
                        logger.error(f"Failed to send new Discord message: {response.status}")
                        logger.error(f"Response text: {await response.text()}")
            else:
                prev_session = self.active_sessions.get(session_id, {})
                changes = []
                
                logger.debug(f"Previous session players: {[p.get('Name') for p in prev_session.get('Players', [])]}")
                logger.debug(f"Current session players: {[p.get('Name') for p in session.get('Players', [])]}")
                
                prev_count = len(prev_session.get('Players', []))
                curr_count = len(session.get('Players', []))
                if prev_count != curr_count:
                    changes.append(f"players ({prev_count}->{curr_count})")
                
                prev_status = prev_session.get('Status', {}).get('State', '')
                curr_status = session.get('Status', {}).get('State', '')
                if prev_status != curr_status:
                    changes.append(f"status ({prev_status}->{curr_status})")
                
                prev_map = prev_session.get('Level', {}).get('MapFile', '')
                curr_map = session.get('Level', {}).get('MapFile', '')
                if prev_map != curr_map:
                    changes.append(f"map ({prev_map}->{curr_map})")
                
                prev_players = {}
                for p in prev_session.get('Players', []):
                    name = p.get('Name')
                    team_data = p.get('Team', {})
                    team_id = team_data.get('ID')
                    prev_players[name] = {
                        'team': str(team_id) if team_id is not None else '',
                        'stats': p.get('Stats', {})
                    }
                
                curr_players = {}
                for p in session.get('Players', []):
                    name = p.get('Name')
                    team_data = p.get('Team', {})
                    team_id = team_data.get('ID')
                    curr_players[name] = {
                        'team': str(team_id) if team_id is not None else '',
                        'stats': p.get('Stats', {})
                    }
                
                joined = set(curr_players.keys()) - set(prev_players.keys())
                left = set(prev_players.keys()) - set(curr_players.keys())
                if joined:
                    changes.append(f"joined ({', '.join(joined)})")
                if left:
                    changes.append(f"left ({', '.join(left)})")
                
                for name in set(prev_players.keys()) & set(curr_players.keys()):
                    prev_data = prev_players[name]
                    curr_data = curr_players[name]
                    
                    prev_team = prev_data['team']
                    curr_team = curr_data['team']
                    logger.debug(f"Comparing teams for {name}: prev={prev_team}, curr={curr_team}")
                    if prev_team != curr_team:
                        logger.debug(f"Team change detected for {name}: {prev_team} -> {curr_team}")
                        changes.append(f"{name} switched teams ({prev_team}->{curr_team})")
                    
                    prev_stats = prev_data['stats']
                    curr_stats = curr_data['stats']
                    if prev_stats != curr_stats:
                        stat_changes = []
                        for stat in ['Kills', 'Deaths', 'Score']:
                            prev_val = prev_stats.get(stat, 0)
                            curr_val = curr_stats.get(stat, 0)
                            if prev_val != curr_val:
                                stat_changes.append(f"{stat}: {prev_val}->{curr_val}")
                        if stat_changes:
                            changes.append(f"{name} stats ({', '.join(stat_changes)})")
                
                changes_str = ", ".join(changes) if changes else "no detected changes"
                logger.info(f"Updated Discord notification for session: {session.get('Name')} (Message ID: {session_id}) - Changes: {changes_str}")
                
                webhook_data = {
                    "embeds": [embed]
                }
                message_id = self.message_ids[session_id]
                update_url = f"{config.DISCORD_WEBHOOK_URL}/messages/{message_id}"
                
                async with self.session.patch(update_url, json=webhook_data) as response:
                    if response.status not in [200, 204]:
                        logger.error(f"Failed to update Discord message: {response.status}")
                        logger.error(f"Response text: {await response.text()}")
                        logger.warning(f"Update failed, removing message ID {message_id} and sending new message")
                        del self.message_ids[session_id]
                        await self.send_discord_notification(session, mods_mapping, is_new=True, api_response=api_response)
                        
        except Exception as e:
            logger.error(f"Error sending Discord notification: {str(e)}")
            logger.debug(f"Current message IDs: {self.message_ids}")

    async def send_player_count_notification(self, player_count, max_players, change_msg=None):
        """Send a notification about player count changes"""
        if change_msg:
            content = f"{player_count}/{max_players} ({change_msg}) @everyone"
        else:
            spots_left = max_players - player_count
            content = f"👥 {player_count}/{max_players} ({spots_left} spots left) @everyone"
        
        webhook_data = {
            "content": content
        }
        
        async with self.session.post(config.DISCORD_WEBHOOK_URL, json=webhook_data) as response:
            if response.status not in [200, 204]:
                logger.error(f"Failed to send player count notification: {response.status}")

    async def has_monitored_player(self, session):
        if session.get('Level', {}).get('GameMode', {}).get('ID') != "STRAT":
            return False
        
        for player in session.get('Players', []):
            player_ids = player.get('IDs', {})
            
            steam_data = player_ids.get('Steam', {})
            if steam_data and str(steam_data.get('ID')) in config.MONITORED_STEAM_IDS:
                return True
            
            gog_data = player_ids.get('Gog', {})
            if gog_data and str(gog_data.get('ID')) in config.MONITORED_STEAM_IDS:
                return True
            
            if player.get('Name') in config.MONITORED_STEAM_IDS:
                return True
        return False

    async def check_sessions(self):
        """Check for active game sessions"""
        try:
            api_response = await self.fetch_api_data()
            if not api_response:
                return

            self.mods = api_response.get('Mods', {})
            self.last_known_mods = {**self.last_known_mods, **self.mods}
            
            current_session_ids = {session['ID'] for session in api_response.get('Sessions', [])}
            
            for session_id in list(self.active_sessions.keys()):
                if session_id not in current_session_ids:
                    logger.info(f"Session {session_id} has ended, marking as ended")
                    await self.mark_session_ended(session_id, self.active_sessions[session_id], self.mods, api_response)
                    continue

            for session in api_response.get('Sessions', []):
                session_id = session.get('ID')
                session_name = session.get('Name', 'Unknown')
                if not session_id:
                    continue

                current_players = session.get('PlayerCount', {}).get('Player', 0)
                current_state = session.get('Status', {}).get('State')
                previous_state = self.last_known_states.get(session_id)

                if not await self.has_monitored_player(session):
                    if session_id in self.active_sessions:
                        await self.mark_session_ended(session_id, session, self.mods, api_response)
                    continue

                if previous_state == "InGame" and current_state == "PreGame":
                    logger.info(f"[{session_name}] Game ended, creating new embed")
                    
                    if session_id in self.message_ids:
                        old_message_id = self.message_ids[session_id]
                        try:
                            old_embed = await self.format_session_embed(self.active_sessions[session_id], self.mods, api_response)
                            old_embed['title'] = "❌  Game Ended"
                            old_embed.pop('url', None)
                            old_embed['color'] = 15158332
                            
                            webhook_url = f"{config.DISCORD_WEBHOOK_URL}/messages/{old_message_id}"
                            patch_data = {"embeds": [old_embed]}
                            async with self.session.patch(webhook_url, json=patch_data) as response:
                                if response.status not in [200, 204]:
                                    logger.error(f"Error updating old embed: {response.status}")
                        except Exception as e:
                            logger.error(f"Error updating old embed: {e}")
                        
                        self.message_ids.pop(session_id, None)
                    
                    embed = await self.format_session_embed(session, self.mods, api_response)
                    
                    host_name = "Unknown"
                    if session.get('Players'):
                        host_player = session['Players'][0]
                        host_ids = host_player.get('IDs', {})
                        
                        steam_data = host_ids.get('Steam', {})
                        if steam_data and steam_data.get('ID'):
                            profile_key = f"S{steam_data['ID']}"
                        else:
                            gog_data = host_ids.get('Gog', {})
                            profile_key = f"G{gog_data['ID']}" if gog_data and gog_data.get('ID') else None
                        
                        if api_response and 'DataCache' in api_response:
                            player_ids = api_response['DataCache'].get('Players', {}).get('IDs', {})
                            if profile_key and profile_key.startswith('S'):
                                steam_id = profile_key[1:]
                                host_name = player_ids.get('Steam', {}).get(steam_id, {}).get('Nickname', host_name)
                            elif profile_key and profile_key.startswith('G'):
                                gog_id = profile_key[1:]
                                host_name = player_ids.get('Gog', {}).get(gog_id, {}).get('Username', host_name)
                    
                    webhook_data = {
                        "content": f"🆕 Game Up (Host: {host_name}) @everyone",
                        "embeds": [embed]
                    }
                    
                    try:
                        webhook_url = f"{config.DISCORD_WEBHOOK_URL}?wait=true"
                        async with self.session.post(webhook_url, json=webhook_data) as response:
                            if response.status == 200:
                                response_data = await response.json()
                                self.message_ids[session_id] = response_data['id']
                            else:
                                logger.error(f"Error creating new embed: {response.status}")
                    except Exception as e:
                        logger.error(f"Error creating new embed: {e}")

                elif session_id in self.active_sessions:
                    max_players = session.get('PlayerTypes', [{}])[0].get('Max', 0)
                    previous_count = self.player_counts.get(session_id, 0)
                    
                    if current_players != previous_count:
                        current_players_list = {p.get('Name') for p in session.get('Players', [])}
                        previous_players_list = {p.get('Name') for p in self.active_sessions[session_id].get('Players', [])}
                        
                        if current_players > previous_count:
                            joined_players = current_players_list - previous_players_list
                            player_name = next(iter(joined_players)) if joined_players else "Unknown"
                            message = f"{current_players}/{max_players} ({player_name} joined) @everyone"
                            logger.info(f"[{session_name}] {player_name} joined ({current_players}/{max_players})")
                        else:
                            left_players = previous_players_list - current_players_list
                            player_name = next(iter(left_players)) if left_players else "Unknown"
                            message = f"{current_players}/{max_players} ({player_name} left) @everyone"
                            logger.info(f"[{session_name}] {player_name} left ({current_players}/{max_players})")
                        
                        try:
                            webhook_data = {
                                "content": message
                            }
                            async with self.session.post(config.DISCORD_WEBHOOK_URL, json=webhook_data) as response:
                                if response.status != 204:
                                    logger.error(f"[{session_name}] Failed to send notification: {response.status}")
                        except Exception as e:
                            logger.error(f"[{session_name}] Error sending notification: {e}")

                    if session_id in self.message_ids:
                        message_id = self.message_ids[session_id]
                        embed = await self.format_session_embed(session, self.mods, api_response)
                        webhook_data = {
                            "embeds": [embed]
                        }
                        webhook_url = f"{config.DISCORD_WEBHOOK_URL}/messages/{message_id}"
                        try:
                            async with self.session.patch(webhook_url, json=webhook_data) as response:
                                if response.status not in [200, 204]:
                                    logger.error(f"Error updating embed: {response.status}")
                        except Exception as e:
                            logger.error(f"Error updating embed: {e}")

                else:
                    embed = await self.format_session_embed(session, api_response.get('Mods', {}), api_response)
                    
                    host_name = "Unknown"
                    if session.get('Players') and len(session['Players']) > 0:
                        host_player = session['Players'][0]
                        host_ids = host_player.get('IDs', {})
                        
                        steam_data = host_ids.get('Steam', {})
                        if steam_data and steam_data.get('ID'):
                            profile_key = f"S{steam_data['ID']}"
                        else:
                            gog_data = host_ids.get('Gog', {})
                            profile_key = f"G{gog_data['ID']}" if gog_data and gog_data.get('ID') else None
                        
                        if api_response and 'DataCache' in api_response:
                            player_ids = api_response['DataCache'].get('Players', {}).get('IDs', {})
                            if profile_key and profile_key.startswith('S'):
                                steam_id = profile_key[1:]  
                                host_name = player_ids.get('Steam', {}).get(steam_id, {}).get('Nickname', host_name)
                            elif profile_key and profile_key.startswith('G'):
                                gog_id = profile_key[1:]  
                                host_name = player_ids.get('Gog', {}).get(gog_id, {}).get('Username', host_name)
                    
                    webhook_data = {
                        "content": f"🆕 Game Up (Host: {host_name}) @everyone",
                        "embeds": [embed]
                    }
                    
                    try:
                        webhook_url = f"{config.DISCORD_WEBHOOK_URL}?wait=true"
                        async with self.session.post(webhook_url, json=webhook_data) as response:
                            if response.status == 200:
                                response_data = await response.json()
                                self.message_ids[session_id] = response_data['id']
                            else:
                                logger.error(f"Error creating embed: {response.status}")
                    except Exception as e:
                        logger.error(f"Error creating embed: {e}")

                self.active_sessions[session_id] = session
                self.player_counts[session_id] = current_players
                self.last_known_states[session_id] = current_state

                self.last_api_responses[session_id] = api_response

        except Exception as e:
            logger.error(f"Error checking sessions: {e}")

    async def run(self):
        await self.initialize()
        try:
            logger.info(f"Bot started - checking every {config.CHECK_INTERVAL} seconds")
            logger.info("Press Ctrl+C to stop")
            while self.is_running:
                try:
                    await self.check_sessions()
                    await asyncio.sleep(config.CHECK_INTERVAL)
                except asyncio.CancelledError:
                    logger.info("Received shutdown signal...")
                    break
        except Exception as e:
            logger.error(f"An error occurred: {e}")
        finally:
            logger.info("Closing session...")
            await self.close()
            logger.info("Bot stopped")

    async def mark_session_ended(self, session_id, session, mods, api_response):
        """Mark a session as ended and update its Discord message"""
        if session_id in self.message_ids:
            message_id = self.message_ids[session_id]
            
            game_data = session.get('Game', {})
            mod_id = str(game_data.get('Mod', ''))
            mod_field = "Unknown"
            
            if mod_id in mods:
                mod_data = mods[mod_id]
                mod_name = mod_data.get('Name', 'Unknown')
                mod_url = mod_data.get('Url', '')
                mod_field = f"[{mod_name}]({mod_url})" if mod_url else mod_name
            elif mod_id in self.last_known_mods:
                mod_data = self.last_known_mods[mod_id]
                mod_name = mod_data.get('Name', 'Unknown')
                mod_url = mod_data.get('Url', '')
                mod_field = f"[{mod_name}]({mod_url})" if mod_url else mod_name
            
            last_embed = await self.format_session_embed(session, mods, api_response)
            
            teams = {}
            for player in session.get('Players', []):
                team_data = player.get('Team', {})
                team_id = str(team_data.get('ID', team_data.get('SubTeam', {}).get('ID', -1)))
                
                if team_id not in teams:
                    teams[team_id] = []
                
                player_ids = player.get('IDs', {})
                
                steam_data = player_ids.get('Steam', {})
                if steam_data and steam_data.get('ID'):
                    profile_key = f"S{steam_data['ID']}"
                else:
                    gog_data = player_ids.get('Gog', {})
                    profile_key = f"G{gog_data['ID']}" if gog_data and gog_data.get('ID') else None
                
                player_name = player.get('Name', 'Unknown')
                profile_url = None
                
                if profile_key and api_response and 'DataCache' in api_response:
                    player_ids = api_response['DataCache'].get('Players', {}).get('IDs', {})
                    if profile_key.startswith('S'):
                        steam_id = profile_key[1:]
                        steam_info = player_ids.get('Steam', {}).get(steam_id, {})
                        profile_url = steam_info.get('ProfileUrl')
                    elif profile_key.startswith('G'):
                        gog_id = profile_key[1:]
                        gog_info = player_ids.get('Gog', {}).get(gog_id, {})
                        profile_url = gog_info.get('ProfileUrl')
                
                if not profile_url and session_id in self.last_api_responses:
                    last_response = self.last_api_responses[session_id]
                    if 'DataCache' in last_response:
                        player_ids = last_response['DataCache'].get('Players', {}).get('IDs', {})
                        if profile_key and profile_key.startswith('S'):
                            steam_id = profile_key[1:]
                            steam_info = player_ids.get('Steam', {}).get(steam_id, {})
                            profile_url = steam_info.get('ProfileUrl')
                        elif profile_key and profile_key.startswith('G'):
                            gog_id = profile_key[1:]
                            gog_info = player_ids.get('Gog', {}).get(gog_id, {})
                            profile_url = gog_info.get('ProfileUrl')
                
                prefix = "C: " if team_data.get('Leader') is True else ""
                
                if profile_url:
                    player_name = f"{prefix}[{player_name}]({profile_url})"
                else:
                    player_name = f"{prefix}{player_name}"
                
                kills = player.get('Stats', {}).get('Kills', 0)
                deaths = player.get('Stats', {}).get('Deaths', 0)
                score = player.get('Stats', {}).get('Score', 0)
                player_with_stats = f"{player_name} ({kills}/{deaths}/{score})"
                teams[team_id].append(player_with_stats)
            
            for field in last_embed["fields"]:
                if field.get("name") == "👥  **TEAM 1**":
                    team1_players = teams.get('1', [])
                    field["value"] = "\n".join(team1_players) if team1_players else "*Empty*"
                elif field.get("name") == "👥  **TEAM 2**":
                    is_mpi = session.get('Level', {}).get('GameMode', {}).get('ID', 'Unknown') == "MPI"
                    if is_mpi:
                        field["value"] = "**Computer**"
                    else:
                        team2_players = teams.get('2', [])
                        field["value"] = "\n".join(team2_players) if team2_players else "*Empty*"
            
            last_embed["title"] = "❌  Session Ended"
            last_embed.pop("url", None)
            last_embed["color"] = 15158332
            
            for field in last_embed["fields"]:
                if field.get("name", "").strip() == "":
                    field["value"] = mod_field
                    break
            
            webhook_data = {
                "embeds": [last_embed]
            }
            
            update_url = f"{config.DISCORD_WEBHOOK_URL}/messages/{message_id}"
            async with self.session.patch(update_url, json=webhook_data) as response:
                if response.status in [200, 204]:
                    logger.info(f"Updated message for ended session: {session_id}")
                else:
                    logger.error(f"Failed to update ended session message: {response.status}")
            
            self.active_sessions.pop(session_id, None)
            self.message_ids.pop(session_id, None)
            self.player_counts.pop(session_id, None)
            self.last_api_responses.pop(session_id, None)
            self.last_known_states.pop(session_id, None)
            self.last_known_mods.pop(session_id, None)

    def format_player_name(self, player, api_response):
        """Format player name with profile link and leader prefix"""
        name = player.get('Name', 'Unknown')
        is_leader = player.get('Team', {}).get('Leader', False)
        prefix = "C: " if is_leader else ""
        
        player_ids = player.get('IDs', {})
        
        steam_data = player_ids.get('Steam', {})
        if steam_data:
            steam_id = steam_data.get('ID')
            if steam_id and api_response:
                steam_info = api_response.get('DataCache', {}).get('Players', {}).get('IDs', {}).get('Steam', {}).get(steam_id, {})
                if steam_info:
                    profile_url = steam_info.get('ProfileUrl')
                    if profile_url:
                        return f"{prefix}[{name}]({profile_url})"
        
        gog_data = player_ids.get('Gog', {})
        if gog_data:
            gog_id = gog_data.get('ID')
            if gog_id and api_response:
                gog_info = api_response.get('DataCache', {}).get('Players', {}).get('IDs', {}).get('Gog', {}).get(gog_id, {})
                if gog_info:
                    profile_url = gog_info.get('ProfileUrl')
                    if profile_url:
                        return f"{prefix}[{name}]({profile_url})"
        
        return f"{prefix}{name}"

    async def health_check(self):
        """Return basic health metrics"""
        return {
            "status": "healthy",
            "uptime": time.time() - self.start_time,
            "active_sessions": len(self.active_sessions),
            "last_api_response": self.last_update.isoformat() if self.last_update else None
        }

    async def send_webhook(self, webhook_data, message_id=None):
        try:
            webhook_url = config.DISCORD_WEBHOOK_URL
            if message_id:
                webhook_url = f"{webhook_url}/messages/{message_id}"
            
            method = "PATCH" if message_id else "POST"
            logger.info(f"Sending {method} request to webhook")
            
            async with self.session.request(method, webhook_url, json=webhook_data) as response:
                if response.status in [200, 204]:
                    logger.info(f"Webhook request successful: {response.status}")
                    if method == "POST":
                        return await response.json()
                    return True
                else:
                    error_text = await response.text()
                    logger.error(f"Webhook request failed: {response.status}")
                    logger.error(f"Error details: {error_text}")
                    logger.error(f"Webhook URL: {webhook_url}")
                    return None
        except Exception as e:
            logger.error(f"Error sending webhook: {str(e)}")
            return None

    async def create_embed(self, session, embed):
        webhook_data = {
            "embeds": [embed]
        }
        response = await self.send_webhook(webhook_data)
        if response:
            return response.get('id')
        return None

    async def update_embed(self, message_id, embed):
        webhook_data = {
            "embeds": [embed]
        }
        return await self.send_webhook(webhook_data, message_id)

    async def send_notification(self, content):
        webhook_data = {
            "content": content
        }
        return await self.send_webhook(webhook_data)

async def main():
    bot = BZBot()
    try:
        await bot.run()
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info("Bot stopped by user")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Program terminated by user") 